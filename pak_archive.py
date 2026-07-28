"""
pak_archive.py — Avatar ``PAK!`` v4 archive reader / writer.

Avatar: The Game ships its data as ``PAK!`` version-4 archives
(``data.pak``, ``patch.pak``, ``patch.pak0/1/...``).  The editor works on
loose folders, so the flow this module supports is:

    select a .pak  ->  extract to a folder  ->  edit normally  ->  repack

Format (verified byte-for-byte against retail archives)::

    PAK! | u32 version=4 | u32 offset_to_metadata | ...file data blob...

    at offset_to_metadata:
        u32 metadata_size            (compressed metadata + 4)
        [zlib chunks]                metadata, deflated in 64 KiB chunks
    at offset_to_metadata + metadata_size:
        u32 chunk_header_count
        chunk_header_count x (u32 cumulative_decompressed, u24 cumulative_end_offset, u8 flag)

    decoded metadata:
        u8  marker = 1
        u32 file_count
        part 1, per file:  u32 offset, u32 size, u32 crc32(path)
                           ceil(size / 65536) x (u16 stored_size, u16 flag)
        part 2, per file:  u64 FILETIME, u8 path_len, path bytes (utf-8)

Per chunk, ``flag == 65535`` means the chunk is STORED and its real length is
``65536 - stored_size``; anything else means LZO1X-compressed in
``stored_size`` bytes (a stored_size of 0 meaning a full 65536).

Notes for future maintainers
----------------------------
* The per-file chunk table makes the format randomly accessible — chunk *k*
  starts at ``file_offset + sum(stored_size[0:k])``.  :func:`read_file` uses
  that; nothing here needs to extract a whole archive to read one file.
* LZO1X is used through ``minilzo`` DLLs when they are present (measured
  487 MB/s compress / 792 MB/s decompress on real game data).  A pure-Python
  LZO1X **decompressor** is the fallback so reading never hard-depends on a
  native binary, and packing falls back to STORED chunks (legal per the
  format — the retail packer emits them whenever compression doesn't pay).
* This module deliberately imports no PyQt so it stays headlessly testable.
  UI lives in the callers.
"""

from __future__ import annotations

import binascii
import ctypes
import datetime
import io
import json
import os
import struct
import sys
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

MAGIC = b'PAK!'
VERSION = 4
CHUNK_SIZE = 65536
STORED_FLAG = 65535
MANIFEST_NAME = '.pak_manifest.json'
MANIFEST_VERSION = 1

#: Extensions the retail packer never compresses.
NEVER_COMPRESS = ('.vso', '.pso', '.rs', '.bik')

#: Editor scratch output that must never end up inside a repacked archive.
#: ``patch.pak1`` in the wild carries 2,686 of these (0.93 GB uncompressed)
#: because the external pak tool had no idea they weren't game data.
ARTIFACT_SUFFIXES = ('.fcb.converted.xml', '.bak')


class PakError(Exception):
    """Raised for malformed archives and unreadable/short streams."""


# --------------------------------------------------------------------------
# Encoding-safe logging
# --------------------------------------------------------------------------
# Progress messages carry check/cross glyphs.  On a cp1252 stdout (piped or
# redirected output) printing those raises UnicodeEncodeError — the same bug
# that used to abort the entire patch-folder scan with "0 worlds found", and
# the reason the stock pak tool dies at its final summary line.
_builtin_print = print


def print(*args, **kwargs):  # noqa: A001 — deliberate module-local shadow
    try:
        _builtin_print(*args, **kwargs)
    except UnicodeEncodeError:
        _builtin_print(*(str(a).encode('ascii', 'replace').decode('ascii')
                         for a in args), **kwargs)


def _mklog(log: Optional[Callable[[str], None]]):
    def _log(msg: str) -> None:
        if log is None:
            return
        try:
            log(msg)
        except Exception:
            pass
    return _log


# ==========================================================================
# LZO1X
# ==========================================================================

_lzo_c = None            # compression DLL handle
_lzo_d = None            # decompression DLL handle
_lzo_loaded = False
_lzo_lock = threading.Lock()   # minilzo's simple wrappers are not known-reentrant


def _dll_dirs() -> List[str]:
    """Candidate directories for the minilzo DLLs, dev and frozen layouts."""
    here = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, 'frozen', False):
        here = os.path.dirname(sys.executable)
    return [
        os.path.join(here, 'tools', 'pak_converter'),
        os.path.join(here, 'tools'),
        here,
    ]


