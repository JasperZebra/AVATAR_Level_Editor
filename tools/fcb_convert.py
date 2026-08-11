"""Native Python bidirectional FCB (Dunia-2 "nbCF") <-> XML converter.

Ported from FCBConverter (GPLv3, Jakub Marecek) + Gibbed.Dunia2 tools, then
improved with a superset name table. NO shelling out to FCBConverter.

Public API:
    fcb_to_xml(data, names, defs) -> xml_text
    xml_to_fcb(xml_text)          -> bytes

`names` is a NameTable (load_names()); `defs` is a Definitions (load_defs()).
Both may be None, in which case they are lazily loaded from the cache/def file.

Byte-exact guarantee: xml_to_fcb(fcb_to_xml(orig)) == orig for every Avatar FCB,
because (a) the XML stores raw field bytes as authoritative BinHex, (b) field and
child order are preserved, (c) dedup is re-derived with the identical FCBConverter
algorithm, and (d) original header objCount/valCount are stored as root attributes
(__objcount/__valcount) and replayed verbatim so the 16-byte header is exact even
when the game's dedup differs from FCBConverter's.
"""
import os
import re
import sys
import struct
import pickle
import zlib

sys.setrecursionlimit(1_000_000)

HERE = os.path.dirname(os.path.abspath(__file__))
MAGIC = b"nbCF"
CACHE = os.path.join(HERE, "fcb_names_cache.pkl")
CACHE_N32 = os.path.join(HERE, "fcb_names_cache.n32.pkl")
CACHE_N64 = os.path.join(HERE, "fcb_names_cache.n64.pkl")
# Prefer the standalone copy in tools/ (so the FCBConverter-master source can be
# removed); fall back to the source tree if the standalone copy is absent.
DEFS_XML = os.path.join(HERE, "FCBConverterDefinitions.xml")
if not os.path.exists(DEFS_XML):
    DEFS_XML = os.path.join(HERE, "FCBConverter-master", "bin", "net7.0-windows",
                            "win-x64", "FCBConverterDefinitions.xml")

GUESS_PREFIX = "value-"

# ---------------------------------------------------------------------------
# CRC
# ---------------------------------------------------------------------------
MASK64 = (1 << 64) - 1


from functools import lru_cache


@lru_cache(maxsize=None)
def crc32(s):
    # FCBConverter masks each char to a byte (ord & 0xFF). Almost all names are
    # latin-1 (<=0xFF), where encode("latin-1") is the identical, C-speed result;
    # only fall back to the explicit mask for the rare char > 0xFF.
    # lru_cache: the same field/object names recur millions of times per file.
    try:
        b = s.encode("latin-1")
    except UnicodeEncodeError:
        b = bytes((ord(c) & 0xFF) for c in s)
    return zlib.crc32(b) & 0xFFFFFFFF


def _load_crc64_table():
    # Self-contained: the 256-entry table is embedded in crc64_table.py (extracted
    # from Gibbed.Dunia2 CRC64.cs), so the FCBConverter-master source is not required.
    try:
        from crc64_table import CRC64_TABLE
        if len(CRC64_TABLE) == 256:
            return list(CRC64_TABLE)
    except Exception:
        pass
    # Legacy fallback: read the C# source if it is still present.
    src = os.path.join(HERE, "FCBConverter-master", "FCBConverter",
                       "Gibbed.Dunia2.FileFormats", "CRC64.cs")
    if os.path.exists(src):
        txt = open(src, "r", encoding="utf-8", errors="replace").read()
        consts = re.findall(r"0x([0-9A-Fa-f]{16})ul", txt)
        if len(consts) == 256:
            return [int(c, 16) for c in consts]
    return None


_CRC64_TABLE = _load_crc64_table()


def crc64(s):
    if _CRC64_TABLE is None:
        return 0
    h = 0
    for c in s:
        h = (_CRC64_TABLE[(h ^ (ord(c) & 0xFF)) & 0xFF] ^ (h >> 8)) & MASK64
    return h


# ---------------------------------------------------------------------------
# Name table
# ---------------------------------------------------------------------------
class NameTable:
    def __init__(self, n32, n64=None, n64_path=None):
        self.n32 = n32
        self._n64 = n64
        self._n64_path = n64_path     # lazy-load source for the (unused-by-convert) n64

    @property
    def n64(self):
        # The CRC64 resource-path table (~4.2M sound-file entries, ~290 MB) is NOT
        # touched by fcb_to_xml/xml_to_fcb — only .file() consumers need it — so it
        # is loaded lazily on first access, halving the name-table load for conversion.
        if self._n64 is None:
            if self._n64_path and os.path.exists(self._n64_path):
                with open(self._n64_path, "rb") as f:
                    self._n64 = pickle.load(f)
            else:
                self._n64 = {}
        return self._n64

    def name(self, h):           # object/field names + hash-list ids (CRC32)
        return self.n32.get(h)

    def file(self, h):           # resource paths (CRC64)
        return self.n64.get(h)


_NAMES = None


def load_names(cache=CACHE):
    global _NAMES
    if _NAMES is not None:
        return _NAMES
    # Prefer the split caches: load the CRC32 name table eagerly (the only table
    # conversion uses) and defer the large CRC64 resource table to first .file()
    # access. Falls back to the combined pickle if the split files are absent.
    if os.path.exists(CACHE_N32):
        with open(CACHE_N32, "rb") as f:
            n32 = pickle.load(f)
        _NAMES = NameTable(n32, n64=None, n64_path=CACHE_N64)
    elif os.path.exists(cache):
        with open(cache, "rb") as f:
            d = pickle.load(f)
        _NAMES = NameTable(d["32"], n64=d["64"])
    else:
        _NAMES = NameTable({}, n64={})
    # FCBConverter's loader hashes blank lines too, so CRC32("")==0 maps to the
    # empty string. Our cache builder skipped blanks; restore that mapping so
    # FindInDictionarySkip on a zero uint matches the oracle (value-* = "").
    if 0 not in _NAMES.n32:
        _NAMES.n32[0] = ""
    return _NAMES


# ---------------------------------------------------------------------------
# C# float/double .ToString(InvariantCulture) shortest round-trip.
#
# Exactly reproduces .NET Core's default Single/Double.ToString(InvariantCulture):
#   1. shortest decimal digit string that round-trips to the same binary value;
#   2. positional vs. scientific decision by the power-of-ten of the leading digit
#      (exp): positional iff -4 <= exp <= 8 for Single, -4 <= exp <= 16 for Double;
#   3. scientific mantissa "d.ddd" with "E+NN"/"E-NN" (>=2 exponent digits).
# Validated against 20k random + structured C# values per type (0 mismatches).
# ---------------------------------------------------------------------------
def _shortest_digits(x, pack, unpack, maxprec):
    """Return (sign, digits, exp) for the shortest round-tripping decimal.
    digits has no decimal point and no leading/trailing zeros (except "0");
    exp is the base-10 power of the leading digit (value ~= d.dddd * 10**exp)."""
    if x == 0.0:
        # preserve -0.0 sign bit (matches .NET which prints "-0")
        sign = "-" if (pack(x)[-1] & 0x80) else ""
        return sign, "0", 0
    neg = x < 0
    a = abs(x)
    s = "%.*e" % (maxprec - 1, a)
    for prec in range(1, maxprec + 1):
        s = "%.*e" % (prec - 1, a)
        try:
            if unpack(pack(float(s)))[0] == a:
                break
        except (OverflowError, ValueError):
            continue
    mant, exp = s.split("e")
    digits = (mant.replace(".", "").rstrip("0")) or "0"
    return ("-" if neg else ""), digits, int(exp)


def _format_net(x, sci_lo, sci_hi, pack, unpack, maxprec):
    if x != x:
        return "NaN"
    if x == float("inf"):
        return "Infinity"
    if x == float("-inf"):
        return "-Infinity"
    sign, digits, exp = _shortest_digits(x, pack, unpack, maxprec)
    if exp < sci_lo or exp > sci_hi:
        mant = digits if len(digits) == 1 else digits[0] + "." + digits[1:]
        es = "+" if exp >= 0 else "-"
        return sign + mant + "E" + es + "%02d" % abs(exp)
    if exp >= 0:
        if len(digits) <= exp + 1:
            return sign + digits + "0" * (exp + 1 - len(digits))
        return sign + digits[:exp + 1] + "." + digits[exp + 1:]
    return sign + "0." + "0" * (-exp - 1) + digits


_pack_f = struct.Struct("<f").pack
_unpack_f = struct.Struct("<f").unpack
_pack_d = struct.Struct("<d").pack
_unpack_d = struct.Struct("<d").unpack


@lru_cache(maxsize=1 << 17)
def _cs_float_b(b):
    # keyed on the 4 raw float bytes so -0.0 and 0.0 (which compare ==) stay
    # distinct, and NaN bit-patterns don't collide on a non-self-equal key.
    f32 = _unpack_f(b)[0]
    return _format_net(f32, -4, 8, _pack_f, _unpack_f, 9)


@lru_cache(maxsize=1 << 17)
def _cs_double_b(b):
    return _format_net(_unpack_d(b)[0], -4, 16, _pack_d, _unpack_d, 17)


def cs_float(x):
    return _cs_float_b(_pack_f(x))


