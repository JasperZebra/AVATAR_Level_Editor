"""Build the superset name cache for fcb_convert.py.

names32: uint32 CRC32 -> str   (object class names, field names)
names64: uint64 CRC64 -> str   (file/resource paths)

Sources, first-wins priority:
  1. FCBConverterStrings.list           -> names32 (CRC32 of each line)
  2. user dunia_crc_ids.xml (streamed)  -> names32, only-if-absent, printable filter
  3. FCBConverterFileNames.list         -> names64 (CRC64 of each line)

Writes tools/fcb_names_cache.pkl = {'32': {...}, '64': {...}, 'mtimes': {...}}
"""
import os
import re
import sys
import pickle
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "FCBConverter-master", "bin", "net7.0-windows", "win-x64")
# the .list files actually live next to FCBConverter.exe (tools root)
STRINGS = os.path.join(HERE, "FCBConverterStrings.list")
FILENAMES = os.path.join(HERE, "FCBConverterFileNames.list")
USERDICT = r"C:/Users/sambe/Desktop/____AVATAR_STUFF/____DAT_CONVERTER/ogs/dunia_crc_ids.xml"
CACHE = os.path.join(HERE, "fcb_names_cache.pkl")

# CRC64 table copied verbatim from Gibbed.Dunia2.FileFormats/CRC64.cs
import importlib.util
def _load_crc64_table():
    src = os.path.join(HERE, "FCBConverter-master", "FCBConverter",
                       "Gibbed.Dunia2.FileFormats", "CRC64.cs")
    txt = open(src, "r", encoding="utf-8", errors="replace").read()
    consts = re.findall(r"0x([0-9A-Fa-f]{16})ul", txt)
    assert len(consts) == 256, len(consts)
    return [int(c, 16) for c in consts]

CRC64_TABLE = _load_crc64_table()
MASK64 = (1 << 64) - 1


def crc32(s):
    # C# hashes (byte)char low bytes; zlib over latin-1-low-byte bytes
    b = bytes((ord(c) & 0xFF) for c in s)
    return zlib.crc32(b) & 0xFFFFFFFF


def crc64(s):
    h = 0
    for c in s:
        h = (CRC64_TABLE[(h ^ (ord(c) & 0xFF)) & 0xFF] ^ (h >> 8)) & MASK64
    return h


_PRINTABLE = re.compile(r"^[\x20-\x7E]+$")


def build():
    names32 = {}
    names64 = {}

    print("loading FCBConverterStrings.list ...")
    with open(STRINGS, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.rstrip("\r\n")
            if not s:
                continue
            h = crc32(s)
            if h not in names32:
                names32[h] = s
    print("  names32 from strings:", len(names32))

    if os.path.exists(USERDICT):
        print("streaming user dict (regex line scan) ...")
        # The dict contains many binary 'string' values that break XML parsing,
        # so scan line by line with a tolerant regex. Each row is one <entry .../>.
        rx = re.compile(r'string="((?:[^"\\]|\\.)*)"[^>]*?hex="([0-9A-Fa-f]{1,8})"')
        added = 0
        with open(USERDICT, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = rx.search(line)
                if not m:
                    continue
                s, hx = m.group(1), m.group(2)
                # unescape standard XML entities
                if "&" in s:
                    s = (s.replace("&lt;", "<").replace("&gt;", ">")
                          .replace("&quot;", '"').replace("&apos;", "'")
                          .replace("&amp;", "&"))
                if not _PRINTABLE.match(s):
                    continue
                k = int(hx, 16)
                # verify the hex really is CRC32(string); drop mismatches
                if crc32(s) != k:
                    continue
                if k not in names32:
                    names32[k] = s
                    added += 1
        print("  names32 added from user dict:", added)
    else:
        print("USER DICT NOT FOUND, skipping:", USERDICT)

    print("loading FCBConverterFileNames.list (CRC64) ...")
    if os.path.exists(FILENAMES):
        with open(FILENAMES, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.rstrip("\r\n")
                if not s:
                    continue
                h = crc64(s)
                if h not in names64:
                    names64[h] = s
        print("  names64:", len(names64))
    else:
        print("FILENAMES NOT FOUND:", FILENAMES)

    mtimes = {}
    for p in (STRINGS, FILENAMES, USERDICT):
        if os.path.exists(p):
            mtimes[p] = os.path.getmtime(p)

    with open(CACHE, "wb") as f:
        pickle.dump({"32": names32, "64": names64, "mtimes": mtimes}, f,
                    protocol=pickle.HIGHEST_PROTOCOL)
    print("wrote", CACHE, "names32=%d names64=%d" % (len(names32), len(names64)))


if __name__ == "__main__":
    build()