def load_lzo_dlls() -> bool:
    """Load the minilzo DLLs if available.  Safe to call repeatedly.

    Returns True when the fast native path is usable.  A False result is not
    fatal: reading falls back to :func:`lzo1x_decompress_py` and packing falls
    back to STORED chunks.
    """
    global _lzo_c, _lzo_d, _lzo_loaded
    if _lzo_loaded:
        return _lzo_c is not None and _lzo_d is not None

    _lzo_loaded = True
    is_64 = sys.maxsize > 2 ** 32
    c_names = ['minilzo_c_x64.dll' if is_64 else 'minilzo_c_x86.dll', 'minilzo_c.dll']
    d_names = ['minilzo_d_x64.dll' if is_64 else 'minilzo_d_x86.dll', 'minilzo_d.dll']

    def _try(names):
        for d in _dll_dirs():
            for n in names:
                p = os.path.join(d, n)
                if os.path.exists(p):
                    try:
                        return ctypes.CDLL(p)
                    except Exception:
                        continue
        return None

    _lzo_c = _try(c_names)
    _lzo_d = _try(d_names)

    if _lzo_c is not None:
        try:
            _lzo_c.lzo1x_compress_simple.argtypes = [
                ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p,
                ctypes.POINTER(ctypes.c_size_t)]
            _lzo_c.lzo1x_compress_simple.restype = ctypes.c_int
        except Exception:
            _lzo_c = None
    if _lzo_d is not None:
        try:
            _lzo_d.lzo_decompress.argtypes = [
                ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p,
                ctypes.POINTER(ctypes.c_size_t)]
            _lzo_d.lzo_decompress.restype = ctypes.c_int
        except Exception:
            _lzo_d = None

    return _lzo_c is not None and _lzo_d is not None


def have_lzo_compression() -> bool:
    """True when chunks can be written compressed (else they go out STORED)."""
    load_lzo_dlls()
    return _lzo_c is not None


def lzo1x_decompress_py(src: bytes, dst_len: int) -> bytes:
    """Pure-Python LZO1X decompressor (fallback when the DLL is absent).

    Verified chunk-for-chunk against the native decoder on real archives.
    Roughly 30x slower than the DLL, so it is a compatibility net rather than
    the intended path.
    """
    out = bytearray()
    slen = len(src)
    if slen == 0:
        return b''

    LIT, MATCH, MATCH_NEXT, MATCH_DONE, FIRST_LIT = 0, 1, 2, 3, 4
    ip = 0
    t = 0

    try:
        if src[0] > 17:
            t = src[0] - 17
            ip = 1
            if t < 4:
                state = MATCH_NEXT
            else:
                out += src[ip:ip + t]
                ip += t
                state = FIRST_LIT
        else:
            state = LIT

        while True:
            if state == LIT:
                t = src[ip]
                ip += 1
                if t >= 16:
                    state = MATCH
                    continue
                if t == 0:
                    while src[ip] == 0:
                        t += 255
                        ip += 1
                    t += 15 + src[ip]
                    ip += 1
                out += src[ip:ip + t + 3]
                ip += t + 3
                state = FIRST_LIT
                continue

            if state == FIRST_LIT:
                t = src[ip]
                ip += 1
                if t >= 16:
                    state = MATCH
                    continue
                m = len(out) - (1 + 0x0800) - (t >> 2) - (src[ip] << 2)
                ip += 1
                if m < 0:
                    raise PakError("LZO back-reference before start of output")
                out.append(out[m])
                out.append(out[m + 1])
                out.append(out[m + 2])
                state = MATCH_DONE
                continue

            if state == MATCH_NEXT:
                out += src[ip:ip + t]
                ip += t
                t = src[ip]
                ip += 1
                state = MATCH
                continue

            if state == MATCH_DONE:
                t = src[ip - 2] & 3
                if t == 0:
                    state = LIT
                else:
                    state = MATCH_NEXT
                continue

            # state == MATCH
            done = False
            while True:
                if t >= 64:
                    m = len(out) - 1 - ((t >> 2) & 7) - (src[ip] << 3)
                    ip += 1
                    t = (t >> 5) - 1
                elif t >= 32:
                    t &= 31
                    if t == 0:
                        while src[ip] == 0:
                            t += 255
                            ip += 1
                        t += 31 + src[ip]
                        ip += 1
                    m = len(out) - 1 - ((src[ip] | (src[ip + 1] << 8)) >> 2)
                    ip += 2
                elif t >= 16:
                    m = len(out) - ((t & 8) << 11)
                    t &= 7
                    if t == 0:
                        while src[ip] == 0:
                            t += 255
                            ip += 1
                        t += 7 + src[ip]
                        ip += 1
                    m -= (src[ip] | (src[ip + 1] << 8)) >> 2
                    ip += 2
                    if m == len(out):
                        return bytes(out)          # end-of-stream marker
                    m -= 0x4000
                else:
                    m = len(out) - 1 - (t >> 2) - (src[ip] << 2)
                    ip += 1
                    if m < 0:
                        raise PakError("LZO back-reference before start of output")
                    out.append(out[m])
                    out.append(out[m + 1])
                    t = src[ip - 2] & 3
                    if t == 0:
                        done = True
                        break
                    out += src[ip:ip + t]
                    ip += t
                    t = src[ip]
                    ip += 1
                    continue

                if m < 0:
                    raise PakError("LZO back-reference before start of output")
                for _ in range(t + 2):             # may overlap — byte at a time
                    out.append(out[m])
                    m += 1
                t = src[ip - 2] & 3
                if t == 0:
                    done = True
                    break
                out += src[ip:ip + t]
                ip += t
                t = src[ip]
                ip += 1

            if done:
                state = LIT
                continue
    except IndexError:
        raise PakError("LZO stream truncated or corrupt") from None