def cs_double(x):
    return _cs_double_b(_pack_d(x))


# ---------------------------------------------------------------------------
# Definitions loader (port of DefinitionsLoader.cs)
# ---------------------------------------------------------------------------
import xml.etree.ElementTree as ET


class DefField:
    __slots__ = ("Hash", "Name", "Type", "ForceType", "Action", "Comment",
                 "ArrayItemType", "ArrayItemName")


class DefObject:
    __slots__ = ("Hash", "Name", "Action", "FieldForName", "Fields", "Objects",
                 "PrimaryKeys")


class DefPrimaryKey:
    __slots__ = ("Hash", "ValueBinHex", "ValueR")


class DefList:
    __slots__ = ("Type", "ForceType", "Action", "Array")


class DefCondition:
    __slots__ = ("Action", "Value", "Type")


class DefConditionArray:
    __slots__ = ("Type", "Conditions", "Arrays")


class DefGlobal:
    __slots__ = ("Fields", "Lists")


class DefFile:
    __slots__ = ("Name", "Objects", "Global")


def _attr(e, k, default=""):
    v = e.get(k)
    return v if v is not None else default


def _parse_fields(parent):
    out = []
    for xf in parent.findall("field"):
        df = DefField()
        df.Hash = _attr(xf, "hash")
        df.Name = _attr(xf, "name")
        df.Type = _attr(xf, "type")          # keep as string name
        df.ForceType = _attr(xf, "forceType")
        df.Action = _attr(xf, "action")
        df.Comment = xf.get("comment")
        df.ArrayItemType = xf.get("ArrayItemType")
        df.ArrayItemName = xf.get("ArrayItemName")
        out.append(df)
    return out


def _parse_objects(parent):
    out = []
    for xo in parent.findall("object"):
        do = DefObject()
        do.Name = _attr(xo, "name")
        do.Hash = _attr(xo, "hash")
        do.Action = xo.get("action")
        do.FieldForName = xo.get("FieldForName")
        do.Fields = _parse_fields(xo)
        do.Objects = _parse_objects(xo)
        do.PrimaryKeys = []
        for xp in xo.findall("primaryKey"):
            pk = DefPrimaryKey()
            pk.Hash = 0
            h = _attr(xp, "hash")
            if h != "":
                pk.Hash = int(h, 16)
            n = _attr(xp, "name")
            if n != "":
                pk.Hash = crc32(n)
            pk.ValueBinHex = bytes.fromhex(_attr(xp, "valueBinHex"))
            pk.ValueR = _attr(xp, "valueR")
            do.PrimaryKeys.append(pk)
        out.append(do)
    return out


def _parse_cond_array(parent):
    a = DefConditionArray()
    a.Type = _attr(parent, "type")
    a.Conditions = []
    a.Arrays = []
    for xc in parent.findall("Condition"):
        c = DefCondition()
        c.Action = _attr(xc, "action")
        c.Value = _attr(xc, "value")
        c.Type = xc.get("type") or ""
        a.Conditions.append(c)
    for xa in parent.findall("ConditionArray"):
        a.Arrays.append(_parse_cond_array(xa))
    return a


_MISS = object()   # cache sentinel: key absent (vs. a cached None result)


