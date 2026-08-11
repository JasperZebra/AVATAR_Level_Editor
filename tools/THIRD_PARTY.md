# Third-party files in `tools/`

This folder mixes our own source with a few third-party helpers the editor
shells out to or loads. This file records where each one came from, so the
provenance is clear in a public repository.

Nothing here is authored by this project unless it says so.

| File | Origin | Licence | Why it is here |
|---|---|---|---|
| `FCBConverterDefinitions.xml` | [FCBConverter](https://downloads.fcmodding.com/others/fcbconverter/) — Jakub Mareček | **GPL v3** | Conversion schema for FCB ↔ XML. **Modified**: the `action="External" FieldForName="Name"` rule was removed from the `entitylibrary.fcb` entry because it crashed the converter (`BitConverter.ToInt32` on a <4-byte Name). |
| `pak_converter/minilzo_*.dll` | miniLZO — Markus F.X.J. Oberhumer | **GPL v2+** | LZO1X compress/decompress for Avatar `.pak` archives. Loaded via `ctypes` at runtime, not linked. `pak_archive.py` also ships a pure-Python LZO decoder, so reading works without these. |
| `texconv.exe` | [Microsoft DirectXTex](https://github.com/microsoft/DirectXTex) | MIT | DDS/texture conversion. |
| `ww2ogg.exe`, `packed_codebooks_aoTuV_603.bin` | ww2ogg — hcs | permissive (see upstream) | Wwise `.wem` → Ogg Vorbis. |
| `revorb.exe` | ReVorb — jonboy / Xiph-derived | permissive (see upstream) | Fixes Ogg granule positions after `ww2ogg`. |

## Game-derived data

`fcb_names_cache.n32.pkl` is a hash → name lookup table built from strings found
in the games' own files. It contains no game assets, only identifier strings,
and is what makes converted XML human-readable. It is regenerable with
`fcb_names_build.py` from `fcb_names.csv` (not tracked — 659 MB, over GitHub's
100 MB per-file limit).

`avatar_class_hierarchy.*`, `avatar_function_names.md` and `fc2_function_names.md`
are reverse-engineering notes derived from the shipped binaries — names and
structure only.

## Not in this repository

The two `*_FULL_DECOMPILE.txt` Ghidra dumps (~129 MB) are deliberately untracked.
They are regenerable from the game binaries you already own, and binaries in git
history never shrink again.

## FCBConverter itself

`FCBConverter.exe` is **no longer used or shipped** — `fcb_convert.py` is a
from-scratch pure-Python reimplementation of the format (it round-trips
byte-exact, which the original does not). The definitions XML above is the one
remaining piece of that project still in use.