def lzo_decompress(src: bytes, dst_len: int) -> bytes:
    """Decompress one LZO1X chunk, preferring the native decoder."""
    load_lzo_dlls()
    if _lzo_d is not None:
        n = ctypes.c_size_t(dst_len)
        buf = ctypes.create_string_buffer(dst_len)
        with _lzo_lock:
            rc = _lzo_d.lzo_decompress(ctypes.c_char_p(src), len(src), buf, ctypes.byref(n))
        if rc != 0:
            raise PakError(f"LZO decompression failed (code {rc})")
        return buf.raw[:n.value]
    return lzo1x_decompress_py(src, dst_len)


def lzo_compress(data: bytes) -> bytes:
    """Compress one chunk with LZO1X.  Requires the native compressor."""
    load_lzo_dlls()
    if _lzo_c is None:
        raise PakError("minilzo compression DLL not available")
    src_len = len(data)
    n = ctypes.c_size_t(src_len + src_len // 16 + 64 + 3)
    buf = ctypes.create_string_buffer(n.value)
    with _lzo_lock:
        rc = _lzo_c.lzo1x_compress_simple(ctypes.c_char_p(data), src_len, buf, ctypes.byref(n))
    if rc != 0:
        raise PakError(f"LZO compression failed (code {rc})")
    return buf.raw[:n.value]


# ==========================================================================
# Index
# ==========================================================================

@dataclass
class PakEntry:
    """One file inside an archive."""
    path: str                       # original stored path, e.g. r'levels\x\y.fcb'
    offset: int                     # absolute byte offset of chunk 0
    size: int                       # uncompressed size
    name_hash: int                  # crc32 of the stored path bytes
    chunks: List[Tuple[int, int]] = field(default_factory=list)   # (stored_size, flag)
    filetime: int = 0               # Windows FILETIME

    @property
    def key(self) -> str:
        """Case/separator-normalised lookup key."""
        return norm_key(self.path)

    def stored_span(self) -> int:
        """Total on-disk bytes occupied by this file's chunks."""
        total = 0
        for stored, flag in self.chunks:
            total += _on_disk_len(stored, flag)
        return total


@dataclass
class PakIndex:
    path: str
    entries: List[PakEntry]

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def total_size(self) -> int:
        return sum(e.size for e in self.entries)

    def by_key(self) -> Dict[str, PakEntry]:
        return {e.key: e for e in self.entries}


def norm_key(path: str) -> str:
    """Normalise a relative path for case-insensitive, separator-agnostic lookup."""
    return path.replace('/', '\\').lstrip('\\').lower()


def _on_disk_len(stored: int, flag: int) -> int:
    """Bytes this chunk occupies in the archive."""
    if flag == STORED_FLAG:
        return CHUNK_SIZE - stored
    return stored if stored else CHUNK_SIZE


def is_pak_file(path: str) -> bool:
    """Cheap magic check — true for a readable ``PAK!`` archive."""
    try:
        with open(path, 'rb') as f:
            return f.read(4) == MAGIC
    except OSError:
        return False


def read_index(pak_path: str) -> PakIndex:
    """Parse an archive's metadata.  Raises :class:`PakError` if malformed.

    Cheap even on huge archives: ``data.pak`` (89,904 files / 1.73 GB) parses
    in well under half a second.
    """
    file_size = os.path.getsize(pak_path)
    with open(pak_path, 'rb') as f:
        head = f.read(12)
        if len(head) < 12:
            raise PakError("File is too small to be a PAK archive")
        if head[:4] != MAGIC:
            raise PakError("Not a PAK archive (bad magic)")
        version = struct.unpack('<I', head[4:8])[0]
        if version != VERSION:
            raise PakError(f"Unsupported PAK version {version} (expected {VERSION})")
        meta_off = struct.unpack('<I', head[8:12])[0]
        if not (12 <= meta_off < file_size):
            raise PakError(f"Metadata offset {meta_off} outside archive")

        f.seek(meta_off)
        raw = f.read(4)
        if len(raw) < 4:
            raise PakError("Truncated archive (metadata size)")
        meta_size = struct.unpack('<I', raw)[0]
        if meta_off + meta_size + 4 > file_size:
            raise PakError("Truncated archive (metadata block)")

        f.seek(meta_off + meta_size)
        raw = f.read(4)
        if len(raw) < 4:
            raise PakError("Truncated archive (chunk header count)")
        n_chunks = struct.unpack('<I', raw)[0]
        hdr = io.BytesIO(f.read(n_chunks * 8))
        if len(hdr.getvalue()) < n_chunks * 8:
            raise PakError("Truncated archive (chunk header table)")

        f.seek(meta_off)
        parts: List[bytes] = []
        last_off = last_dec = 0
        for _ in range(n_chunks):
            dec_size = struct.unpack('<I', hdr.read(4))[0]
            sec = hdr.read(4)
            end_off = struct.unpack('<I', sec[:3] + b'\x00')[0]
            if end_off < last_off:
                raise PakError("Metadata chunk offsets are not monotonic")
            blob = f.read(end_off - last_off)
            # The first header is a sentinel accounting for the 4-byte size
            # field; it carries no decompressed payload.
            if dec_size != last_dec:
                try:
                    parts.append(zlib.decompress(blob))
                except zlib.error as exc:
                    raise PakError(f"Metadata inflate failed: {exc}") from exc
            last_off, last_dec = end_off, dec_size

    meta = io.BytesIO(b''.join(parts))
    total = len(meta.getvalue())
    if total < 5:
        raise PakError("Metadata block is empty")
    meta.read(1)                                    # marker, always 1
    n_files = struct.unpack('<I', meta.read(4))[0]
    if n_files == 0:
        raise PakError("Archive contains no files")
    if n_files * 12 > total:
        raise PakError(f"Implausible file count {n_files}")

    entries: List[PakEntry] = []
    for _ in range(n_files):
        rec = meta.read(12)
        if len(rec) < 12:
            raise PakError("Metadata ended inside the file table")
        offset, size, name_hash = struct.unpack('<III', rec)
        n_ch = (size + CHUNK_SIZE - 1) // CHUNK_SIZE
        raw = meta.read(n_ch * 4)
        if len(raw) < n_ch * 4:
            raise PakError("Metadata ended inside a chunk table")
        chunks = [struct.unpack_from('<HH', raw, i * 4) for i in range(n_ch)]
        entries.append(PakEntry(path='', offset=offset, size=size,
                                name_hash=name_hash, chunks=chunks))

    for e in entries:
        raw = meta.read(9)
        if len(raw) < 9:
            raise PakError("Metadata ended inside the path table")
        e.filetime = struct.unpack('<Q', raw[:8])[0]
        plen = raw[8]
        pb = meta.read(plen)
        if len(pb) < plen:
            raise PakError("Metadata ended inside a path string")
        e.path = pb.decode('utf-8', 'replace')

    return PakIndex(path=pak_path, entries=entries)


# ==========================================================================
# Reading
# ==========================================================================

def _decode_entry(fh, entry: PakEntry) -> bytes:
    """Read and decode one entry from an already-open archive handle."""
    fh.seek(entry.offset)
    parts: List[bytes] = []
    for stored, flag in entry.chunks:
        if flag == STORED_FLAG:
            n = CHUNK_SIZE - stored
            blob = fh.read(n)
            if len(blob) < n:
                raise PakError(f"Truncated stored chunk in {entry.path!r}")
            parts.append(blob)
        else:
            n = stored if stored else CHUNK_SIZE
            blob = fh.read(n)
            if len(blob) < n:
                raise PakError(f"Truncated compressed chunk in {entry.path!r}")
            parts.append(lzo_decompress(blob, CHUNK_SIZE))
    data = b''.join(parts)
    if len(data) != entry.size:
        raise PakError(
            f"{entry.path!r}: decoded {len(data)} bytes, metadata says {entry.size}")
    return data


def read_file(pak_path: str, entry: PakEntry) -> bytes:
    """Read a single file out of an archive without extracting anything else."""
    with open(pak_path, 'rb') as f:
        return _decode_entry(f, entry)


def read_stored_span(fh, entry: PakEntry) -> bytes:
    """Return an entry's raw, still-compressed bytes.

    Lets a repack copy an unchanged file straight through without a
    decompress/recompress round trip.
    """
    fh.seek(entry.offset)
    span = entry.stored_span()
    blob = fh.read(span)
    if len(blob) < span:
        raise PakError(f"Truncated chunk span for {entry.path!r}")
    return blob


# ==========================================================================
# Extraction
# ==========================================================================

@dataclass
class ExtractResult:
    folder: str
    extracted: int
    failed: List[str]
    total: int
    manifest_path: Optional[str] = None


def _filetime_to_dt(ft: int) -> datetime.datetime:
    return datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=ft // 10)


def _apply_filetime(path: str, ft: int) -> None:
    """Best-effort restore of a file's timestamps from a Windows FILETIME."""
    if not ft:
        return
    try:
        ts = ft / 10_000_000.0 - 11644473600.0
        if ts > 0:
            os.utime(path, (ts, ts))
    except Exception:
        pass


def extract(pak_path: str,
            out_dir: str,
            log: Optional[Callable[[str], None]] = None,
            progress: Optional[Callable[[int, int], None]] = None,
            cancel: Optional[Callable[[], bool]] = None,
            workers: Optional[int] = None,
            write_manifest_file: bool = True) -> ExtractResult:
    """Extract every file in ``pak_path`` beneath ``out_dir``.

    Existing files are overwritten; callers wanting the "you have local edits"
    guard should run :func:`scan_changes` against the manifest **first** (see
    :func:`describe_local_changes`).
    """
    _log = _mklog(log)
    index = read_index(pak_path)
    total = len(index.entries)
    _log(f"{os.path.basename(pak_path)}: {total:,} files, "
         f"{index.total_size / 1e6:.0f} MB uncompressed")

    os.makedirs(out_dir, exist_ok=True)
    # Pre-create directories once so the workers never race on makedirs.
    dirs = {os.path.dirname(os.path.join(out_dir, e.path.lstrip('\\/')))
            for e in index.entries}
    for d in dirs:
        if d:
            os.makedirs(d, exist_ok=True)

    failed: List[str] = []
    crcs: Dict[str, int] = {}
    done = 0
    lock = threading.Lock()
    aborted = threading.Event()

    def _one(entry: PakEntry):
        nonlocal done
        if aborted.is_set():
            return
        dest = os.path.join(out_dir, entry.path.lstrip('\\/'))
        try:
            with open(pak_path, 'rb', buffering=1024 * 1024) as fh:
                data = _decode_entry(fh, entry)
            with open(dest, 'wb') as out:
                out.write(data)
            _apply_filetime(dest, entry.filetime)
            # Checksum here, from bytes already in memory — re-reading the
            # whole extraction afterwards to build the manifest costs more
            # than the extraction did.
            crc = binascii.crc32(data) & 0xFFFFFFFF
            with lock:
                crcs[entry.path] = crc
            ok = True
        except Exception as exc:                     # noqa: BLE001 — reported, not raised
            ok = False
            with lock:
                failed.append(f"{entry.path}: {exc}")
        with lock:
            done += 1
            n = done
        if progress is not None and (n % 64 == 0 or n == total):
            try:
                progress(n, total)
            except Exception:
                pass
        if not ok and len(failed) <= 5:
            _log(f"  FAILED {entry.path}")
        if cancel is not None and n % 64 == 0:
            try:
                if cancel():
                    aborted.set()
            except Exception:
                pass

    if workers is None:
        workers = max(2, min((os.cpu_count() or 4), 16))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(_one, index.entries))

    extracted = done - len(failed)
    if aborted.is_set():
        _log(f"Cancelled after {extracted:,} files")
    else:
        _log(f"Extracted {extracted:,}/{total:,} files to {out_dir}")
    if failed:
        _log(f"{len(failed)} file(s) failed")

    manifest_path = None
    if write_manifest_file and not aborted.is_set():
        manifest_path = write_manifest(out_dir, pak_path, index, crcs=crcs)
        _log(f"Wrote {MANIFEST_NAME}")

    return ExtractResult(folder=out_dir, extracted=extracted, failed=failed,
                         total=total, manifest_path=manifest_path)