class Definitions:
    def __init__(self, path, target_file=""):
        self.Files = []
        tree = ET.parse(path)
        root = tree.getroot()
        for xFile in root.findall("File"):
            df = DefFile()
            df.Name = _attr(xFile, "name")
            df.Objects = _parse_objects(xFile)
            df.Global = None
            xg = xFile.find("Globals")
            if xg is not None:
                g = DefGlobal()
                g.Lists = []
                g.Fields = _parse_fields(xg)
                for xcl in xg.findall("ConditionList"):
                    dl = DefList()
                    dl.Type = _attr(xcl, "type")
                    dl.ForceType = _attr(xcl, "forceType")
                    dl.Action = xcl.get("action")
                    dl.Array = _parse_cond_array(xcl.find("ConditionArray"))
                    g.Lists.append(dl)
                df.Global = g
            self.Files.append(df)
        self.set_target(target_file)

    @staticmethod
    def _file_matches(pattern, target):
        if pattern == "":
            return True
        # .NET def patterns are of the form  $(?<=(GROUP))  meaning "ends with GROUP"
        # (GROUP is itself a small regex alternation). Python rejects variable-width
        # lookbehind, so translate to: does target match  .*(GROUP)$ ?
        m = re.fullmatch(r"\$\(\?<=\((.*)\)\)", pattern)
        if m:
            grp = m.group(1)
            try:
                return re.search("(?:" + grp + r")$", target) is not None
            except re.error:
                return False
        try:
            return re.search(pattern, target) is not None
        except re.error:
            return False

    def set_target(self, target_file):
        self.Objects = []
        self.Globals = []
        for df in self.Files:
            if self._file_matches(df.Name, target_file):
                self.Objects.extend(df.Objects)
                self.Globals.append(df.Global)
        # Memoization caches (invalidated whenever the active def set changes):
        #  _field_cache: (id(def_object), field_hash, field_name) -> result dict
        #                for a FIELD-schema hit, or None ("no field hit; check lists").
        #                Value-independent — the schema for a class/field is fixed.
        #  _list_cache:  (field_name, binary_hex, strv) -> result dict for a Globals
        #                ConditionList hit, or None. Only consulted on a field miss.
        #  _objmatch_cache: (id(pool0), object_name, object_hash) -> DefObject (no-PK
        #                match) for process_object's value-independent first pass.
        self._field_cache = {}
        self._list_cache = {}
        self._objmatch_cache = {}
        self._ctx_cache = {}

    # ---- string helpers (Helpers.cs) ----
    @staticmethod
    def starts_with_type(name, pfx):
        if name.startswith(pfx) and len(name) > len(pfx):
            return name[len(pfx)].isupper()
        return False

    @staticmethod
    def get_last(s, n):
        return s if n >= len(s) else s[len(s) - n:]

    @staticmethod
    def contains_ci(name, sub):
        return sub.lower() in name.lower()

    def _eval_cond(self, cond, binary_hex, name, strv):
        a = cond.Action
        t = False
        if a == "ByteLen":
            v = cond.Value
            if v.startswith(">"):
                t = len(binary_hex) > int(v[1:])
            elif v.startswith("<"):
                t = len(binary_hex) < int(v[1:])
            else:
                t = len(binary_hex) == int(v)
        elif a == "ByteLast":
            t = self.get_last(binary_hex, len(cond.Value)) == cond.Value
        elif a == "StartsWithType":
            t = self.starts_with_type(name, cond.Value)
        elif a == "StartsWith":
            t = name.startswith(cond.Value)
        elif a == "EndsWith":
            t = name.endswith(cond.Value)
        elif a == "ExactName":
            t = name == cond.Value
        elif a == "ExactValue":
            t = binary_hex == cond.Value
        elif a == "ContainsCI":
            t = self.contains_ci(name, cond.Value)
        elif a == "Contains":
            t = cond.Value in name
        elif a == "Regex":
            t = re.search(cond.Value, strv) is not None
        elif a == "RegexBinaryHex":
            t = re.search(cond.Value, binary_hex) is not None
        if cond.Type == "not":
            t = not t
        return t

    def _eval_array(self, arr, binary_hex, name, strv):
        use_and = arr.Type == "and"
        temp = use_and
        for cond in arr.Conditions:
            t = self._eval_cond(cond, binary_hex, name, strv)
            if use_and:
                temp = temp and t
                if not temp:
                    return temp
            else:
                temp = temp or t
        for sub in arr.Arrays:
            t = self._eval_array(sub, binary_hex, name, strv)
            if use_and:
                temp = temp and t
                if not temp:
                    return temp
            else:
                temp = temp or t
        return temp

    # Shared immutable default (all-BinHex). Callers in this module only READ the
    # returned dict, so handing back a shared instance is safe and avoids allocating
    # ~one dict per field on the hot path.
    _DEFAULT_RES = {"Type": "BinHex", "Action": None, "Comment": None,
                    "ArrayItemType": None, "ArrayItemName": None}

    def _field_schema(self, pnt_def_object, object_name, field_hash,
                      field_name, object_hash):
        """Value-independent FIELD-schema lookup (object Fields / Globals Fields).
        Returns a result dict for a hit, or None for "no field hit; check lists".
        Memoized on (id(def_object), object_name, object_hash, field_hash,
        field_name)."""
        ck = (id(pnt_def_object), object_name, object_hash, field_hash, field_name)
        cache = self._field_cache
        hit = cache.get(ck, _MISS)
        if hit is not _MISS:           # cached (could be a dict or None)
            return hit

        res = None
        if pnt_def_object is not None:
            o = pnt_def_object
            if (o.Name != "" and o.Name == object_name) or \
               (o.Hash != "" and o.Hash == object_hash):
                for f in o.Fields:
                    if (field_hash != "" and f.Hash == field_hash) or \
                       (field_name != "" and f.Name == field_name):
                        res = {"Type": f.Type, "Action": f.Action,
                               "Comment": f.Comment,
                               "ArrayItemType": f.ArrayItemType,
                               "ArrayItemName": f.ArrayItemName}
                        break
        else:
            for o in self.Objects:
                # PrimaryKeys is always [] (never None) -> the C# "== null" guard
                # is always false, so top-level objects never match here.
                if (((o.Name != "" and o.Name == object_name) or
                     (o.Hash != "" and o.Hash == object_hash)) and
                        o.PrimaryKeys is None):
                    for f in o.Fields:
                        if (field_hash != "" and f.Hash == field_hash) or \
                           (field_name != "" and f.Name == field_name):
                            res = {"Type": f.Type, "Action": f.Action,
                                   "Comment": f.Comment,
                                   "ArrayItemType": f.ArrayItemType,
                                   "ArrayItemName": f.ArrayItemName}
                            break
                    if res is not None:
                        break

        if res is None:
            # Globals Fields are also value-independent.
            for g in self.Globals:
                if g is None:
                    continue
                for f in g.Fields:
                    if (field_hash != "" and f.Hash == field_hash) or \
                       (field_name != "" and f.Name == field_name):
                        res = {"Type": f.Type, "Action": f.Action,
                               "Comment": f.Comment,
                               "ArrayItemType": f.ArrayItemType,
                               "ArrayItemName": f.ArrayItemName}
                        break
                if res is not None:
                    break

        cache[ck] = res
        return res

    def field_ctx(self, pnt_def_object, object_name, object_hash):
        """Return a context handle for a node so per-field schema lookups need only
        a small (field_hash, field_name) key instead of rebuilding the full
        (id(def_object), names, hashes, field...) tuple 1.3M times. The handle is a
        dict the caller keys with (fhex, fname); a _MISS-or-result is memoized into
        it. Memoized per (id(def_object), object_name, object_hash)."""
        ck = (id(pnt_def_object), object_name, object_hash)
        ctx = self._ctx_cache.get(ck)
        if ctx is None:
            # Resolve the matching object's Fields list once. Mirrors _field_schema's
            # object-match logic so the per-field scan below is identical.
            obj_fields = None
            if pnt_def_object is not None:
                o = pnt_def_object
                if (o.Name != "" and o.Name == object_name) or \
                   (o.Hash != "" and o.Hash == object_hash):
                    obj_fields = o.Fields
            else:
                for o in self.Objects:
                    if (((o.Name != "" and o.Name == object_name) or
                         (o.Hash != "" and o.Hash == object_hash)) and
                            o.PrimaryKeys is None):
                        obj_fields = o.Fields
                        break
            ctx = {"_of": obj_fields, "_memo": {}}
            self._ctx_cache[ck] = ctx
        return ctx

    def _ctx_field(self, ctx, field_hash, field_name):
        """Field-schema hit for a precomputed context, or None. Replicates the
        first-match-wins scan of _field_schema (object Fields then Globals Fields).
        Keyed on field_hash alone: field_name is a deterministic function of the
        hash (name-table lookup), so within a context it never varies for a hash."""
        memo = ctx["_memo"]
        hit = memo.get(field_hash, _MISS)
        if hit is not _MISS:
            return hit
        res = None
        of = ctx["_of"]
        if of is not None:
            for f in of:
                if (field_hash != "" and f.Hash == field_hash) or \
                   (field_name != "" and f.Name == field_name):
                    res = {"Type": f.Type, "Action": f.Action,
                           "Comment": f.Comment,
                           "ArrayItemType": f.ArrayItemType,
                           "ArrayItemName": f.ArrayItemName}
                    break
        if res is None:
            for g in self.Globals:
                if g is None:
                    continue
                for f in g.Fields:
                    if (field_hash != "" and f.Hash == field_hash) or \
                       (field_name != "" and f.Name == field_name):
                        res = {"Type": f.Type, "Action": f.Action,
                               "Comment": f.Comment,
                               "ArrayItemType": f.ArrayItemType,
                               "ArrayItemName": f.ArrayItemName}
                        break
                if res is not None:
                    break
        memo[field_hash] = res
        return res

    def process_ctx(self, ctx, field_hash, binary_hex, field_name, strv,
                    use_lists):
        """process() using a precomputed field context (see field_ctx). Inlines the
        per-field schema memo lookup (the hot path) to save a call layer."""
        memo = ctx["_memo"]
        res = memo.get(field_hash, _MISS)
        if res is _MISS:
            res = self._ctx_field(ctx, field_hash, field_name)
        if res is not None:
            return res
        if use_lists:
            lk = (field_name, binary_hex, strv)
            lcache = self._list_cache
            lres = lcache.get(lk, _MISS)
            if lres is not _MISS:
                return lres if lres is not None else self._DEFAULT_RES
            for g in self.Globals:
                if g is None:
                    continue
                for dl in g.Lists:
                    if self._eval_array(dl.Array, binary_hex, field_name, strv):
                        lres = {"Type": dl.Type, "Action": dl.Action,
                                "Comment": None, "ArrayItemType": None,
                                "ArrayItemName": None}
                        lcache[lk] = lres
                        return lres
            lcache[lk] = None
        return self._DEFAULT_RES

    def process(self, pnt_def_object, object_name, field_hash, binary_hex,
                field_name, object_hash, strv, use_lists):
        """Returns dict(Type, Action, Comment, ArrayItemType, ArrayItemName)."""
        res = self._field_schema(pnt_def_object, object_name, field_hash,
                                 field_name, object_hash)
        if res is not None:
            return res

        if use_lists:
            # ConditionLists depend only on (field_name, binary_hex, strv); cache
            # the (often-repeated) value-dependent result.
            lk = (field_name, binary_hex, strv)
            lcache = self._list_cache
            lres = lcache.get(lk, _MISS)
            if lres is not _MISS:
                return lres if lres is not None else self._DEFAULT_RES
            for g in self.Globals:
                if g is None:
                    continue
                for dl in g.Lists:
                    if self._eval_array(dl.Array, binary_hex, field_name, strv):
                        lres = {"Type": dl.Type, "Action": dl.Action,
                                "Comment": None, "ArrayItemType": None,
                                "ArrayItemName": None}
                        lcache[lk] = lres
                        return lres
            lcache[lk] = None
        return self._DEFAULT_RES

    def process_object(self, pnt_def_object, object_name, object_hash, fields):
        """fields: list of (hash, bytes). Returns dict(Action, CurrentObject, FieldForName)."""
        pool = pnt_def_object.Objects if pnt_def_object is not None else self.Objects
        # Cache the (value-independent) candidate match list keyed by pool+name+hash.
        # Objects WITH PrimaryKeys still need the value-dependent fields check, but
        # the candidate scan (the expensive part) is memoized.
        ck = (id(pool), object_name, object_hash)
        cands = self._objmatch_cache.get(ck, _MISS)
        if cands is _MISS:
            cands = [o for o in pool
                     if (o.Name != "" and o.Name == object_name) or
                        (o.Hash != "" and o.Hash == object_hash)]
            self._objmatch_cache[ck] = cands
        for o in cands:
            if fields is not None and o.PrimaryKeys:
                pk_ok = False
                for pk in o.PrimaryKeys:
                    for fld in fields:
                        if fld[0] == pk.Hash and fld[1] == pk.ValueBinHex:
                            pk_ok = True
                if not pk_ok:
                    continue
            return {"Action": o.Action, "CurrentObject": o,
                    "FieldForName": o.FieldForName}
        return {"Action": None, "CurrentObject": None, "FieldForName": None}


_DEFS_CACHE = {}
_ARR_NAME_MAP = None


def _array_name_map():
    """ArrayItemName -> ArrayItemType for every Array-action field in the defs.
    Used by xml_to_fcb to re-serialize <ArrayItemName> child elements without
    needing object-class context. Each ArrayItemName is unique to one type."""
    global _ARR_NAME_MAP
    if _ARR_NAME_MAP is not None:
        return _ARR_NAME_MAP
    m = {}
    try:
        for _ev, el in ET.iterparse(DEFS_XML):
            if el.tag == "field" and el.get("action") == "Array":
                nm = el.get("ArrayItemName")
                ty = el.get("ArrayItemType")
                if nm and ty:
                    m.setdefault(nm, ty)
            el.clear()
    except Exception:
        pass
    _ARR_NAME_MAP = m
    return m


def load_defs(target_file=""):
    key = target_file
    if "_base" not in _DEFS_CACHE:
        _DEFS_CACHE["_base"] = Definitions(DEFS_XML, target_file)
        _DEFS_CACHE[key] = _DEFS_CACHE["_base"]
        return _DEFS_CACHE["_base"]
    d = _DEFS_CACHE["_base"]
    d.set_target(target_file)
    return d


# ---------------------------------------------------------------------------
# Decode (BinaryObject.Deserialize), fully-expanded tree
# ---------------------------------------------------------------------------
def _read_count(d, pos):
    b = d[pos]
    pos += 1
    if b < 0xFE:
        return b, False, pos
    v = struct.unpack_from("<I", d, pos)[0]
    return v, (b != 0xFF), pos + 4


class Node:
    __slots__ = ("hash", "fields", "children", "child_refs")

    def __init__(self, h=0):
        self.hash = h
        self.fields = []      # list of (fieldHash, bytes)
        self.children = []    # list of Node (fully expanded; back-refs share node)
        # child_refs[i] = ordinal (int) if child i was an object back-ref, else None
        self.child_refs = []


