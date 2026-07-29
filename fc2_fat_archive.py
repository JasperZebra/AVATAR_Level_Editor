#!/usr/bin/env python3
"""Far Cry 2 ``.fat``/``.dat`` (Dunia FAT v5) reader — format only, no GUI.

The Avatar side of the editor reads ``PAK!`` archives via :mod:`pak_archive`;
this is the Far Cry 2 equivalent so both games can load their data the same way.
As with pak_archive the editor still only ever *works* against a folder — the
archive is purely how the data arrives.

Format
------
Verified byte-for-byte against retail ``Data_Win32\\worlds\\worlds.fat`` +
``worlds.dat`` (142,369 entries / 2.577 GB) by extracting files and diffing them
against an independently-unpacked copy of the same archive.

::

    header (16 bytes)
        char[4]  '2TAF'   (the u32 0x46415432, i.e. 'FAT2' little-endian)
        u32      version = 5
        u32      flags   = 0x00000301
        u32      entryCount
    entries (entryCount x 16 bytes, SORTED ASCENDING BY nameHash)
        u32 nameHash    CRC-32 of the lowercased path with '\\' separators
        u32 sizeField   0 -> stored verbatim; else (realSize << 2) | scheme
        u32 packField   (offsetLow2 << 30) | storedSize      [30-bit size]
        u32 offsetHigh  offset >> 2
    u32 trailer = 0            (so the file is exactly 16 + 16n + 4 bytes)

    offset     = offsetHigh * 4 + (packField >> 30)
    storedSize = packField & 0x3FFFFFFF

The two spare bits are the LOW bits of a byte offset, not a compression enum —
they are uniformly distributed, and folding them in is what takes extraction
from 28% to 100% byte-identical. ``scheme`` 0 means stored, 1 means LZO1X
(the same codec pak_archive already carries a decoder for).

Names
-----
The index holds **no filenames**, only hashes, so extraction needs a dictionary
of candidate paths to hash back. :func:`load_filelist` reads one;
:func:`build_name_map` hashes an iterable of paths. Anything unresolved is
written to ``__Unknown/<hash>.bin``, which is what other Dunia tools do too —
the level editor only needs ``levels/`` and ``worlds/`` to resolve, and those
follow strict naming conventions.

Writing archives is deliberately NOT implemented: the editor saves into the
unpacked folder, and repacking a FAT would need the compressor plus a way to
preserve the hash ordering.
"""

from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional

# Reuse the PAK module's LZO plumbing (DLL-accelerated, pure-Python fallback)
# and its encoding-safe print shim rather than duplicating either.
from pak_archive import lzo_decompress, load_lzo_dlls, print  # noqa: A004

# On disk the four magic bytes read '2TAF' — that is the u32 0x46415432 ('FAT2')
# stored little-endian. Compare the bytes, not the mnemonic.
FAT_MAGIC = b'2TAF'
FAT_VERSION = 5
HEADER_LEN = 16
ENTRY_LEN = 16

SCHEME_STORED = 0
SCHEME_LZO1X = 1

UNKNOWN_DIR = '__Unknown'

# Where a bundled path dictionary may live, tried in order.
FILELIST_NAMES = ('fc2_filelist.txt', 'fc2_filelist.txt.gz')


class FatError(Exception):
    """Malformed or unsupported .fat archive."""


@dataclass(frozen=True)
class FatEntry:
    name_hash: int
    offset: int          # absolute byte offset into the .dat
    stored_size: int     # bytes occupied in the .dat
    size: int            # real (uncompressed) size
    scheme: int          # 0 stored, 1 LZO1X

    @property
    def compressed(self) -> bool:
        return self.scheme != SCHEME_STORED


@dataclass
class FatIndex:
    fat_path: str
    dat_path: str
    version: int
    flags: int
    entries: List[FatEntry] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def total_size(self) -> int:
        return sum(e.size for e in self.entries)