# ==========================================================================
# Manifest — what we extracted, so we can diff and guard against clobbering
# ==========================================================================

def manifest_path_for(folder: str) -> str:
    return os.path.join(folder, MANIFEST_NAME)


def write_manifest(folder: str, pak_path: str, index: PakIndex,
                   crcs: Optional[Dict[str, int]] = None) -> str:
    """Record the extracted file set: order, sizes, CRCs and timestamps.

    ``files`` is an *ordered* mapping — JSON round-trips insertion order, and
    preserving the archive's original file order is what makes a repack of an
    untouched extraction byte-reproducible.

    ``crcs`` supplies checksums the caller already computed (:func:`extract`
    hashes each file from the bytes it just decoded).  Without it every file is
    re-read from disk, which on a cold cache costs more than the extraction
    itself.
    """
    files = {}
    for e in index.entries:
        crc = None if crcs is None else crcs.get(e.path)
        if crc is None:
            dest = os.path.join(folder, e.path.lstrip('\\/'))
            crc = 0
            try:
                with open(dest, 'rb') as f:
                    crc = binascii.crc32(f.read()) & 0xFFFFFFFF
            except OSError:
                pass
        files[e.path] = [e.size, crc, e.filetime]

    data = {
        'manifest_version': MANIFEST_VERSION,
        'source_pak': os.path.abspath(pak_path),
        'source_size': os.path.getsize(pak_path),
        'source_mtime': int(os.path.getmtime(pak_path)),
        'extracted_utc': datetime.datetime.utcnow().isoformat(timespec='seconds'),
        'files': files,
    }
    path = manifest_path_for(folder)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
    return path