def parse_tree(data, record=False):
    """Decode an FCB.

    record=False: fast fully-expanded tree (object back-refs share the SAME Node
                  instance, exactly like FCBConverter). Used for XML emission.
    record=True:  additionally records, per child slot, the back-ref ordinal (or
                  None), and per field whether it was a value-back-ref plus the
                  original target byte offset. Used to guarantee byte-exact encode.

    Returns (root, end_pos, obj_count, val_count, had_backref).
    When record=True each field is (fieldHash, bytes, bref_target_or_None) and
    a parallel `value_offsets` map is attached to the returned tuple's globals
    via root only through child_refs/field tuples.
    """
    if len(data) < 16 or data[:4] != MAGIC:
        raise ValueError("not an FCB (bad magic)")
    version, flags = struct.unpack_from("<HH", data, 4)
    obj_count, val_count = struct.unpack_from("<II", data, 8)
    pointers = []
    pos = [16]
    had_backref = [False]

    def rc():
        v, off, np = _read_count(data, pos[0])
        pos[0] = np
        return v, off

    def read_obj():
        cc, isoff = rc()
        if isoff:
            had_backref[0] = True
            return pointers[cc], cc
        node = Node()
        pointers.append(node)
        node.hash = struct.unpack_from("<I", data, pos[0])[0]
        pos[0] += 4
        vc, isoff2 = rc()
        if isoff2:
            raise ValueError("valueCount back-ref unsupported")
        for _ in range(vc):
            fh = struct.unpack_from("<I", data, pos[0])[0]
            pos[0] += 4
            vpos = pos[0]
            size, soff = rc()
            if soff:
                had_backref[0] = True
                save = pos[0]
                rpos = vpos - size
                real, ro, rpos2 = _read_count(data, rpos)
                if ro:
                    raise ValueError("nested value back-ref")
                val = bytes(data[rpos2:rpos2 + real])
                pos[0] = save
                bref = size           # the ORIGINAL back-ref delta (verbatim)
            else:
                val = bytes(data[pos[0]:pos[0] + size])
                pos[0] += size
                bref = None
            if record:
                node.fields.append((fh, val, bref))
            else:
                node.fields.append((fh, val))
        for _ in range(cc):
            ch, ordn = read_obj()
            node.children.append(ch)
            if record:
                node.child_refs.append(ordn)
        return node, None

    root, _ = read_obj()
    return root, pos[0], obj_count, val_count, had_backref[0]


# ---------------------------------------------------------------------------
# Field-type value -> typed string (FieldTypeDeserializers)
# ---------------------------------------------------------------------------
_up_b = struct.Struct("<b").unpack_from
_up_H = struct.Struct("<H").unpack_from
_up_h = struct.Struct("<h").unpack_from
_up_I = struct.Struct("<I").unpack_from
_up_i = struct.Struct("<i").unpack_from
_up_Q = struct.Struct("<Q").unpack_from
_up_q = struct.Struct("<q").unpack_from


def _d_string(v, n):
    if n < 1:
        return None
    # first terminator (0x00 or 0x0A); the C# loop stops at either.
    z = v.find(0)
    nl = v.find(10)
    if z < 0:
        o = nl
    elif nl < 0:
        o = z
    else:
        o = z if z < nl else nl
    if o < 0:                       # no terminator at all -> o would reach n
        return None
    last = v[-1]
    if last != 0 and last != 10:
        return None
    return v[:o].decode("utf-8", errors="replace")


def _deser(ftype, v):
    """Return typed string for value bytes v under ftype, or None if impossible.

    Dispatch ordered/dict-routed by observed frequency (Float32 > String > Int32 >
    Hash32 > Boolean dominate entity files). Behaviour identical to the original
    if-chain port of FieldTypeDeserializers."""
    n = len(v)
    try:
        if ftype == "Float32":
            return _cs_float_b(bytes(v[0:4])) if n >= 4 else None
        if ftype == "String":
            return _d_string(v, n)
        if ftype in ("Int32", "Enum"):
            return str(_up_i(v)[0]) if n >= 4 else None
        if ftype in ("UInt32", "Hash32", "Id32"):
            return str(_up_I(v)[0]) if n >= 4 else None
        if ftype == "Boolean":
            if n < 1 or (v[0] != 0 and v[0] != 1):
                return None
            return "True" if v[0] else "False"
        if ftype == "Vector3":
            if n < 12:
                return None
            return (_cs_float_b(bytes(v[0:4])) + "," + _cs_float_b(bytes(v[4:8]))
                    + "," + _cs_float_b(bytes(v[8:12])))
        if ftype in ("UInt64", "Hash64", "Id64"):
            return str(_up_Q(v)[0]) if n >= 8 else None
        if ftype == "Float64":
            return _cs_double_b(bytes(v[0:8])) if n >= 8 else None
        if ftype == "Vector2":
            if n < 8:
                return None
            return _cs_float_b(bytes(v[0:4])) + "," + _cs_float_b(bytes(v[4:8]))
        if ftype == "Vector4":
            if n < 16:
                return None
            return (_cs_float_b(bytes(v[0:4])) + "," + _cs_float_b(bytes(v[4:8]))
                    + "," + _cs_float_b(bytes(v[8:12])) + ","
                    + _cs_float_b(bytes(v[12:16])))
        if ftype == "UInt8":
            return str(v[0]) if n >= 1 else None
        if ftype == "Int8":
            return str(_up_b(v)[0]) if n >= 1 else None
        if ftype == "UInt16":
            return str(_up_H(v)[0]) if n >= 2 else None
        if ftype == "Int16":
            return str(_up_h(v)[0]) if n >= 2 else None
        if ftype == "Int64":
            return str(_up_q(v)[0]) if n >= 8 else None
    except struct.error:
        return None
    return None


# ---------------------------------------------------------------------------
# Array action (FCBConverter): a length-prefixed packed array of fixed-size
# items (Vector2/3/4 or Int32). Exported as <ArrayItemName> child elements and
# re-imported by re-serializing each item. We ONLY adopt this representation
# when it reconstructs the field bytes EXACTLY (count*itemsize+4 == len, every
# float survives shortest-round-trip, ints exact), otherwise the caller keeps
# the field as authoritative BinHex so byte-exactness is never sacrificed.
# ---------------------------------------------------------------------------
_ARR_ITEM = {"Vector2": 8, "Vector3": 12, "Vector4": 16, "Int32": 4}
_ARR_FLOATS = {"Vector2": 2, "Vector3": 3, "Vector4": 4}


def _array_items(item_type, v):
    """Return list-of-item-text-strings iff v reconstructs byte-exact, else None.

    Mirrors FCBConverter Exporting.cs Array action: skip the leading u32 count,
    then decode tightly-packed items. Verifies the count field equals the item
    count and that the re-serialized bytes equal v exactly (byte-exact guard)."""
    isize = _ARR_ITEM.get(item_type)
    if isize is None or len(v) < 4:
        return None
    body = v[4:]
    if len(body) % isize != 0:
        return None
    count = len(body) // isize
    decl = struct.unpack_from("<I", v)[0]
    if decl != count:
        return None
    items = []
    rebuilt = bytearray(struct.pack("<I", count))
    if item_type == "Int32":
        for i in range(count):
            iv = struct.unpack_from("<i", body, i * 4)[0]
            items.append(str(iv))
            rebuilt += struct.pack("<i", iv)
    else:
        nf = _ARR_FLOATS[item_type]
        for i in range(count):
            comps = struct.unpack_from("<" + "f" * nf, body, i * isize)
            texts = [cs_float(c) for c in comps]
            items.append(",".join(texts))
            try:
                rebuilt += struct.pack("<" + "f" * nf, *(float(t) for t in texts))
            except (ValueError, OverflowError):
                return None
    if bytes(rebuilt) != v:
        return None
    return items


def _array_from_items(item_type, texts):
    """Re-serialize <ArrayItemName> texts back to length-prefixed bytes
    (FCBConverter Importing.cs Array action)."""
    isize = _ARR_ITEM[item_type]
    out = bytearray(struct.pack("<I", len(texts)))
    if item_type == "Int32":
        for t in texts:
            out += struct.pack("<i", int(t))
    else:
        nf = _ARR_FLOATS[item_type]
        for t in texts:
            parts = t.split(",")
            out += struct.pack("<" + "f" * nf, *(float(p) for p in parts[:nf]))
    return bytes(out)


# ---------------------------------------------------------------------------
# XMLRML (legacy/descriptor) action -- the structural expansion the editor needs.
#
# A legacy hidDescriptor / LocalProperties field value (value[0]==0) is a Gibbed
# XmlResourceFile (RML): a binary serialization of a small XML tree (the
# GraphicComponent / GraphicKitComponent descriptor). FCBConverter decodes it via
# XmlResourceFile.Deserialize + ConvertXml.Program.WriteNode into nested
# <component>/<object>/<resource>/<skeleton>/<slot>/<part> elements wrapped in a
# <field ... legacy="1"> with NO type/hex body. The level editor's model loader
# parses these nested elements to find entity model files (see model_loader.py).
#
# We reproduce FCBConverter's nested XML EXACTLY for editor parity, but ALSO stash
# the authoritative original field bytes on the <field> as a hidden __rawhex
# attribute so xml_to_fcb can round-trip byte-exact (FCBConverter's own re-encode
# is lossy -- it drops a trailing 0x00 and forces Unknown1=0). On import, __rawhex
# is authoritative and the nested XML is ignored (same pattern as BinHex).
# ---------------------------------------------------------------------------
def _rml_read_packed_u32(b, p):
    """Gibbed ReadValuePackedU32: <0xFE literal, ==0xFE error, ==0xFF -> u32."""
    v = b[p]
    p += 1
    if v < 0xFE:
        return v, p
    if v == 0xFE:
        raise ValueError("packed u32 0xFE")
    return struct.unpack_from("<I", b, p)[0], p + 4