def path_hash(rel_path: str) -> int:
    """Hash a relative path the way the FAT index keys it.

    Standard reflected CRC-32 (zlib's) of the LOWERCASED path using backslash
    separators. Confirmed on 2,000 real paths at 100%.
    """
    norm = rel_path.replace('/', '\\').lstrip('\\').lower()
    return zlib.crc32(norm.encode('ascii', 'ignore')) & 0xFFFFFFFF


def dat_path_for(fat_path: str) -> str:
    """``worlds.fat`` -> ``worlds.dat`` (the payload sits alongside the index)."""
    return os.path.splitext(fat_path)[0] + '.dat'


def is_fat_file(path: str) -> bool:
    """Cheap sniff so callers can reject a wrong pick before doing real work."""
    try:
        with open(path, 'rb') as fh:
            head = fh.read(8)
        if len(head) < 8 or head[:4] != FAT_MAGIC:
            return False
        return struct.unpack_from('<I', head, 4)[0] == FAT_VERSION
    except Exception:
        return False


def read_index(fat_path: str) -> FatIndex:
    """Parse a .fat. Raises FatError on anything that isn't a v5 index."""
    try:
        with open(fat_path, 'rb') as fh:
            blob = fh.read()
    except OSError as exc:
        raise FatError(f"cannot read {fat_path}: {exc}") from exc

    if len(blob) < HEADER_LEN or blob[:4] != FAT_MAGIC:
        raise FatError(f"{os.path.basename(fat_path)} is not a Dunia FAT archive")
    version, flags, count = struct.unpack_from('<III', blob, 4)
    if version != FAT_VERSION:
        raise FatError(
            f"unsupported FAT version {version} (only v5 / Far Cry 2 is known); "
            "later Dunia games pack their index differently")

    expected = HEADER_LEN + count * ENTRY_LEN
    if len(blob) < expected:
        raise FatError(
            f"index truncated: {len(blob)} bytes for {count:,} entries "
            f"(need at least {expected:,})")

    dat = dat_path_for(fat_path)
    if not os.path.isfile(dat):
        raise FatError(f"payload missing: expected {os.path.basename(dat)} "
                       f"beside {os.path.basename(fat_path)}")

    entries: List[FatEntry] = []
    for i in range(count):
        h, size_field, pack, off_hi = struct.unpack_from(
            '<IIII', blob, HEADER_LEN + i * ENTRY_LEN)
        stored = pack & 0x3FFFFFFF
        # The top 2 bits of `pack` are the offset's low bits, NOT a scheme.
        offset = off_hi * 4 + (pack >> 30)
        if size_field:
            real, scheme = size_field >> 2, size_field & 3
        else:
            real, scheme = stored, SCHEME_STORED
        entries.append(FatEntry(h, offset, stored, real, scheme))
    return FatIndex(fat_path, dat, version, flags, entries)


def read_entry(fh, entry: FatEntry) -> bytes:
    """Pull one file out of an open .dat handle."""
    fh.seek(entry.offset)
    blob = fh.read(entry.stored_size)
    if len(blob) != entry.stored_size:
        raise FatError(f"short read at {entry.offset} for hash "
                       f"{entry.name_hash:08X}")
    if entry.scheme == SCHEME_STORED:
        return blob
    if entry.scheme == SCHEME_LZO1X:
        out = lzo_decompress(blob, entry.size)
        if len(out) != entry.size:
            raise FatError(f"LZO output {len(out)} != declared {entry.size} "
                           f"for hash {entry.name_hash:08X}")
        return out
    raise FatError(f"unknown compression scheme {entry.scheme} for hash "
                   f"{entry.name_hash:08X}")


def read_file(fat_path: str, entry: FatEntry) -> bytes:
    """Random-access read of a single entry (the index is not re-parsed)."""
    with open(dat_path_for(fat_path), 'rb') as fh:
        return read_entry(fh, entry)


# ── name resolution ───────────────────────────────────────────────────────