def read_manifest(folder: str) -> Optional[dict]:
    """Load a folder's extraction manifest, or None when absent/unreadable."""
    path = manifest_path_for(folder)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict) or 'files' not in data:
            return None
        return data
    except Exception:
        return None


def is_artifact(rel_path: str) -> bool:
    """True for editor scratch output that must never be packed."""
    low = rel_path.lower()
    if os.path.basename(low) == MANIFEST_NAME:
        return True
    return low.endswith(ARTIFACT_SUFFIXES)


def iter_folder(folder: str, skip_artifacts: bool = True):
    """Yield ``(relative_path, absolute_path)`` for packable files in a folder."""
    for dp, _dirs, files in os.walk(folder):
        for fn in files:
            ap = os.path.join(dp, fn)
            rel = os.path.relpath(ap, folder).replace('/', '\\')
            if skip_artifacts and is_artifact(rel):
                continue
            yield rel, ap


@dataclass
class ChangeSet:
    modified: List[str] = field(default_factory=list)
    added: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.modified) + len(self.added) + len(self.missing)

    def changed_paths(self) -> List[str]:
        """Paths that belong in a changed-only repack (modified + added)."""
        return self.modified + self.added


def scan_changes(folder: str, manifest: dict,
                 progress: Optional[Callable[[int, int], None]] = None) -> ChangeSet:
    """Diff a folder against its extraction manifest by size then CRC32."""
    recorded = {norm_key(p): (v[0], v[1]) for p, v in manifest['files'].items()}
    seen = set()
    cs = ChangeSet()

    entries = list(iter_folder(folder))
    for i, (rel, ap) in enumerate(entries):
        key = norm_key(rel)
        seen.add(key)
        rec = recorded.get(key)
        if rec is None:
            cs.added.append(rel)
            continue
        try:
            size = os.path.getsize(ap)
        except OSError:
            cs.added.append(rel)
            continue
        if size != rec[0]:
            cs.modified.append(rel)
            continue
        try:
            with open(ap, 'rb') as f:
                crc = binascii.crc32(f.read()) & 0xFFFFFFFF
        except OSError:
            cs.modified.append(rel)
            continue
        if crc != rec[1]:
            cs.modified.append(rel)
        if progress is not None and i % 256 == 0:
            try:
                progress(i, len(entries))
            except Exception:
                pass

    for p in manifest['files']:
        if norm_key(p) not in seen:
            cs.missing.append(p)
    return cs