class _RmlNode:
    __slots__ = ("name", "value", "attrs", "children", "ni", "vi")

    def __init__(self):
        self.attrs = []        # list of [nameIndex, valueIndex, name, value]
        self.children = []
        self.value = ""
        self.name = ""
        self.ni = 0
        self.vi = 0


def _rml_decode(v):
    """Decode a legacy RML field value (value[0]==0) into an _RmlNode tree.

    Returns (root, end_pos). end_pos is where the string table ends; the FCB field
    value frequently has 1 extra trailing 0x00 beyond it which is NOT consumed
    (preserved verbatim via __rawhex). Raises on any malformed input so the caller
    can fall back to plain BinHex."""
    if not v or v[0] != 0:
        raise ValueError("not legacy RML")
    p = 1
    _unknown1 = v[p]; p += 1                       # stored but cosmetic-irrelevant
    strtab_size, p = _rml_read_packed_u32(v, p)
    total_nodes, p = _rml_read_packed_u32(v, p)
    total_attrs, p = _rml_read_packed_u32(v, p)
    cnt = [1, 0]                                   # actualNodeCount, actualAttrCount

    def parse_node():
        nonlocal p
        n = _RmlNode()
        n.ni, p = _rml_read_packed_u32(v, p)
        n.vi, p = _rml_read_packed_u32(v, p)
        ac, p = _rml_read_packed_u32(v, p)
        cc, p = _rml_read_packed_u32(v, p)
        cnt[0] += cc
        cnt[1] += ac
        for _ in range(ac):
            unk, p2 = _rml_read_packed_u32(v, p); p = p2
            if unk != 0:
                raise ValueError("attr unknown != 0")
            ani, p2 = _rml_read_packed_u32(v, p); p = p2
            avi, p2 = _rml_read_packed_u32(v, p); p = p2
            n.attrs.append([ani, avi, None, None])
        for _ in range(cc):
            n.children.append(parse_node())
        return n

    root = parse_node()
    if cnt[0] != total_nodes or cnt[1] != total_attrs:
        raise ValueError("RML node/attr count mismatch")
    end = p + strtab_size
    if end > len(v):
        raise ValueError("RML string table overruns value")
    strtab = v[p:end]
    # Build offset -> string by walking NUL-terminated UTF-8 entries. Indices are
    # BYTE offsets into the table (dedup: several indices may share an entry-start).
    offmap = {}
    i = 0
    L = len(strtab)
    while i < L:
        z = strtab.find(0, i)
        if z < 0:
            z = L
        offmap[i] = strtab[i:z].decode("utf-8", errors="replace")
        i = z + 1

    def resolve(n):
        n.name = offmap.get(n.ni, "")
        n.value = offmap.get(n.vi, "")
        for a in n.attrs:
            a[2] = offmap.get(a[0], "")
            a[3] = offmap.get(a[1], "")
        for c in n.children:
            resolve(c)

    resolve(root)
    return root, end


def _rml_emit(node, depth, ap, ind_fn, esc):
    """Emit an _RmlNode subtree as .NET-XmlWriter-Indent XML (2-space indent),
    matching ConvertXml.Program.WriteNode. A node whose name starts with a digit
    gets a leading '_'. A node with no children and no text is self-closing."""
    ind = ind_fn(depth)
    nm = node.name
    if nm and nm[0].isdigit():
        nm = "_" + nm
    attrs = "".join(' %s="%s"' % (a[2], esc(a[3])) for a in node.attrs)
    has_text = node.value is not None and node.value != ""
    if not node.children and not has_text:
        ap("%s<%s%s />\n" % (ind, nm, attrs))
        return
    if not node.children and has_text:
        # WriteNode writes children then (if Value) text. With no children the
        # XmlWriter emits <name ...>text</name> on a single line.
        ap("%s<%s%s>%s</%s>\n" % (ind, nm, attrs, esc(node.value), nm))
        return
    ap("%s<%s%s>\n" % (ind, nm, attrs))
    for c in node.children:
        _rml_emit(c, depth + 1, ap, ind_fn, esc)
    # A node with children AND text: .NET writes children first, then the text as
    # an inline value before the close tag (on its own, un-indented, follows close
    # of last child). Observed Avatar files never hit this; emit text after children.
    if has_text:
        ap("%s%s\n" % (ind_fn(depth + 1), esc(node.value)))
    ap("%s</%s>\n" % (ind, nm))


# ---------------------------------------------------------------------------
# Dedup decision stream (compact, self-contained byte-exact replay overlay)
#
# Emitted in the SAME pre-order as the expanded XML (object; fields in order;
# children in order). For every object encountered AS A CHILD we record one bit
# "is object back-ref"; if set, a varint ordinal follows and its (expanded)
# subtree is NOT descended on encode. For every inline object's fields we record
# one bit per field "is value back-ref"; if set, a varint delta follows.
# The whole stream is zlib+base64'd into the root @__dedup attribute.
# ---------------------------------------------------------------------------
class _BitWriter:
    def __init__(self):
        self.bits = bytearray()
        self.cur = 0
        self.nbits = 0
        self.varints = bytearray()

    def bit(self, b):
        self.cur |= (1 & b) << self.nbits
        self.nbits += 1
        if self.nbits == 8:
            self.bits.append(self.cur)
            self.cur = 0
            self.nbits = 0

    def varint(self, v):
        while True:
            x = v & 0x7F
            v >>= 7
            if v:
                self.varints.append(x | 0x80)
            else:
                self.varints.append(x)
                break

    def finish(self):
        if self.nbits:
            self.bits.append(self.cur)
        # layout: u32 bitlen | bits | varints
        import struct as _s
        head = _s.pack("<I", len(self.bits))
        return bytes(head) + bytes(self.bits) + bytes(self.varints)


class _BitReader:
    def __init__(self, blob):
        import struct as _s
        nbytes = _s.unpack_from("<I", blob, 0)[0]
        self.bits = blob[4:4 + nbytes]
        self.varints = blob[4 + nbytes:]
        self.bitpos = 0
        self.vpos = 0

    def bit(self):
        byte = self.bits[self.bitpos >> 3]
        b = (byte >> (self.bitpos & 7)) & 1
        self.bitpos += 1
        return b

    def varint(self):
        shift = 0
        result = 0
        while True:
            x = self.varints[self.vpos]
            self.vpos += 1
            result |= (x & 0x7F) << shift
            if not (x & 0x80):
                break
            shift += 7
        return result


def _build_dedup_stream(root):
    """Walk the recorded (shared-node) tree in expanded pre-order, emitting the
    object/field back-ref decisions. Returns the base64(zlib(stream))."""
    import base64
    bw = _BitWriter()

    def visit_inline(node):
        # fields: bit per field; if value back-ref, varint(delta)
        for fld in node.fields:
            bref = fld[2]
            if bref is not None:
                bw.bit(1)
                bw.varint(bref)
            else:
                bw.bit(0)
        # children: per child, bit "is objref"; if set varint(ordinal) and DO
        # NOT descend; else descend.
        for i, ch in enumerate(node.children):
            ordn = node.child_refs[i]
            if ordn is not None:
                bw.bit(1)
                bw.varint(ordn)
            else:
                bw.bit(0)
                visit_inline(ch)

    visit_inline(root)
    blob = bw.finish()
    return base64.b64encode(zlib.compress(blob, 9)).decode("ascii")


# ---------------------------------------------------------------------------
# XML escaping (match C# XmlWriter attribute/text behaviour)
# ---------------------------------------------------------------------------
# bytes 0x00-0x7F pass through; 0x80-0xFF -> '?' (0x3F). Reproduces .NET's ASCII
# decoder byte-for-byte; used with .decode("latin-1") which never raises.
_ASCII_QMARK = bytes(range(0x80)) + b"?" * 0x80


_ESC_TABLE = {
    ord("&"): "&amp;",
    ord("<"): "&lt;",
    ord(">"): "&gt;",
    ord('"'): "&quot;",
    ord("\n"): "&#xA;",
    ord("\r"): "&#xD;",
    ord("\t"): "&#x9;",
}
# Fast membership test: any char that needs escaping. str.translate handles the
# replacement in one C-level pass, but we first check the common case (no special
# char) so unchanged strings are returned without building anything.
_ESC_SCAN = re.compile(r'[&<>"\n\r\t]')


_esc_search = _ESC_SCAN.search


def _esc_attr(s):
    if _esc_search(s) is None:
        return s
    return s.translate(_ESC_TABLE)


# .NET Regex \p{C}+ over the ASCII-decoded string (bytes >= 0x80 already became
# '?'); the only control chars that can survive are C0 (0x00-0x1F) and DEL (0x7F).
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]+")