def build_name_map(paths: Iterable[str]) -> Dict[int, str]:
    """Hash an iterable of relative paths into a {hash: path} lookup."""
    out: Dict[int, str] = {}
    for p in paths:
        p = p.strip().replace('/', '\\').lstrip('\\')
        if p:
            out[path_hash(p)] = p
    return out


def load_filelist(path: str) -> Dict[int, str]:
    """Load a newline-separated path dictionary (optionally gzipped)."""
    if path.endswith('.gz'):
        import gzip
        with gzip.open(path, 'rt', encoding='utf-8', errors='ignore') as fh:
            return build_name_map(fh)
    with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
        return build_name_map(fh)


def find_bundled_filelist() -> Optional[str]:
    """Locate a shipped path dictionary next to the app / in assets."""
    here = os.path.dirname(os.path.abspath(__file__))
    roots = (here, os.path.join(here, 'assets'), os.path.join(here, 'tools'))
    for root in roots:
        for name in FILELIST_NAMES:
            cand = os.path.join(root, name)
            if os.path.isfile(cand):
                return cand
    return None


def default_name_map() -> Dict[int, str]:
    """The bundled dictionary, or empty when none ships."""
    fl = find_bundled_filelist()
    if not fl:
        return {}
    try:
        return load_filelist(fl)
    except Exception as exc:
        print(f"  [fat] could not read filelist {fl}: {exc}")
        return {}


def default_extract_dir(fat_path: str) -> str:
    """``…\\worlds.fat`` -> ``…\\worlds`` (mirrors pak_archive's convention)."""
    return os.path.splitext(fat_path)[0]


@dataclass
class FatExtractResult:
    folder: str
    total: int = 0
    written: int = 0
    unknown: int = 0
    failed: int = 0
    bytes_written: int = 0

    @property
    def resolved_pct(self) -> float:
        return 100.0 * (self.total - self.unknown) / self.total if self.total else 0.0


def extract(fat_path: str,
            out_dir: Optional[str] = None,
            names: Optional[Dict[int, str]] = None,
            progress: Optional[Callable[[int, int], bool]] = None,
            log: Optional[Callable[[str], None]] = None) -> FatExtractResult:
    """Unpack a .fat/.dat pair into ``out_dir``.

    ``names`` maps hash -> relative path; entries with no name land in
    ``__Unknown/<hash>.bin``. ``progress(done, total)`` may return False to
    abort. Returns a :class:`FatExtractResult`.
    """
    def _log(msg):
        if log:
            log(msg)
        else:
            print(msg)

    load_lzo_dlls()          # best-effort; the pure-Python decoder still works
    index = read_index(fat_path)
    out_dir = out_dir or default_extract_dir(fat_path)
    names = names if names is not None else default_name_map()
    os.makedirs(out_dir, exist_ok=True)

    res = FatExtractResult(folder=out_dir, total=len(index))
    _log(f"[fat] {os.path.basename(fat_path)}: {res.total:,} entries, "
         f"{len(names):,} known paths")

    with open(index.dat_path, 'rb') as fh:
        for i, entry in enumerate(index.entries):
            rel = names.get(entry.name_hash)
            if rel is None:
                rel = os.path.join(UNKNOWN_DIR, f"{entry.name_hash:08X}.bin")
                res.unknown += 1
            dest = os.path.join(out_dir, rel)
            try:
                data = read_entry(fh, entry)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, 'wb') as out:
                    out.write(data)
                res.written += 1
                res.bytes_written += len(data)
            except Exception as exc:
                res.failed += 1
                if res.failed <= 10:
                    _log(f"  [fat] FAILED {rel}: {exc}")
            if progress and (i % 256 == 0 or i + 1 == res.total):
                if progress(i + 1, res.total) is False:
                    _log("[fat] cancelled")
                    return res

    _log(f"[fat] wrote {res.written:,} files ({res.bytes_written / 1e6:.1f} MB); "
         f"{res.unknown:,} unnamed -> {UNKNOWN_DIR}/ "
         f"({res.resolved_pct:.1f}% resolved); {res.failed} failed")
    return res