def describe_local_changes(folder: str) -> Optional[ChangeSet]:
    """Convenience wrapper: diff a folder against its own manifest.

    Returns None when the folder has no manifest (never extracted here), which
    callers should treat as "unknown — don't assume it's safe to overwrite".
    """
    manifest = read_manifest(folder)
    if manifest is None:
        return None
    return scan_changes(folder, manifest)


# ==========================================================================
# Packing
# ==========================================================================

def _pack_offset_flag(offset: int, flag: int) -> bytes:
    return offset.to_bytes(3, 'little') + struct.pack('<B', flag)


def _encode_chunk(chunk: bytes, allow_compress: bool) -> Tuple[bytes, Tuple[int, int]]:
    """Return ``(bytes_to_write, (stored_size, flag))`` for one chunk."""
    n = len(chunk)
    if allow_compress:
        try:
            comp = lzo_compress(chunk)
        except PakError:
            comp = None
        if comp is not None and len(comp) < n:
            return comp, (len(comp), 0)
    # STORED: the size field holds the complement so a full chunk encodes as 0.
    return chunk, ((CHUNK_SIZE - n) % CHUNK_SIZE, STORED_FLAG)


@dataclass
class PackResult:
    path: str
    file_count: int
    bytes_written: int
    skipped_artifacts: int