# ---------------------------------------------------------------------------
# fcb_to_xml
# ---------------------------------------------------------------------------
def fcb_to_xml(data, names=None, defs=None, target_file=""):
    if names is None:
        names = load_names()
    root, end, obj_count, val_count, had_backref = parse_tree(data, record=True)
    if end != len(data):
        raise ValueError("did not consume to EOF (%d/%d)" % (end, len(data)))
    if defs is None:
        defs = load_defs(target_file)
    else:
        defs.set_target(target_file)

    out = []
    ap = out.append
    ap('<?xml version="1.0" encoding="utf-8"?>\n')
    ap("<!--Converted by fcb_convert.py (native Python port of FCBConverter). "
       "Names from FCBConverterStrings.list + user CRC dict. "
       "BinHex is authoritative; value-* are cosmetic.-->\n")
    # Byte-exact repack metadata, kept in a comment so the root element stays clean
    # (the FCB header objCount/valCount are game-specific and NOT recomputable; e.g.
    # sectorsdep stores valCount=101 though it has 770 values). Do not edit this line.
    _meta = '<!--fcb_meta objcount="%d" valcount="%d" compress="%d"' % (
        obj_count, val_count, 1 if had_backref else 0)
    if had_backref:
        _meta += ' dedup="%s"' % _build_dedup_stream(root)
    ap(_meta + '-->\n')

    nm = names.name
    process_ctx = defs.process_ctx
    field_ctx = defs.field_ctx
    process_object = defs.process_object
    esc = _esc_attr
    _crc32 = crc32
    _crc64 = crc64
    _ctrl_sub = _CTRL_RE.sub
    _qmark = _ASCII_QMARK
    _unpack_I = struct.Struct("<I").unpack_from
    _deser_f = _deser
    _arr_item = _ARR_ITEM
    _GP = GUESS_PREFIX
    names_name = names.name
    _indent_cache = {}
    # Per-hash escaped-attribute cache: the great majority of object/field names
    # recur thousands of times; escape each once. Maps hash -> (name_str, attr_str)
    # where attr_str is '' for an unnamed hash or ' name="ESCAPED"' otherwise.
    _name_attr = {}

    def _ind(depth):
        s = _indent_cache.get(depth)
        if s is None:
            s = "  " * depth
            _indent_cache[depth] = s
        return s

    def _name_pair(h):
        pair = _name_attr.get(h)
        if pair is None:
            hx = "%08X" % h
            nmv = nm(h) or ""
            # cached attr string already includes the leading hash="..." plus any
            # name="...", so emit just appends type/value attrs to it.
            base = 'hash="%s"%s' % (
                hx, (' name="%s"' % _esc_attr(nmv)) if nmv != "" else "")
            pair = (nmv, hx, base)
            _name_attr[h] = pair
        return pair

    def emit(node, depth, def_object):
        ind = _ind(depth)
        h = node.hash
        node_name, hhex, objattr = _name_pair(h)
        # object def context. NOTE: objects whose def carries action="External"
        # are emitted by FCBConverter to a separate file and do NOT establish a
        # persistent def context for their descendants in the inlined output, so
        # we skip context-setting for them (this makes e.g. Knot.Value resolve via
        # the top-level Knot def -> Hash32, matching the oracle).
        to = process_object(def_object, node_name, hhex, node.fields)
        cur = to["CurrentObject"]
        if cur is not None and to["Action"] != "External":
            def_object = cur

        # Root carries no metadata attributes (clean, like FCBConverter); the byte-exact
        # header counts + dedup stream live in the leading <!--fcb_meta ...--> comment.
        if not node.fields and not node.children:
            ap("%s<object %s />\n" % (ind, objattr))
            return
        ap("%s<object %s>\n" % (ind, objattr))
        cind = _ind(depth + 1)
        ctx = field_ctx(def_object, node_name, hhex)

        prev_node_val = ""
        for fld in node.fields:
            fh, v = fld[0], fld[1]
            fname, fhex, fattrs = _name_pair(fh)

            binary_hex = v.hex()                       # lowercase forward
            # C#: str = Encoding.ASCII.GetString(value, 0, len-1). The .NET ASCII
            # decoder maps every byte >= 0x80 to '?' (U+003F), not U+FFFD.
            # bytes.translate (C-level) + latin-1 decode reproduces this exactly.
            strv = v[:-1].translate(_qmark).decode("latin-1") if v else ""

            # Hash detection only matters when the previous field was a String; the
            # reverse-hex + crc32/crc64 of prev_node_val are otherwise pure waste.
            is_hash32 = False
            is_hash64 = False
            if prev_node_val != "":
                rev_hex = v[::-1].hex()                 # lowercase reversed
                is_hash32 = ("%08x" % _crc32(prev_node_val)) == rev_hex
                if not is_hash32:
                    is_hash64 = ("%016x" % _crc64(prev_node_val)) == rev_hex

            skip_value = False
            field_type = "Invalid"

            if is_hash32:
                fattrs += ' %sComputeHash32="%s"' % (_GP, esc(prev_node_val))
            elif is_hash64:
                fattrs += ' %sComputeHash64="%s"' % (_GP, esc(prev_node_val))
            else:
                t = process_ctx(ctx, fhex, binary_hex, fname, strv, True)
                field_type = t["Type"]
                action = t["Action"]
                if action:
                    skip_value = True

                    if action == "FindInDictionarySkip":
                        if len(v) < 4:
                            skip_value = False
                            field_type = "BinHex"
                        else:
                            uv = _unpack_I(v)[0]
                            resolved = names_name(uv)
                            if resolved is not None:
                                fattrs += ' %s%s="%s"' % (_GP, field_type,
                                                          esc(resolved))
                                skip_value = False
                                field_type = "BinHex"
                            else:
                                skip_value = False
                                field_type = "Hash32"
                    elif action == "Array":
                        # Adopt FCBConverter's Array representation IFF it
                        # reconstructs byte-exact; else fall back to BinHex.
                        item_type = t["ArrayItemType"]
                        item_name = t["ArrayItemName"]
                        arr_items = None
                        if item_type in _arr_item and item_name:
                            arr_items = _array_items(item_type, v)
                        if arr_items is not None:
                            ap("%s<field %s>\n" % (cind, fattrs))
                            gind = _ind(depth + 2)
                            for it in arr_items:
                                ap("%s<%s>%s</%s>\n" %
                                   (gind, item_name, esc(it), item_name))
                            ap("%s</field>\n" % cind)
                            prev_node_val = ""
                            continue
                        skip_value = False
                        field_type = "BinHex"
                    elif action == "XMLRML":
                        # Structural expansion the editor needs (hidDescriptor /
                        # LocalProperties). value[0]==0 -> legacy RML object: emit
                        # the SAME nested XML FCBConverter does (legacy="1" + nested
                        # <component>/<object>/<resource>/... with no type/hex body),
                        # plus a hidden __rawhex carrying the authoritative original
                        # bytes for byte-exact round-trip. Any decode failure or the
                        # value[0]!=0 / empty cases fall back to plain BinHex.
                        rml_root = None
                        if len(v) > 0 and v[0] == 0:
                            try:
                                rml_root, _rend = _rml_decode(v)
                            except Exception:
                                rml_root = None
                        if rml_root is not None:
                            # The authoritative original bytes ride in a __rawhex
                            # ATTRIBUTE, which both encoders already read
                            # (`attr.get("__rawhex")` in the expat path,
                            # `child.get("__rawhex")` in the ElementTree `build`
                            # path).  There is no RML re-encoder, so these bytes
                            # are the only way to rebuild the field.
                            #
                            # It used to be a comment instead, for cosmetics.  That
                            # was silently fatal: ElementTree DROPS comments, so the
                            # instant anything round-tripped the tree through
                            # ET.parse (which the editor does for every
                            # mapsdata/omnis edit) the bytes were gone, `build` fell
                            # through to the array branch, and re-encoding died with
                            # "invalid literal for int() with base 10" on the nested
                            # <component> element.  The byte-exact round-trip only
                            # ever survived via the fcb_meta fast path, which an
                            # edited tree also loses.  Keep this an attribute.
                            ap('%s<field %s legacy="1" __rawhex="%s">\n'
                               % (cind, fattrs, binary_hex.upper()))
                            _rml_emit(rml_root, depth + 2, ap, _ind, esc)
                            ap("%s</field>\n" % cind)
                            prev_node_val = ""
                            continue
                        # value[0]!=0 (new-format inline XML) and empty values are
                        # rare/absent in Avatar legacy files; keep them byte-exact
                        # as BinHex rather than re-emitting a possibly-lossy string.
                        skip_value = False
                        field_type = "BinHex"
                    elif action in ("FCBRML", "CompressedFCB",
                                    "InstancesSectorData", "CollectionZoneData",
                                    "ReadListHashes", "ReadListFiles",
                                    "MoveBinDataChunk", "DoNothing"):
                        # Robust byte-exact path: never apply structural actions;
                        # always emit plain BinHex (re-decodes identically).
                        skip_value = False
                        field_type = "BinHex"

                if not skip_value and field_type != "BinHex":
                    dv = _deser_f(field_type, v)
                    if dv is None:
                        field_type = "BinHex"
                    else:
                        fattrs += ' %s%s="%s"' % (_GP, field_type, esc(dv))
                        if field_type == "String":
                            prev_node_val = dv

                if not skip_value and field_type == "BinHex" and not action:
                    s2 = _ctrl_sub("", strv).replace("?", "")
                    if s2 != "":
                        fattrs += ' strVal="%s"' % esc(s2)

            if field_type != "String":
                prev_node_val = ""

            if not skip_value:
                ap("%s<field %s type=\"BinHex\">%s</field>\n" %
                   (cind, fattrs, binary_hex.upper()))
            else:
                ap("%s<field %s />\n" % (cind, fattrs))

        for ch in node.children:
            emit(ch, depth + 1, def_object)
        ap("%s</object>\n" % ind)

    emit(root, 0, None)
    return "".join(out)


# ---------------------------------------------------------------------------
# Encode (BinaryObject.Serialize, isCompressEnabled=True path)
# ---------------------------------------------------------------------------
def _write_count(buf, value, is_offset):
    if is_offset or value >= 0xFE:
        buf.append(0xFE if is_offset else 0xFF)
        buf += struct.pack("<I", value)
    else:
        buf.append(value & 0xFF)


def _values_hash(node):
    # GetValuesHash: NameHash.ToString("X") (uppercase, no pad) + per field
    # Key.ToString("X")+lowercasehex(value) + recurse children.
    parts = ["%X" % node.hash]
    for (fh, v) in node.fields:
        parts.append("%X" % fh)
        parts.append(v.hex())
    for ch in node.children:
        parts.append(_values_hash(ch))
    return "".join(parts)


def _serialize_node(node, buf, ptr_fields, ptr_objects, counters):
    counters[1] += len(node.fields)          # totalValueCount += Fields.Count
    _write_count(buf, len(node.children), False)
    buf += struct.pack("<I", node.hash)
    _write_count(buf, len(node.fields), False)
    for (fh, v) in node.fields:
        buf += struct.pack("<I", fh)
        key = v.hex()
        tgt = ptr_fields.get(key)
        if tgt is not None:
            buf.append(0xFE)
            buf += struct.pack("<I", len(buf) - tgt)
        else:
            _write_count(buf, len(v), False)
            if len(key) > 8:
                ptr_fields[key] = len(buf)   # position of first value byte
            buf += v
    for ch in node.children:
        chash = _values_hash(ch)
        if chash != "" and chash in ptr_objects:
            buf.append(0xFE)
            buf += struct.pack("<I", ptr_objects[chash])
        else:
            counters[2] += 1                 # offsetsObjectsNum++
            if chash != "" and chash not in ptr_objects:
                ptr_objects[chash] = counters[2]
            counters[0] += 1                 # totalObjectCount++
            _serialize_node(ch, buf, ptr_fields, ptr_objects, counters)


def _serialize_node_nc(node, buf, counters):
    """Non-compressed (no-dedup) serialize path."""
    counters[0] += len(node.children)
    counters[1] += len(node.fields)
    _write_count(buf, len(node.children), False)
    buf += struct.pack("<I", node.hash)
    _write_count(buf, len(node.fields), False)
    for (fh, v) in node.fields:
        buf += struct.pack("<I", fh)
        _write_count(buf, len(v), False)
        buf += v
    for ch in node.children:
        _serialize_node_nc(ch, buf, counters)


def _serialize_node_replay(node, buf, counters):
    """Replay-mode serialize: reproduces the exact original byte stream using the
    recorded decisions. Because the layout is identical to the original, recorded
    back-ref deltas (and object ordinals) are written verbatim.
    Field tuples are (fh, val, bref_delta_or_None); child_refs[i] is the object
    back-ref ordinal or None."""
    counters[1] += len(node.fields)
    _write_count(buf, len(node.children), False)
    buf += struct.pack("<I", node.hash)
    _write_count(buf, len(node.fields), False)
    for fld in node.fields:
        fh, v, bref = fld
        buf += struct.pack("<I", fh)
        if bref is not None:
            buf.append(0xFE)
            buf += struct.pack("<I", bref)     # verbatim original delta
        else:
            _write_count(buf, len(v), False)
            buf += v
    for i, ch in enumerate(node.children):
        ordn = node.child_refs[i]
        if ordn is not None:
            buf.append(0xFE)
            buf += struct.pack("<I", ordn)     # verbatim original ordinal
        else:
            counters[0] += 1
            _serialize_node_replay(ch, buf, counters)


def encode_tree_replay(root, force_obj, force_val):
    body = bytearray()
    counters = [1, 0]
    _serialize_node_replay(root, body, counters)
    obj_count = force_obj if force_obj is not None else counters[0]
    val_count = force_val if force_val is not None else counters[1]
    head = MAGIC + struct.pack("<HH", 2, 0) + struct.pack("<II", obj_count, val_count)
    return head + bytes(body)


def encode_tree(root, force_obj=None, force_val=None, compress=True):
    """Serialize a Node tree into FCB bytes. Header counts forced if provided."""
    body = bytearray()
    if compress:
        ptr_fields = {}
        ptr_objects = {}
        counters = [1, 0, 0]   # totalObjectCount(=1 root), totalValueCount, offsets
        _serialize_node(root, body, ptr_fields, ptr_objects, counters)
    else:
        counters = [1, 0, 0]
        _serialize_node_nc(root, body, counters)
    obj_count = force_obj if force_obj is not None else counters[0]
    val_count = force_val if force_val is not None else counters[1]
    head = bytearray()
    head += MAGIC
    head += struct.pack("<HH", 2, 0)
    head += struct.pack("<II", obj_count, val_count)
    return bytes(head) + bytes(body)


# ---------------------------------------------------------------------------
# xml_to_fcb (port of Importing.cs ReadNode, BinHex-only path)
# ---------------------------------------------------------------------------
def _serialize_field(ftype, text):
    """Encode a typed field value back to bytes (used only when type != BinHex)."""
    ft = ftype
    if ft == "Boolean":
        return b"\x01" if text == "True" else b"\x00"
    if ft == "UInt8":
        return struct.pack("<B", int(text) & 0xFF)
    if ft == "Int8":
        return struct.pack("<b", int(text))
    if ft == "UInt16":
        return struct.pack("<H", int(text) & 0xFFFF)
    if ft == "Int16":
        return struct.pack("<h", int(text))
    if ft in ("UInt32", "Id32"):
        return struct.pack("<I", int(text) & 0xFFFFFFFF)
    if ft in ("Int32", "Enum"):
        return struct.pack("<i", int(text))
    if ft == "UInt64":
        return struct.pack("<Q", int(text) & MASK64)
    if ft == "Int64":
        return struct.pack("<q", int(text))
    if ft == "Float32":
        return struct.pack("<f", float(text))
    if ft == "Float64":
        return struct.pack("<d", float(text))
    if ft == "Vector2":
        return struct.pack("<ff", *[float(x) for x in text.split(",")])
    if ft == "Vector3":
        return struct.pack("<fff", *[float(x) for x in text.split(",")])
    if ft == "Vector4":
        return struct.pack("<ffff", *[float(x) for x in text.split(",")])
    if ft == "String":
        return text.encode("utf-8") + b"\x00"
    if ft == "Hash32":
        return struct.pack("<I", int(text, 16))
    if ft == "Hash64":
        return struct.pack("<Q", int(text, 16))
    if ft == "Id64":
        if text == "-1":
            return b"\xff" * 8
        return struct.pack("<Q", int(text))
    if ft == "ComputeHash32":
        return struct.pack("<I", crc32(text))
    if ft == "ComputeHash64":
        return struct.pack("<Q", crc64(text))
    raise ValueError("unsupported manual type on import: %s" % ft)