def pack(folder: str,
         out_pak: str,
         only: Optional[Sequence[str]] = None,
         manifest: Optional[dict] = None,
         compress: bool = True,
         log: Optional[Callable[[str], None]] = None,
         progress: Optional[Callable[[int, int], None]] = None,
         cancel: Optional[Callable[[], bool]] = None,
         backup: bool = True) -> PackResult:
    """Pack ``folder`` into ``out_pak``.

    ``only``      — restrict to these relative paths (a changed-only mod pak).
    ``manifest``  — when given, its key order drives the output file order and
                    supplies each file's original FILETIME, so repacking an
                    untouched extraction reproduces the source archive.
    ``compress``  — False, or a missing compression DLL, writes STORED chunks.

    The archive is built to a temporary file and moved into place only on
    success, so an interrupted pack can never destroy an existing archive.
    """
    _log = _mklog(log)
    if compress and not have_lzo_compression():
        _log("minilzo compressor unavailable — writing uncompressed chunks")
        compress = False

    on_disk = dict(iter_folder(folder))
    # Count only real editor scratch output — our own manifest is bookkeeping,
    # not something the user thinks of as an excluded file.
    skipped = sum(1 for rel, _ in iter_folder(folder, skip_artifacts=False)
                  if is_artifact(rel)
                  and os.path.basename(rel).lower() != MANIFEST_NAME.lower())

    # Order: manifest order first (original archive order), then anything new.
    ordered: List[str] = []
    lookup = {norm_key(r): r for r in on_disk}
    if manifest:
        for p in manifest['files']:
            r = lookup.get(norm_key(p))
            if r is not None:
                ordered.append(r)
        known = {norm_key(p) for p in manifest['files']}
        ordered.extend(sorted(r for r in on_disk if norm_key(r) not in known))
    else:
        ordered = sorted(on_disk)

    if only is not None:
        wanted = {norm_key(p) for p in only}
        ordered = [r for r in ordered if norm_key(r) in wanted]

    if not ordered:
        raise PakError("Nothing to pack")

    ft_by_key: Dict[str, int] = {}
    if manifest:
        for p, v in manifest['files'].items():
            if len(v) > 2:
                ft_by_key[norm_key(p)] = v[2]

    _log(f"Packing {len(ordered):,} files"
         + (f" ({skipped:,} editor artifacts skipped)" if skipped else ""))

    tmp = out_pak + '.tmp'
    meta1 = bytearray()
    meta2 = bytearray()
    count = 0

    try:
        with open(tmp, 'wb', buffering=2 * 1024 * 1024) as pak:
            pak.write(MAGIC + struct.pack('<I', VERSION) + struct.pack('<I', 0))
            cursor = 12

            for i, rel in enumerate(ordered):
                if cancel is not None and i % 64 == 0:
                    try:
                        if cancel():
                            raise PakError("Cancelled")
                    except PakError:
                        raise
                    except Exception:
                        pass

                ap = on_disk[rel]
                path_bytes = rel.encode('utf-8')
                if len(path_bytes) > 255:
                    _log(f"  SKIP (path too long for the format): {rel}")
                    continue

                key = norm_key(rel)
                ft = ft_by_key.get(key)
                if ft is None:
                    try:
                        ft = int((os.path.getctime(ap) + 11644473600) * 10 ** 7)
                    except OSError:
                        ft = 0

                allow = compress and not rel.lower().endswith(NEVER_COMPRESS)
                start_cursor = cursor
                chunk_meta: List[Tuple[int, int]] = []
                size = 0
                with open(ap, 'rb', buffering=1024 * 1024) as f:
                    while True:
                        chunk = f.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        size += len(chunk)
                        blob, meta = _encode_chunk(chunk, allow)
                        pak.write(blob)
                        cursor += len(blob)
                        chunk_meta.append(meta)

                if size == 0:
                    # The format derives the chunk count from the size, so a
                    # zero-byte file has no chunks and round-trips cleanly.
                    chunk_meta = []

                meta1 += struct.pack('<I', start_cursor)
                meta1 += struct.pack('<I', size)
                meta1 += struct.pack('<I', binascii.crc32(path_bytes) & 0xFFFFFFFF)
                for stored, flag in chunk_meta:
                    meta1 += struct.pack('<HH', stored, flag)

                meta2 += struct.pack('<Q', ft)
                meta2 += struct.pack('<B', len(path_bytes))
                meta2 += path_bytes
                count += 1

                if progress is not None and (i % 32 == 0 or i == len(ordered) - 1):
                    try:
                        progress(i + 1, len(ordered))
                    except Exception:
                        pass

            if count == 0:
                raise PakError("Nothing to pack")

            meta_off = cursor
            raw_meta = struct.pack('<B', 1) + struct.pack('<I', count) + bytes(meta1) + bytes(meta2)

            stream = io.BytesIO(raw_meta)
            headers = struct.pack('<I', 0) + _pack_offset_flag(4, 128)
            header_count = 1
            end_off = 4
            dec = 0
            comp_parts: List[bytes] = []
            while True:
                block = stream.read(CHUNK_SIZE)
                if not block:
                    break
                dec += len(block)
                cblock = zlib.compress(block, 1)
                comp_parts.append(cblock)
                end_off += len(cblock)
                headers += struct.pack('<I', dec) + _pack_offset_flag(end_off, 128)
                header_count += 1

            comp_meta = b''.join(comp_parts)
            pak.write(struct.pack('<I', len(comp_meta) + 4))
            pak.write(comp_meta)
            pak.write(struct.pack('<I', header_count))
            pak.write(headers)

            pak.seek(8)
            pak.write(struct.pack('<I', meta_off))
            pak.flush()
            os.fsync(pak.fileno())

        if backup and os.path.exists(out_pak):
            bak = out_pak + '.bak'
            if not os.path.exists(bak):
                try:
                    os.replace(out_pak, bak)
                    _log(f"Backed up existing archive to {os.path.basename(bak)}")
                except OSError:
                    pass
        os.replace(tmp, out_pak)
    except BaseException:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise

    written = os.path.getsize(out_pak)
    _log(f"Wrote {os.path.basename(out_pak)} — {count:,} files, {written / 1e6:.1f} MB")
    return PackResult(path=out_pak, file_count=count, bytes_written=written,
                      skipped_artifacts=skipped)


def default_extract_dir(pak_path: str) -> str:
    """Where a ``.pak`` unpacks to by default: a sibling ``<name>_unpacked``."""
    base, _ = os.path.splitext(pak_path)
    ext = os.path.splitext(pak_path)[1].lstrip('.')
    suffix = f"_{ext}_unpacked" if ext and ext != 'pak' else "_unpacked"
    return base + suffix