def _build_tree_expat(xml_text, arr_map):
    """Build the Node tree directly from an expat SAX pass — no intermediate
    ElementTree (saves ~one Element per object+field on huge files). Handles the
    three element kinds the emitter produces: <object>, <field>, and array-item
    children (<ArrayItemName>). Semantics match the old ET-based build() exactly."""
    import xml.parsers.expat as _expat

    ITEMMAP = {0: "Int32", 1: "Vector2", 2: "Vector3", 3: "Vector4"}
    _crc32 = crc32
    _fromhex = bytes.fromhex
    _arr_get = arr_map.get
    _ser = _serialize_field
    _arr_from = _array_from_items

    root_holder = []
    node_stack = []          # stack of Node (open <object>)
    stack_push = node_stack.append
    stack_pop = node_stack.pop
    cur_field = None         # [fh, type, text_parts, item_kids, rawhex] for open <field>
    text_target = None       # list to append char data into, or None
    skip_depth = [0]         # >0 while inside a __rawhex field's nested RML subtree

    def start(tag, attr):
        nonlocal cur_field, text_target
        if skip_depth[0] > 0:
            # Inside an XMLRML legacy field whose __rawhex is authoritative; ignore
            # every nested element (<component>/<object>/<resource>/... and any
            # <field>/<object> names that collide with FCB element names).
            skip_depth[0] += 1
            text_target = None
            return
        if tag == "field":
            nm = attr.get("name")
            if nm is not None and nm.strip() != "":
                fh = _crc32(nm)
            else:
                fh = int(attr["hash"], 16)
            rawhex = attr.get("__rawhex")
            tp = []
            cur_field = [fh, attr.get("type", ""), tp, None, rawhex]
            text_target = tp
            if rawhex is not None:
                # Authoritative raw bytes: skip the nested RML expansion entirely.
                skip_depth[0] = 1
        elif tag == "object":
            nm = attr.get("name")
            if nm is not None and nm.strip() != "":
                hh = _crc32(nm)
            else:
                hh = int(attr["hash"], 16)
            node = Node(hh)
            if node_stack:
                node_stack[-1].children.append(node)
            else:
                root_holder.append(node)
            stack_push(node)
            text_target = None
        else:
            # array-item child of a field (e.g. <ArrayItemName>)
            cf = cur_field
            if cf is not None:
                parts = []
                ik = cf[3]
                if ik is None:
                    ik = cf[3] = []
                ik.append((tag, parts))
                text_target = parts

    def chardata(s):
        if text_target is not None:
            text_target.append(s)

    def end(tag):
        nonlocal cur_field, text_target
        if skip_depth[0] > 1:
            # Closing a nested RML element inside a __rawhex field.
            skip_depth[0] -= 1
            text_target = None
            return
        if tag == "field":
            # If we were skipping this field's RML subtree, skip_depth is now 1.
            skip_depth[0] = 0
            fh, ftype, text_parts, item_kids, rawhex = cur_field
            if rawhex is not None:
                # XMLRML legacy: authoritative original bytes (ignore nested XML).
                val = _fromhex(rawhex.strip()) if rawhex.strip() else b""
            elif item_kids:
                item_name = item_kids[0][0]
                item_type = _arr_get(item_name)
                texts = ["".join(p) for _n, p in item_kids]
                if item_type is None:
                    item_type = ITEMMAP.get(texts[0].count(","))
                val = _arr_from(item_type, texts)
            elif ftype == "" or ftype.lower() == "binhex":
                if text_parts:
                    txt = ("".join(text_parts)).strip()
                    val = _fromhex(txt) if txt else b""
                else:
                    val = b""
            else:
                val = _ser(ftype, "".join(text_parts))
            node_stack[-1].fields.append((fh, val))
            cur_field = None
            text_target = None
        elif tag == "object":
            stack_pop()
            text_target = None
        else:
            # closing an array-item child: redirect text back to nothing
            text_target = None

    def comment(data):
        # Capture the hidden <!--rawhex HEX--> that carries a legacy field's
        # authoritative original bytes (emitted instead of a __rawhex attribute).
        # Fires after the <field> start and before its nested RML, so cur_field is
        # open with rawhex still None; set it and skip the nested expansion.
        if skip_depth[0] > 0:
            return
        d = data.strip()
        if d.startswith("rawhex ") and cur_field is not None and cur_field[4] is None:
            cur_field[4] = d[7:].strip()
            skip_depth[0] = 1

    p = _expat.ParserCreate("utf-8")
    p.buffer_text = True
    p.StartElementHandler = start
    p.EndElementHandler = end
    p.CharacterDataHandler = chardata
    p.CommentHandler = comment
    p.Parse(xml_text.encode("utf-8"), True)
    return root_holder[0]


def xml_to_fcb(xml_text):
    if isinstance(xml_text, bytes):
        xml_text = xml_text.decode("utf-8-sig")
    # Byte-exact metadata lives in the leading <!--fcb_meta ...--> comment (ElementTree
    # drops comments on parse, so pull it from the raw text). Fall back to the older
    # root-attribute form for XML produced before this change.
    m = re.search(r'<!--fcb_meta\s+objcount="(\d+)"\s+valcount="(\d+)"\s+compress="(\d+)"'
                  r'(?:\s+dedup="([A-Za-z0-9+/=]+)")?\s*-->', xml_text)
    if m:
        force_obj = int(m.group(1)); force_val = int(m.group(2))
        compress = (m.group(3) == "1"); dedup_b64 = m.group(4)
        arr_map = _array_name_map()
        root = _build_tree_expat(xml_text, arr_map)
    else:
        # Legacy XML with metadata as root attributes (pre-comment form). Use ET so
        # the root @__* attributes are available.
        root_el = ET.fromstring(xml_text)
        fo = root_el.get("__objcount"); fv = root_el.get("__valcount")
        force_obj = int(fo) if fo is not None else None
        force_val = int(fv) if fv is not None else None
        compress = (root_el.get("__compress") == "1")
        dedup_b64 = root_el.get("__dedup")

        def name_and_hash(el):
            nm = el.get("name")
            hh = el.get("hash")
            if nm is not None and nm.strip() != "":
                return crc32(nm)
            return int(hh, 16)

        arr_map = _array_name_map()

        def build(el):
            node = Node(name_and_hash(el))
            for child in el:
                tag = child.tag
                if tag == "field":
                    fh = name_and_hash(child)
                    rawhex = child.get("__rawhex")
                    if rawhex is not None:
                        rh = rawhex.strip()
                        node.fields.append((fh, bytes.fromhex(rh) if rh else b""))
                        continue
                    item_kids = [c for c in child if c.tag != "field"
                                 and c.tag != "object"]
                    if item_kids:
                        item_name = item_kids[0].tag
                        item_type = arr_map.get(item_name)
                        if item_type is None:
                            # A legacy descriptor expansion (hidDescriptor /
                            # LocalProperties) also has non-field children, but it
                            # is NOT an array — its items carry structure, not a
                            # numeric text body.  Without __rawhex there is no way
                            # back to bytes (no RML re-encoder exists), so say that
                            # plainly instead of dying inside int() on whitespace.
                            head = (item_kids[0].text or "")
                            if not head.strip():
                                raise ValueError(
                                    "field %r holds a structural <%s> expansion but "
                                    "carries no __rawhex, so it cannot be re-encoded. "
                                    "This XML was produced by an older converter — "
                                    "reconvert the .fcb with the current native "
                                    "converter and edit that."
                                    % (child.get("name") or child.get("hash"),
                                       item_name))
                            commas = head.count(",")
                            item_type = {0: "Int32", 1: "Vector2",
                                         2: "Vector3", 3: "Vector4"}.get(commas)
                        texts = [(c.text or "") for c in item_kids]
                        val = _array_from_items(item_type, texts)
                        node.fields.append((fh, val))
                        continue
                    ftype = child.get("type", "")
                    if ftype == "" or ftype.lower() == "binhex":
                        txt = (child.text or "").strip()
                        val = bytes.fromhex(txt) if txt else b""
                    else:
                        val = _serialize_field(ftype, (child.text or ""))
                    node.fields.append((fh, val))
                elif tag == "object":
                    node.children.append(build(child))
            return node

        root = build(root_el)

    if dedup_b64:
        import base64
        blob = zlib.decompress(base64.b64decode(dedup_b64))
        br = _BitReader(blob)
        return _encode_with_stream(root, br, force_obj, force_val)

    return encode_tree(root, force_obj, force_val, compress)


def _encode_with_stream(root, br, force_obj, force_val):
    """Serialize the EXPANDED tree applying the recorded dedup decision stream
    (object back-refs and value back-refs) in expanded pre-order. Guarantees a
    byte-exact reproduction of the original FCB."""
    body = bytearray()
    counters = [1, 0]

    def ser(node):
        counters[1] += len(node.fields)
        _write_count(body, len(node.children), False)
        body.extend(struct.pack("<I", node.hash))
        _write_count(body, len(node.fields), False)
        for (fh, v) in node.fields:
            body.extend(struct.pack("<I", fh))
            if br.bit():
                body.append(0xFE)
                body.extend(struct.pack("<I", br.varint()))   # verbatim delta
            else:
                _write_count(body, len(v), False)
                body.extend(v)
        for ch in node.children:
            if br.bit():
                body.append(0xFE)
                body.extend(struct.pack("<I", br.varint()))   # verbatim ordinal
            else:
                counters[0] += 1
                ser(ch)

    ser(root)
    obj_count = force_obj if force_obj is not None else counters[0]
    val_count = force_val if force_val is not None else counters[1]
    head = MAGIC + struct.pack("<HH", 2, 0) + struct.pack("<II", obj_count, val_count)
    return head + bytes(body)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _target_name(path):
    return os.path.basename(path)


def main(argv):
    names = load_names()
    targets = []
    for a in argv:
        if a.startswith("-source="):
            folder = a[len("-source="):]
            for dp, _d, fs in os.walk(folder):
                targets += [os.path.join(dp, f) for f in fs
                            if f.lower().endswith(".fcb")]
        else:
            targets.append(a)
    print("names: n32=%d (n64 lazy)" % len(names.n32))
    for p in targets:
        try:
            if p.lower().endswith(".fcb"):
                data = open(p, "rb").read()
                xml = fcb_to_xml(data, names, target_file=_target_name(p))
                op = p + ".xml"
                with open(op, "w", encoding="utf-8", newline="") as f:
                    f.write(xml)
                print("OK  %s -> %s" % (os.path.basename(p), os.path.basename(op)))
            elif p.lower().endswith(".xml"):
                xml = open(p, "r", encoding="utf-8-sig").read()
                out = xml_to_fcb(xml)
                op = p + ".out.fcb"
                open(op, "wb").write(out)
                print("OK  %s -> %s" % (os.path.basename(p), os.path.basename(op)))
        except Exception as e:
            import traceback
            traceback.print_exc()
            print("ERR %s : %s" % (os.path.basename(p), e))


if __name__ == "__main__":
    main(sys.argv[1:])
