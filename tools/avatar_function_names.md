# Avatar Dunia Engine — Function Name Reference (best-effort, partial)

Source: `Avatar_Dunia_Retail_1.02_decrypted.dll_FULL_DECOMPILE.txt` (Ghidra decompile, ~2.61M lines).

## Scope / methodology

The dump contains **44,511** functions matching Ghidra's unresolved-symbol pattern
`FUN_[0-9a-f]{8}` (signature regex used for navigation:
`^(void|undefined4|undefined8|int|float|double|char|bool|uint|ulong|longlong|undefined) (__thiscall|__cdecl|__fastcall)? ?FUN_[0-9a-f]+`).
This document labels a **best-effort subset** — not all 44,511. Names are inferred from call
patterns, string-literal neighbours (log/assert messages, RTTI class names, technique/shader
names), struct field access shape, and known Windows/CRT API calls. **Confidence varies per
entry** — treat the one-line justification as the evidence, not the name itself, as ground
truth. Entries build on and stay consistent with prior findings already in `AGENTS.md`
(`InitTerrainSystem`, `InitTerrainChannelTable`, the FCB reader/writer pair, the terrain shader
technique lookup, etc.) — those are not re-derived here.

Two kinds of entries appear:
1. **Mechanically derived** (`RTTI_GetClassInfo_*`, ~1,530 entries): every class's self-registration
   getter function, taken directly from `tools/avatar_class_hierarchy.tsv` (produced by
   `tools/scrape_class_hierarchy.py`, which already parsed the `FUN_100016b0("ClassName", parentGetter())`
   self-registration pattern across the whole dump). These are high-confidence but low-detail —
   they identify *which class* a getter belongs to, not what the class's methods do.
2. **Manually/agent-inferred** (everything else): read from the decompile directly, grouped by
   subsystem, with an inferred verb-first PascalCase name and a justification.

This is a partial sweep of a 2.6M-line file — treat it as a growing index, not a complete map.

**Coverage as of this pass**: ~2,930 unique `FUN_<addr>` addresses labeled (~6.6% of the
44,511 total) — 1,532 mechanical RTTI getters plus ~1,400 individually-investigated functions
across Terrain, Math/Utility, Audio, Asset Loading/World, Networking, Physics/Collision,
Rendering/Graphics, and AI/Scripting. Coverage depth varies a lot by subsystem — see the
per-section notes below and the final wrap-up note at the end of this document for what got
deep vs. shallow treatment, and for a corrected negative result (a promising-looking
"vegetation" address cluster that turned out NOT to be a vegetation system on closer
inspection — see that section for what it actually is).

## Scripting/Lua Class-Registration Idiom (manual deep-dive)

While tracing the `CTerrain` script binding (see Terrain section below), found this exact idiom
repeats verbatim throughout the dump for every script-exposed singleton class: register the class
name string, register a `"GetInstance"` method string, bind a getter function pointer, then call
`FUN_100de5f0(0, classNameArray, ctorOrGetterFn)`. Located every occurrence by grepping the
`(*DAT_1100038c)("GetInstance")` call pattern and pairing it with the preceding class-name string
literal — this cheaply enumerates most of the engine's script-exposed singleton managers:

- `FUN_103c7040` (line 656565) — **ScriptRegister_CTerrain** — registers `"CTerrain"` as a script
  class with `GetInstance` → `FUN_103c6970` and `GetSector` → (see Terrain section).
- `FUN_10217490` (line 372117) — **ScriptRegister_CDominoDelayManager** — registers
  `"CDominoDelayManager"`, a delayed-trigger/timer manager for the "Domino" scripted-event system
  (see below).
- `FUN_10218030` (line 372635) — **ScriptRegister_CDominoSoundManager** — registers
  `"CDominoSoundManager"`, the Domino event system's sound-trigger manager.
- `FUN_102190b0` (line 373294) — **ScriptRegister_CDominoSequenceManager** — registers
  `"CDominoSequenceManager"`, the Domino event system's cutscene/sequence manager.
- `FUN_102a1ec0` (line 458871) — **ScriptRegister_CDominoManager** — registers `"CDominoManager"`,
  the top-level manager for what appears to be the game's scripted mission/quest trigger system
  (Ubisoft's "Domino" event framework, also seen in other Dunia-engine titles) — see also
  `CDominoWaterLevelManager`, `CDominoConsoleCommandManager`, `CDominoSocialRegion*` and
  `CFCXRegionManager` string hits in the Appendix string-tag index below; this whole family is a
  **distinct, sizable subsystem not covered by this pass's subsystem sweeps** — flagged here as a
  good target for a dedicated future session (mission-scripting/trigger system, not AI/pathing).
- `FUN_102cb7d0` (line 487269) — **ScriptRegister_CDominoWaterLevelManager** — registers
  `"CDominoWaterLevelManager"`, a scripted water-level control manager — potentially relevant to the
  editor's water-height/underwater-flag work (see `AGENTS.md`'s byte[3] investigation) as it confirms
  water level is a scriptable, dynamic (not just static per-sector) concept in the engine, though this
  particular manager looks like a gameplay/cutscene trigger, not the terrain data path itself.
- `FUN_102e1c40` (line 501371) — **ScriptRegister_CDominoConsoleCommandManager** — registers
  `"CDominoConsoleCommandManager"`, exposing console-command triggers to the Domino event system.
- `FUN_10349700` (line 572654) — **ScriptRegister_CMovieSystem** — registers `"CMovieSystem"`, the
  cutscene/movie playback manager singleton.
- `FUN_10501990` (line 864882) — **ScriptRegister_CFCXRegionManager** — registers
  `"CFCXRegionManager"` ("FCX" = likely an internal Ubisoft codename prefix seen elsewhere, e.g.
  `CFCXConsoleService` at line 42165), a region/zone-trigger manager.

---

## Terrain (manual deep-dive, builds on AGENTS.md's InitTerrainSystem sequence)

Extends the terrain-init call chain already documented in `AGENTS.md` (`FUN_1046e630` =
`InitTerrainSystem`, line 770433, calling in order: `FUN_1046d9e0`=`BuildTerrainLODWeights`,
`FUN_1046df40`, `FUN_1046e4f0`=`InitTerrainChannelTable`, `FUN_1046e580`=`BuildTerrainSectorEdgeGrid`,
`FUN_1046d990`). Two calls in that chain were previously unlabeled — resolved below — plus
neighbouring functions in the same address cluster and a vegetation-zone reflection function.

- `FUN_1046d990` (line 769841) — **BuildTerrainGridNeighborOffsets** — fills a 65×65 (0x41×0x41,
  matching the confirmed sector stride) short-array table with 4 packed neighbour index deltas per
  cell (`+0x1040`=+row, `sVar1*0x41+0x40`=diag, `+0`=self col, `*0x41`=row-only) — a precomputed
  "neighbour cell index" lookup consumed by the LOD/edge functions, called last in `InitTerrainSystem`.
- `FUN_1046df40` (line 770075) — **BuildTerrainLODStitchWeights** — sibling to `BuildTerrainLODWeights`
  (`FUN_1046d9e0`): iterates the same 3 LOD block sizes (2×2/4×4/8×8) over an 8×8 sub-grid, but instead
  of just interpolation factors it computes and stores an **edge classification tag (0/2/3)** per cell
  plus 4 area-weight floats into BOTH a flat array (`piVar6`, stride 0x18) AND a dynamic-array insert
  via `FUN_1046dbf0` — reads as a T-junction/"crack fix" stitching-weight table for blending between
  adjacent terrain LOD block sizes (a classic terrain-LOD popping/seam mitigation structure); not
  fully certain of the exact geometric semantics, medium confidence.
- `FUN_1046dbf0` (line 769949) — **TerrainDynArrayReserveOrGrow** — growable-array append helper: if
  the target pointer is exactly at the current end-of-buffer and capacity (derived from a
  count/shift-encoded capacity field) allows it, bumps the count in place; otherwise falls through to
  `FUN_100ed980` (a generic array-grow/realloc routine) — used by both LOD table builders above to
  append per-cell records.
- `FUN_1046ddd0` (line 769968) — **CopyTerrainLODStitchRecord** — tight loop copying a fixed 0x15-dword
  struct (matches the record shape written by `BuildTerrainLODStitchWeights`) from one buffer to
  another; a record-copy helper for the stitch-weight table, likely used when growing/reallocating it.
- `FUN_1046e400` (line 770294) — **RegisterTerrainDataChannels** (already named in AGENTS.md; included
  here for completeness) — registers exactly 3 channel descriptors `"TerrainHeights"`(type 7),
  `"TerrainNormals"`(type 4), `"TerrainParams"`(type 5).
- `FUN_1046e6a0` (line 770459) — **ExpandTerrainLODStripBuffer** (medium confidence) — for each of
  `param_1` LOD-block entries, looks up a per-blocksize count from global table `DAT_1117a330`
  (the same lookup used by `FUN_1046e820` below) and replicates a 4-dword (likely quad/vertex) source
  record `iVar1+1` times into an output buffer — reads as expanding a compact per-LOD-block source
  table into a flattened strip/index buffer for rendering.
- `FUN_1046e820` (line 770510) — **BuildTerrainLODStripOffsets** (medium confidence) — walks a source
  list (`param_1+4` object, fields at +0x1c count / +0x20 array), and for each entry, writes a packed
  `(local_10,local_c)` two-`short` offset pair per output slot while advancing an accumulating offset
  by `iVar1+1` (or `iVar1*6+1` when a per-entry flag from `FUN_1008a4d0` is set) — looks like it's
  precomputing start-offsets into the strip buffer built by `FUN_1046e6a0`, with a `*6` jump for
  entries needing 2 extra "degenerate triangle" indices (a real technique for stitching triangle
  strips without restarting them) — consistent with terrain LOD strip generation.
- `FUN_1046e980` (line 770568) — **InitTerrainLODStripParams** — simple field-copy/setup function
  (copies count/array pointers from an inner object into a flat param block, sets a flag=1); likely
  called once per LOD-strip-build invocation to stage inputs for `FUN_1046e6a0`/`FUN_1046e820`.
- `FUN_1046e9d0` (line 770585) — **EmitTerrainStripVertex** (lower confidence) — writes one 6-float
  output vertex record (u/v-ish + 4 float fields) per call, driven by a wrap-around index computed mod
  a lookup-table value (`DAT_1117a348`), inside a loop bounded by `param_4+1`; shape is consistent with
  generating a fan/strip of vertices around a stitching junction, but exact semantics unconfirmed.
- `FUN_102f3050` (line 514780) — **RegisterVegetationZoneProperties** — one-time (guarded by
  `DAT_111eb6e4` flag) reflection-property registration: binds `"dataVersion"`, `"bboxMin"`,
  `"bboxMax"` fields plus a nested `"VegetationZoneData"` collection property (via `FUN_102f2e20`/
  `FUN_102f2e80`) into what looks like the property-table system also used by FCB serialization —
  confirms a real `VegetationZoneData` class with a bounding-box-keyed sub-zone list, independent
  corroboration for the vegetation-placement cluster documented separately below.
- `FUN_103c6970` (line 656216) — **ScriptBinding_CTerrain_GetInstance** — bound as the Lua/script
  `"GetInstance"` method for `"CTerrain"` (registration visible a few lines earlier at line 656612);
  checks 0 script args, then pushes the global `CTerrain` singleton pointer (`DAT_1121dfd4`) as an
  object-typed script return value.
- `FUN_103c6f80` (line 656526) — **ScriptBinding_CTerrain_GetSector** — the actual native
  implementation bound to Lua/script `"CTerrain"."GetSector"` (registered at line 656634 via
  `FUN_100de5f0("CTerrain","GetSector",&LAB_103c7020)`); validates 2 script args (an object + an int
  sector index), fetches the index via `FUN_100cc550`, calls a getter (`param_2`, passed in — likely
  the raw C++ `CTerrain::GetSector(int)` pointer) and pushes the result via `FUN_103c6920` below. This
  is the confirmed script-exposed entry point a level/mission Lua script would use to fetch a sector
  object by index — the earlier AGENTS.md note flagging this as "a Lua-style scripting registration,
  a dead end for byte-level structure" still holds (it's a thin binding shim, not sector-data logic),
  but it's now a fully traced, labeled call chain rather than a loose hit.
- `FUN_103c6920` (line 656197) — **ScriptPushObjectOrNil** — generic helper: if given a non-null
  pointer, boxes it as a script return value with type tag `DAT_1117c664`; otherwise pushes script
  `nil` (`FUN_100cc5d0`). Used by `ScriptBinding_CTerrain_GetSector` to return the fetched sector (or
  nil if out of range) to the calling script.
- `FUN_10ac0960` (line 1668186) — **CtorConsiderationVegetation** — sets up a log/category context
  tagged `"Vegetation"` (via `(*DAT_1100038c)("Vegetation")` + `FUN_10003590`) before delegating to
  `FUN_10acc170`; this address anchors a dense ~531-function cluster at `FUN_10ac0000`-`FUN_10adffff`
  that was initially suspected to be a vegetation/foliage placement subsystem — spot-checking
  `FUN_10ad1910` (a generic compiler-emitted float-to-int64 rounding helper unrelated to vegetation)
  raised doubt, and a full dedicated sweep of the whole cluster **falsified the hypothesis entirely**:
  `"Vegetation"` here just names one of seven sibling AI "consideration"/utility-scoring criteria
  (Vegetation, Grass, Occlusion, Stance, Speed, PawnSampling, AvatarSkill) used for stealth/behavior
  scoring, not a placement system. See the dedicated section below (**"AI Considerations /
  Local-Avoidance / Runtime Internals — cluster formerly hypothesized as 'Vegetation'"**) for the full
  corrected ~540-function breakdown — the only genuinely vegetation-relevant code found there is
  `FUN_10ac5fb0`/`ComputeVegetationCoverageScore`, a foliage-concealment *query* for stealth AI, not a
  scatter/instancing system. A true vegetation placement subsystem, if present in this DLL, was not
  located in this session — `RegisterVegetationZoneProperties`/`FUN_102f3050` (above) and the globals
  `DAT_11224e68`/`DAT_11234f50` are the best leads for a future pass.

---

## Math/Utility (background sweep)

Fast, shallow breadth sweep of Dunia engine decompile (`Avatar_Dunia_Retail_1.02_decrypted.dll_FULL_DECOMPILE.txt`, ~2.61M lines). Names are inferred from arithmetic shape / call patterns, not verified against real symbols. Sampling was done by grepping for float-heavy signatures, SQRT usage, known hash/crypto constants, and CRT-shaped loops, then skimming clusters.

### Vector/Matrix/Bounding-Volume Math (cluster near FUN_10013xxx-FUN_10019xxx)

- `FUN_10013600` (line 12318) — **AABBTranslateInPlace** — adds vec3 (param_2) to both min and max of a 6-float AABB (param_1[0..2]=min,[3..5]=max).
- `FUN_10013680` (line 12341) — **AABBTransformCorners6f** — runs a 3-float chunk through `FUN_10037240` (likely Vector3-by-matrix transform) twice to rebuild a 6-float AABB.
- `FUN_10013900` (line 12360) — **TransformVector3ByMatrixPartial** — thin wrapper: calls `FUN_10037090` (setup?) then `FUN_10037240` once and stores 3 floats out.
- `FUN_10013a30` (line 12380) — **Vector3AddInPlace** — `param_1 += param_2` on 3 floats, simplest add pattern.
- `FUN_10013a80` (line 12396) — **TransformAABBCorners4x3** — runs 4 separate 3-float chunks through `FUN_10037240` (transforms 4 box corners/axes by a matrix).
- `FUN_10013ba0` (line 12428) — **SphereContainsPointSIMD** — squared-distance-vs-radius² compare using `movmskps`, classic point-in-sphere test.
- `FUN_10013c60` (line 12454) — **SphereVsOBBOverlapSIMD** — SIMD compare of projected extents against radius on 3 axes; sphere/OBB style overlap test.
- `FUN_10013d60` (line 12492) — **SphereSphereIntersect** — squared-distance vs `(r1+r2)²` test with SIMD mask.
- `FUN_10017740` (line 15225) — **OBBOBBIntersectSAT** — classic separating-axis-theorem test between two oriented boxes (3 axis-projection compares + cross-axis compares).
- `FUN_10017a60` (line 15278) — **SegmentAABBIntersectSAT** — normalizes edge vectors with `SQRT`, cross-product axis tests against an AABB; segment-vs-box test.
- `FUN_10017d70` (line 15338) — **ClosestPointOnSegmentToPoint** — normalizes segment direction, projects a point onto it, clamps to segment length, writes projection.
- `FUN_10018120` (line 15376) — **SegmentPlaneIntersect** — ray/segment-vs-plane intersection with t-parameter clamp to [0,1], writes hit point.
- `FUN_10018320` (line 15410) — **ProjectPointOntoPlane** — `dot(point,plane)/|planeNormal|` then subtracts along normal; classic point→plane projection.
- `FUN_100183e0` (line 15439) — **AdjustPlaneOffsetForAABB** — recomputes a plane's D component against an AABB half-extent/center (frustum-plane fitting shape).
- `FUN_10018600` (line 15463) — **AABBOBBIntersectSAT** — mirror of `FUN_10017740` with operands swapped (AABB vs OBB SAT test).
- `FUN_100189e0` (line 15522) — **OBBOBBIntersectFullSAT** — very long 15-axis SAT test (3+3+9 cross axes), full OBB-vs-OBB intersection.
- `FUN_100192a0` (line 15630) — **SegmentSegmentClosestDistance** — SIMD (`sqrtps`/`divps`) closest-distance-between-two-segments/capsule test, writes distance to out param.
- `FUN_10019490` (line 15726) — capsule/OBB-style SIMD intersection test (didn't fully resolve); heavy `sqrtps` use consistent with capsule-vs-box distance test.
- `FUN_10033cb0` (line 32645) — **QuaternionRotateVector** — quaternion (xyzw, param_1) applied to vec3 (param_3) via the standard `q*v*q⁻¹` cross/dot expansion, writes rotated vec3 to param_2.
- `FUN_100376a0` (line 36038) — **Vector3LengthSquaredOrLength** — `SQRT(x*x+y*y+z*z)` shape (float10/extended precision), single-vec3-in.
- `FUN_10037700` (line 36055) — **Vector3Distance** — `SQRT` of squared component diffs between param_1 and param_2, vec3 distance.
- `FUN_10037240` (referenced heavily as a helper @ ~35774) — **Vector3TransformByMatrixHelper** — repeatedly used by the AABB/box transform functions above to transform a 3-float chunk; treat as the core Vector3×Matrix helper.

### Hashing / Checksums / Light Crypto

- `FUN_1000bbc0` (line 7229) — **TeaBlockEncrypt** — classic XTEA/TEA block cipher: 32-round Feistel loop with delta accumulator `0x9e3779b9`, XOR/shift mixing — this is TEA encrypt, not a hash.
- `FUN_1000bc30` (line 7258) — **TeaBlockDecrypt** — mirror of the above: 32-round loop starting `uVar1=0xc6ef3720` and subtracting `0x61c88647` per round (TEA decrypt sum unwind).
- `FUN_1000c050` (line 7354) — **HashBufferJenkinsLookup2** — Bob Jenkins' "lookup2"/`hashlittle`-style mixing hash: three 32-bit accumulators seeded `0x9e3779b9`, 12-byte block mix with the canonical shift/sub/xor "mix()" macro sequence, byte-count tail switch.
- `FUN_100f2720` (line 174346) — **HashStringFNV1a** — textbook 32-bit FNV-1a: `uVar3=0x811c9dc5; uVar3 = uVar3*0x1000193 ^ byte` per character. Distinct from the already-documented reflected-CRC32 FCB name hash.
- `FUN_100f2970` (line 174371) — **FormatMatrixToCSVString** — sprintf's 16 floats as `"%g,%g,...,%g"` (matrix/array-to-string serialization helper).
- Lines 189784 / 189832 (inside an unresolved-name function around 189760) — **StringHashMultiplier33** — inline string hash `hash = hash*0x21 + byte` (classic djb2-style ×33 hash) used to drive an open-addressing hash-table insert/lookup with linear probing and capacity doubling at 2× on collision-table growth; effectively a **HashMapStringInsertOrFind** container helper.
- `1792565` — note only: `hkCrc32StreamWriter::vftable` — a resolved Havok symbol name appears verbatim in the decompile (Havok physics is statically linked with partial RTTI/vtable names surviving), confirming a separate, already-named CRC32 stream writer class exists from Havok, not engine-authored.

### CRT Number↔String Conversion (String Utilities) — cluster near FUN_10033exx-FUN_10034xxx

- `FUN_10033ed0` (line 32684) — **Int64ToStringRadix** — 64-bit signed value → string in arbitrary radix (param_4), digit-by-digit divide/mod then reverse; matches MSVCRT `_i64toa` shape.
- `FUN_10033f80` (line 32742) — **UInt32ToStringRadix** — 32-bit unsigned → string, arbitrary radix; MSVCRT `_ultoa`-shape.
- `FUN_10034030` (line 32792) — **UInt64ToStringRadix** — 64-bit value (built via `CONCAT44`) divided with `__aulldvrm` (compiler helper for unsigned 64-bit div/mod), digit-by-digit → string.
- `FUN_10034120` (line 32847) — **DoubleToStringInternal** — full double→decimal-digits conversion using a big power-of-ten table (`DAT_111765f8` array), carries/rounding, builds mantissa digit array; MSVCRT `fcvt`/`ecvt`-style internal (Dragon-ish digit generator).
- `FUN_100343d0` (line 32992) — **Int64ToWideStringRadix** — wide-char (`short`/UTF-16 code unit) version of `FUN_10033ed0`.
- `FUN_100344b0` (line 33050) — **UInt32ToWideStringRadix** — wide-char version of `FUN_10033f80`.
- `FUN_10ad119e` (referenced repeatedly as the copy-out step in the above) — **CopyStringBytesWrapper** — thin wrapper used by all the above conversion routines to copy the built digit buffer into the caller's output buffer (memcpy-shaped helper).

### Memory / Allocation Wrappers

- `FUN_10ad1136` (line 1678705) — **MemCpyWrapper** — thin thunk: `(*DAT_110005ec)()`, i.e. tail-calls the imported CRT `memcpy` through an import-table pointer (Ghidra couldn't resolve the import name).
- `FUN_10ad113c` (line 1678718) — **MemSetWrapper** — thin thunk to imported CRT `memset` via `_DAT_110005e4`; used everywhere in the codebase as `FUN_10ad113c(dest, value, size)`.
- `FUN_10ad1142` (line 1678731) — **MemMoveOrMallocWrapper** — thin thunk to `_DAT_110005e0`, same shape as the two above; likely `memmove` or `malloc` import thunk (not disambiguated in this shallow pass).
- `FUN_100ee250` (line 170899) — **AllocateBufferSizeClassed** — allocator front-end: rounds requested size up to a power-of-two "size class" (`(param_1-1+param_2) & ~(param_2-1)`), tries a fast pooled path (`FUN_101033d0`/`FUN_10103b30`) for buckets ≤0x100, else falls through to a general allocator (`FUN_10103d90`) — classic small-object pool allocator wrapper.

### Container Helpers

- Function around line 189760 (unresolved name, uses `unaff_EDI` frame state) — **HashMapStringInsertOrFind** — open-addressing string-keyed hash map: computes ×33 string hash, probes linearly (`capacity-1 & hash`, decrementing on collision), resizes/rehashes to 2× capacity when full (`unaff_EDI[2] == unaff_EDI[3]`), reinserts all live entries — this single function bundles hash, lookup, insert, and rehash for a generic string→pointer table.

### More Vector/Matrix/Quaternion Math (second pass, scattered addresses)

- `FUN_1003d880` (line 42289) — **Vector3TransformByMatrix3x3** — transforms a vec3 by the rotation-only (3x3) part of a matrix, no translation added (normal/direction transform, not point transform).
- `FUN_1003d9b0` (line 42309) — **Vector3SetLength** — normalizes param_2 then scales to length `param_3`; returns zero vec4 (w=1) if input length is ~0.
- `FUN_1003ddf0` (line 42586) — **CartesianToSpherical** — converts an xyz-ish input to spherical/polar angles using an `atan2`-style wrapper (`FUN_10ad182a`) twice; output packed as (angle,0,angle).
- `FUN_1003df00` (line 42640) — **EulerAnglesToQuaternion** — computes half-angle sin/cos via `FUN_10ad1648`/`FUN_10ad164e` (sin/cos thunks) for 3 axes and combines into a quaternion xyzw.
- `FUN_1003e040` (line 42684) — **AxisAngleToMatrixColumn** — builds a matrix column/row pair from a single angle via sin/cos wrappers; helper used while building rotation matrices.
- `FUN_1003eaf0` (line 43162) — **Vector3NormalizeInPlace** — normalizes a 3-float vector in place, skips work if already unit length (`x²+y²+z²==1.0` fast-path).
- `FUN_1003ec00` (line 43181) — **RotateVector3ByQuaternionWrapper** — thin convenience wrapper that packs a vec3 into a temp vec4 (w=0) and calls `FUN_10033cb0` (`QuaternionRotateVector`).
- `FUN_1003ec90` (line 43210) — **GetLazyInitVector3Global** — returns a static global vec3 (`DAT_111b8d2c/30/34`), lazily zero-initializing it on first use (classic "default direction" singleton pattern).
- `FUN_10091990` (line 104873) — **Matrix4x4Multiply** — in-place 4x4×4x4 matrix multiply, full 16-term row×column dot-product expansion; very high confidence (classic unrolled matmul shape).
- `FUN_10084a60` (line 95851) — **Matrix4x4Invert** — full 4x4 matrix inversion via cofactor/adjugate expansion (12 cofactor terms) then divides all 16 elements by the determinant; very high confidence (matches classic unrolled D3DX-style inverse).
- `FUN_10085360` (line 95982) — **TransformPoint3ByMatrix4x4** — transforms a point by the 3x3 rotation part of a row-major 4x4 matrix plus the translation row (indices 12/13/14).
- `FUN_10085480` (line 96002) — **BuildScaleOrIdentityMatrix** — constructs a matrix from a couple of scalar globals (diagonal-heavy pattern); low confidence on exact semantics.
- `FUN_10085550` (line 96040) — **Vector4TransformByMatrix4x4** — full 4-component (xyzw) vector × 4x4 matrix transform.
- `FUN_100855b0` (line 96087) — **Matrix4x4Copy** — straight 16-float struct copy.
- `FUN_1013f3f0` (line 222915) — **QuaternionToMatrix4x4** — builds a 4x4 rotation matrix from a quaternion using the standard `1-2(y²+z²)`-style formula; high confidence.
- `FUN_10183c10` (line 268281) — **EulerAnglesToMatrix4x4WithTranslation** — builds a rotation matrix from 3 Euler angles (6 sin/cos wrapper calls) and stores a translation into column 12/13/14.
- `FUN_101b2130` (line 300708) — **AABBTransformByMatrix** — robust AABB-by-matrix transform (Arvo's method: splits each matrix row's positive/negative contributions into new min/max) — high confidence.
- `FUN_1086d890` (line 1359848) — **InverseLerpClamped** — computes `t=(x-edge0)/(edge1-edge0)` and clamps to [0,1]; classic "linearstep"/inverse-lerp utility.

### Random Number Generation

- `FUN_10f1a440` (line 2493479) — **RandomFloat01** — classic LCG PRNG: updates global seed `DAT_111b1f00 = seed*0x41c64e6d + 0x3039 (12345) & 0x7fffffff` (ANSI-C/glibc-style constants), then scales the seed to a `[0,1)` float via a normalization constant. High confidence.
- `FUN_10c36ea0` (line 1938100) — **RandomFloat01FromRegisterSeed** — identical LCG math to `FUN_10f1a440` but reads/writes the seed through an uninitialized/register-passed value (`in_EAX`) rather than the named global; likely an inlined duplicate of the same PRNG.
- Call site at line 1164888, `FUN_10101bb0(0x3039)` — a function invoked with the literal `12345`, consistent with **SeedRandomDefault** (seeding the LCG state with the classic default seed value); not independently confirmed by reading `FUN_10101bb0`'s body in this pass.

### Container Helpers (additional)

- `FUN_10091cb0` (line 104967) — **BinarySearchUint32Array** — classic binary search over a sorted uint32 array; returns the found index, or `~insertionIndex` (bitwise complement) if not found — standard sorted-array container helper.
- `FUN_10091d00` (line 104999) — **AllocateAndCopyVertexBuffer3f** — allocates two parallel buffers sized `count*0xc` (12 bytes = 3 floats) via `FUN_100ee250`, zeroes one with `FUN_10ad113c`, then bulk-copies from a source structure with `FUN_10ad119e`; a dynamic vec3-array construction helper.

### Quantization / Compression Helpers (numeric utility, network-adjacent)

- `FUN_1013f740` (line 223034) — **DecodeQuantizedPosition3D** — decodes a bit-packed fixed-point position (per-axis bit-width read from a struct, `1<<bits` range) back into a float triple; used near `CNetSimulationCameraMemento`, so likely a network position decompressor.
- `FUN_1013f8b0` (line 223122) — **DecodeQuantizedNormal** — decodes two packed angle values via `atan2`-style wrappers (`FUN_10ad1b4a`, `FUN_10ad182a`) back into a 3-component direction; spherical/octahedral-style normal decompression.

### Notes / Low-Confidence Leads Not Fully Resolved

- `FUN_10019490` (line 15726) — heavy SIMD (`sqrtps`) geometry test, shape consistent with capsule-vs-OBB or triangle distance test; not fully traced in this pass, name left generic.
- `FUN_101099a0` (line 189721) — returns a value later masked `& 0x3f` and used to seed a hash table bucket count; possibly a tick-count/PRNG seed source — worth a follow-up deep pass if RNG needs pinning down precisely.

---
## Audio (background sweep)

Scope note: The core sound engine lives in a contiguous compiled block roughly
0x10360000-0x1036f6d0 (decompile lines ~587776-599432), anchored by the one
function in the whole dump that Ghidra could demangle: `CSoundSystem::Initialize`
@ 0x103692b0 (line 594649), mangled `?Initialize@CSoundSystem@@UAEXABVCPlatformContext@@PAVISoundObjectCallbacks@@@Z`.
That function's body is the Rosetta stone for this sweep: it allocates/wires up
every sound sub-manager (mixing, reverb, sound lines/types, doppler/occlusion
channel strategy, operation-stats profiler) and is the anchor used to infer
most names below. No literal ".ogg"/"vorbis"/"Wwise"/"SoundDataID" string
constants exist anywhere in this DLL, and `CSoundManager`/`CSoundComponent`/
`CVoiceFxManager`/etc. (from avatar_class_hierarchy.tsv) resolve only to tiny
RTTI-getter thunks (`FUN_100016b0("CSoundManager",...)` stubs) — those are
mechanically covered elsewhere per instructions and are NOT relisted here.
Real gameplay-facing sound bank/asset loading appears to be handled by a
separate, non-decompiled audio engine (consistent with the ww2ogg/revorb
tooling shipping alongside the DLL rather than inside it) — the DLL's role is
config/XML orchestration (SoundConfig.xml, SoundRolloff.xml, SoundRegions.xml,
soundbank.xml, ReverbEchoLengthMap.xml), 3D positional/doppler/occlusion
channel setup, Lua script bindings, and mixing-preset control, not actual
codec/decoding work.

### Confirmed / high-confidence

- `CSoundSystem::Initialize` (line 594649, @ 0x103692b0) — already named by Ghidra (retained debug symbol). Central sound-engine bring-up: constructs op-stats profiler, sound-mixing manager, reverb map, sound-line/type reflection, loads SoundConfig.xml + SoundRolloff.xml, sets up per-channel doppler/occlusion strategy. Included here as the anchor for everything else in this file, not counted as a new label.

- `FUN_10369ae0` (line 595009) — **CSoundSystem_Shutdown** — mirror-image teardown of `CSoundSystem::Initialize`: releases every DAT_111ec8xx sub-manager pointer (mixing, reverb map, sound lines/types, op-stats) that Initialize allocated, then tears down CSoundResource/CPlatformContext registration. Highest confidence in the sweep.

- `FUN_103669b0` (line 593222) — **GetSoundSystemInstance** — trivial getter returning global singleton `DAT_111ec820`; this pointer is the `this` used throughout the module for vtable calls (channel count @ +0x74, doppler/occlusion tables @ +0x100/+0x10c/+0x11c/+0x120), i.e. CSoundSystem::GetInstance.

- `FUN_103669c0` (line 593232) — **DestroySoundSystemInstance** — calls vtable+0xf0 (destructor slot) on the singleton with `bDelete=1`, then nulls it.

- `FUN_1036f6d0` (line 599419) — **ParseSoundIdHexString** — if given a non-empty string, sscanf-parses it as `"0x%08X"` into a numeric sound ID (matches the SoundDataIDs.bin convention of hash IDs formatted as hex); otherwise returns the default/invalid ID sentinel `DAT_110555b4`. Used by the PlaySound/PlaySoundAtPosition Lua bindings to resolve a sound name argument to an ID.

- `FUN_1036f710` (line 599437) — **FormatSoundIdHexString** — inverse of the above: sprintf's a numeric ID back to `"0x%08X"`.

- `FUN_10365910` (line 592438) — **LoadSoundRolloffConfig** — opens `Databases\Generic\SoundRolloff.xml`, iterates a `"rolloffs"` node, building per-entry rolloff (distance attenuation) records.

- `FUN_10365ca0` (line 592616) — **LoadSoundProjectProfile** (CSoundSystem member) — resolves the active sound "profile" name, then loads `<bindir>/SoundInfo.xml` into `this+4`; also drives spline curve rebuild (`FUN_10365af0`) beforehand. thiscall on the CSoundSystem instance.

- `FUN_10365af0` (line 592526) — **MatchSoundPlatformResources** — compares a `"win32"` platform tag (via `FUN_10372560`) against the current platform id (`FUN_10b15d50`); on match, walks a linked list of resource records and registers each into a hashmap keyed by resource id (`FUN_1022c450`). Looks like per-platform sound-resource filtering during profile load.

- `FUN_10368d20` (line 594329) — **LoadSoundConfigXml** — parses `Config/SoundConfig.xml`, looks up the `"SoundProject"` node, reads its `"bindir"` attribute and `dopplerFactor`/`occfade`/`occmul_pc` numeric fields into the CSoundSystem instance.

- `FUN_10368a40` (line 594209) — **ConfigureSoundChannelStrategy** — reads `"positioning"`/`"occlusion"`/`"enhanced"` capability flags off a channel descriptor and builds per-channel function-pointer thunk tables (doppler/occlusion callback sets) written into `CSoundSystem+0x100/+0x10c/+0x11c/+0x120` arrays — i.e. per-voice-channel DSP/positioning behavior setup.

- `FUN_103663c0` (line 593036) — **ConstructSoundOperationStatsProfiler** — object constructor that registers the `snd_opstat` ("Size of the operation history to compute an average value") and `snd_oppeak` ("Duration in sec of the operation peak display") console variables. Matches `DAT_111ec81c = FUN_103663c0()` in CSoundSystem::Initialize.

- `FUN_1036cb70` (line 597464) — **ConstructSoundMixingManager** — object constructor; resizes internal per-voice arrays to the sound system's channel count (`FUN_103669b0()`+0x74), references string table `s_Databases_SoundMixing_...` (Databases/SoundMixing/ config path), and registers the Lua globals `StartSoundMixingFromLua`/`StopSoundMixingFromLua`. Matches `DAT_111ec874 = FUN_1036cb70()` in Initialize.

- `FUN_1036beb0` (line 596737) — **Lua_StartSoundMixingFromLua** — Lua-callable entry point registered under the name `"StartSoundMixingFromLua"`; validates 1 string arg then calls `FUN_1036bda0` (mix-preset start).

- `FUN_1036bf00` (line 596766) — **Lua_StopSoundMixingFromLua** — Lua-callable entry point registered under `"StopSoundMixingFromLua"`; validates 1 string arg then calls `FUN_1036be10` (mix-preset stop).

- `FUN_1036e820` (line 598703) — **LoadBaltazarReverbEchoLengthMap** — opens `Databases/baltazar/ReverbEchoLengthMap.xml`, walks a `"Reverbs"` node's `"Reverb"` children reading `sndReverb`/`echoLength` fields into a lookup map. Matches `DAT_111ec8c0 = FUN_1036f5c0()`-style sub-manager pattern (feeds the reverb-length lookup used elsewhere in Initialize).

- `FUN_1036e9f0` (line 598786) — **GetReverbEchoLength** — looks up a reverb-zone id in the map built by `FUN_1036e820` and returns its echo-length float (or 0 if not found).

- `FUN_10367aa0` (line 593817) — **RegisterSndSoundIdReflectionField** — one-shot reflection/serialization registration of a field named `"sndSoundId"` (typical `DAT_..._once` init-guard + `FUN_100ee250` allocator + `FUN_100b6b90` field-list append pattern seen throughout the reflection system).

- `FUN_102a63d0` (line 462100) — **LoadBaltazarSoundBankConfig** — opens `Databases/baltazar/soundbank.xml`, checks for a `"BtzSoundBanks"` node, then iterates `"WorldBank"` entries each containing nested `"MapBank"` entries — i.e. loads the world/map sound-bank manifest (ties to `CFCXGameSoundService`/`CDominoSoundManager`-era Baltazar sound-bank system, TSV line 460).

- `FUN_102c9a70` (line 485982) — **ValidateSoundRegionsConfig** — loads `SoundRegions.xml` (via generic schema-load-and-verify helper `FUN_100fe100`) and returns a bool success flag; part of `CSoundRegion`/`SoundRegions` reflection registration (see string `"SoundRegions"` also registered as a reflection array type at line 485960, `FUN_102c26e0(0x14,"SoundRegions","SoundRegion",...)`).

### Lua script-binding layer for sound (registered in `FUN_102bd810`, line 594649-adjacent block @ 0x102bd340-family, actually 0x102bd7b0-0x102bd810)

- `FUN_102bd810` (line 478593) — **RegisterSoundLuaBindings** — registers the three core Lua-exposed sound entry points: `"PlaySound"` -> FUN_102bd690, `"PlaySoundAtPosition"` -> FUN_102bd5a0, `"StopSound"` -> LAB_102bd3c0.

- `FUN_102bd7b0` (line 478568) — **RegisterGlobalLuaFunction** — generic helper used by RegisterSoundLuaBindings (and other systems) to register one named C callback as a global Lua function; not sound-specific by itself but is the mechanism the sound bindings above go through.

- `FUN_102bd510` (line 478461) — **RegisterSoundLuaType** — registers the Lua-exposed `"Sound"` handle/wrapper type and defines the `SOUND_HANDLE_INVALID` Lua constant.

- `FUN_102bd5a0` (line 478479) — **Lua_PlaySoundAtPosition** — implementation of the `PlaySoundAtPosition(name, position, entity)` Lua call: validates 3 args (string, vector, entity), resolves the sound name to an id via `FUN_1036f6d0`, and dispatches through the CSoundSystem singleton's vtable+0x98 slot.

- `FUN_102bd690` (line 478524) — **Lua_PlaySound** — implementation of the `PlaySound(name, ?, entity)` Lua call: validates 3 args, looks up a script-entity wrapper (`FUN_102bd4d0`), resolves the sound id (`FUN_1036f6d0`), and plays it on the entity's sound component.

### On-disk sound package format (`.spk`) + resource resolution

- `FUN_1036a670` (line 595546) — **BuildSoundPackagePath** — builds the on-disk path to a sound-package file using `sprintf("%s%08x.spk", dir, id)` (or `"%s%s\\%08x.spk"` with a subfolder when bit 0x40000000 of the id is set). Confirms the real runtime sound container format is a proprietary `.spk` package keyed by a 32-bit hash id — not raw `.ogg` (those are pre-processed into packages at build time; explains why no `.ogg`/`vorbis` string literals exist in this DLL despite `ww2ogg.exe`/`revorb.exe` shipping alongside it).

- `FUN_1036a720` (line 595597) — **ParseSoundPackageHeader** — validates a loaded `.spk` buffer: checks a magic number `0x53504b01` ("SPK" + version byte 1) at the start of the buffer, then wires up pointers to the package's entry-count and entry table. This is the on-disk sound-package header parser.

- `FUN_1036a6f0` (line 595578) — **ReleaseSoundPackageEntries** — iterates a package's entry array and calls vtable+0x3c (release/unload) on each entry object.

- `FUN_1036a7f0` (line 595646) — **ResolveSoundResourceHandle** — turns a sound resource id into a cached, refcounted resource object: builds the `.spk` path (`FUN_1036a670`), looks it up/loads it into the resource cache (`FUN_100f1f30`), then acquires a ref (`FUN_1036a7a0`). Used throughout the module (rolloff/platform resource matching, managed-sound playback, sound-instance update) to go from id -> loaded resource.

- `FUN_1036a870` (line 595673) — **RegisterSoundResourceInBank** — resolves a resource handle (`FUN_1036a7f0`) then calls vtable+0x68 on a bank/manager object to register it; used by the platform-resource-matching loop.

- `FUN_10372560` (line 601651) — **LogSoundDependency** — appends a `"*DEP* "`-tagged line to a per-platform `sound_dep.log` file (path built as `"_<platform>\\<snddir><logname>"`). A build-time dependency-tracking hook, called with the literal `"win32"` platform tag from `FUN_10365af0`.

### Managed/tracked sound-instance playback

- `FUN_1036fac0` (line 599580) — **DispatchPlaySound** — core native PlaySound path used by both the Lua PlaySoundAtPosition binding and other callers: if no source-object id is given, plays directly by resource id via CSoundSystem vtable+0x98; otherwise resolves the object's resource handle (`FUN_1036a7f0`) first.

- `FUN_10370bd0` (line 600175) — **UpdateManagedSoundInstance** — per-frame(ish) update for a tracked/managed sound handle: checks CSoundSystem vtable+0xbc ("is still playing"), advances a fade timer, and re-triggers playback via vtable+0x98/+0x94 when needed (loop/retrigger logic for a managed sound slot).

- `FUN_10370ba0` (line 600155) — **FindManagedSoundById** — linear-scans a linked list (walking a `+0x15`-index "next" field) of managed sound entries for one matching an id.

- `FUN_10372640` (line 601731) — **PruneStoppedManagedSounds** — walks a linked list of managed sound handles, queries CSoundSystem vtable+0xbc ("is playing") per entry, and unlinks/releases (vtable+0(1) destructor call) any that have finished.

- `FUN_103729b0` (line 601960) — **PlayTrackedSound** — resolves a resource handle (`FUN_1036a7f0`), allocates a small tracking node, plays it through CSoundSystem vtable+0x94, and links the node into an owner's managed-sound list (paired with `FUN_10370ba0`/`FUN_10372640` for lookup/pruning).

### Sub-manager constructors wired up in `CSoundSystem::Initialize`

- `FUN_1036cb70` (line 597464) — see above, **ConstructSoundMixingManager**.
- `FUN_1036f5c0` (line 599349) — **ConstructSoundReverbZoneManager** — constructor for the `DAT_111ec8c0` sub-manager (paired with `FUN_1036f520` destructor below); initializes default float params to `1.0`/id fields to the invalid sentinel and an internal red-black tree (zone lookup table), consistent with the reverb-zone/echo-length system fed by `FUN_1036e820`/`FUN_1036e9f0`.
- `FUN_1036f520` (line 599310) — **DestructSoundReverbZoneManager** — destructor mirroring the constructor above; unregisters a callback (`FUN_1036dac0`) and tears down the zone tree.
- `FUN_10370450` (line 599952) — **ConstructSoundEffectParamSetManager** — constructor for `DAT_111ec8e8`; registers a callback and initializes from `DAT_111ec8f0`/`DAT_1101d3ec`. Paired with the reflection registration below.
- `FUN_10370550` (line 599969) — **RegisterSoundEffectParamSetReflection** — one-shot registration of the `EffectParams`/`ParamSetName`/`selEffectType` reflection fields and an `enumEffectType` enum whose values include `"Invalid"` and `"Reverb"` — i.e. the schema for per-zone sound DSP effect parameter sets (reverb effect params in particular).
- `FUN_10370b80` (line 600142) — **ConstructActiveSoundEffectList** — trivial constructor for `DAT_111ec948`, the list managed by `FUN_10370ba0`/`FUN_10372640` (active per-zone sound-effect instance tracking, prune-on-stop).
- `FUN_10372600` (line 601696) — **ConstructSoundManagedHandleList** — constructor for `DAT_111ec950`, a small linked-list head object (paired with destructor `FUN_10372610` immediately below it, which walks and releases every node via vtable slot 0).
- `FUN_10372610` (line 601708) — **DestructSoundManagedHandleList** — destructor pairing `FUN_10372600`; releases every linked node.
- `FUN_103729a0` (line 601948) — **ConstructTrackedSoundList** — constructor for `DAT_111ec954`, the owner-side list populated by `FUN_103729b0`/`PlayTrackedSound`.

### CSoundEvent / CDialogEvent / entity sound-message plumbing (0x10237xxx / 0x1025axxx)

- `FUN_1025a410` (line 414736) — **PlayEntitySoundAndStoreHandle** — plays a sound positioned at an entity offset (`param_1+0x14`) through the CSoundSystem singleton (vtable+0xb0) and clears the stored-handle field (`param_1+0x44`) back to the invalid sentinel; the play-side counterpart of `FUN_1025a440` below. Likely a CSoundEvent/CDialogEvent method.

- `FUN_1025a440` (line 414751) — **StopEntitySoundHandle** — if the entity's stored sound handle (`param_1+0x44`) isn't the invalid sentinel, stops it via CSoundSystem vtable+0xa0 and resets the field. Pairs with `FUN_1025a410`.

- `FUN_1025ab60` (line 414846) — **ConstructSoundEvent** — object constructor that stamps the type name `"SoundEvent"` into the new instance (matches `CSoundEvent`, TSV line 1073) before initializing its remaining fields to defaults (invalid ids, zeroed flags).

- `FUN_1025b070` (line 414992) — **RegisterSoundAndDialogEventTypes** — builds two named event-type name objects, `"PlaySound"` and `"PlayDialog"` (via `FUN_1025ac00`), and registers each with an event-type registry (`FUN_102aa230`) — the two entity-event kinds that drive `FUN_1025a410`/`FUN_1025a440`-style playback.

- `FUN_10237ea0` (line 393740) — **ApplySoundCategoryMuteMask** — iterates a bit-array of sound categories/switches (`param_1+0x44`/`+0x48`) and, for each set entry, calls CSoundSystem vtable+0x70 or +0x6c (selected by a bool param) — looks like a bulk mute/unmute-by-category operation, likely part of `CGameSoundMessage`/`CGameSoundSequenceMessage` handling (TSV lines 680-681, same 0x10237xxx neighborhood).

### Baltazar-era CDominoSoundManager (Lua-scriptable sound facade, 0x10217xxx-0x10218xxx)

- `FUN_10218030` (line 372637) — **RegisterCDominoSoundManagerClass** — one-shot class registration: names the Lua/RTTI type `"CDominoSoundManager"`, binds a `"GetInstance"` singleton accessor, binds a `"PlaySound"` method (`LAB_10218010`), and registers a `"Sounds"`/`"Sound"` reflection array — i.e. wires up `CDominoSoundManager` as a script-visible sound-effects facade (predecessor/alternate to the CSoundSystem Lua bindings above; "Baltazar" was Avatar's internal codename, per the `Databases/baltazar/...` paths seen elsewhere in this sweep).

- `FUN_10217e30` (line 372529) — **RegisterDominoSoundManagerMetatable** — registers the `CDominoSoundManager` Lua metatable and its `gettable_event`/`gettable` hook, routing property/method lookups through `FUN_10217eb0`.

- `FUN_10217eb0` (line 372552) — **DominoSoundManagerLuaCallThunk** — generic Lua->native call-marshalling trampoline validating a fixed 7-argument call shape before invoking the bound native callback; the mechanism `PlaySound` (and friends) go through when called from Lua on `CDominoSoundManager`.

- `FUN_10217790` (line 372254) — **ConstructDominoSoundManagerMethodDesc** — small constructor building a bound-method descriptor record (name + owner + argument name strings) used when registering `CDominoSoundManager`'s scripted methods.

### Notes on lower-confidence / generic helpers encountered

- `FUN_1036a7a0` (line 595622) — generic refcounted resource-cache acquire helper (hashmap get-or-insert + addref pattern reused across many non-audio systems too); only included here because it's the inner step of `ResolveSoundResourceHandle`. Not audio-specific by itself.
- `FUN_10369820`, `FUN_10369960`, `FUN_10369a20`, `FUN_10369cd0`, `FUN_10369d30` (lines 594831-595200ish) — red-black-tree/map erase-insert helper functions operating on the sound module's internal id-keyed containers (likely the `SoundLines`/`SoundTypes` maps set up in `CSoundSystem::Initialize`). These are templated STL-style container internals with no audio-specific logic of their own, so left unlabeled individually — flagged here so a future pass can match them to the specific `map<int,T>` instantiation if needed.
- The large block of Hermite/TCB-spline math functions immediately preceding the sound module (`FUN_10360150`..`FUN_10360db0`ish, lines 587776-588520, operating on 0xc0-byte-stride keyframe structs) was initially suspected to be the SoundRolloff distance-attenuation curve evaluator (it sits directly before `SoundRolloff.xml`/`SoundInfo.xml` loading code in the same compiled block), but at least one function in the middle of that range (`FUN_103614e0`, line 588526) reads `"BlendType"`/`"texture"` fields, proving the curve evaluator is a **shared/generic** spline utility also used by material/decal blending — not sound-specific. Deliberately left unlabeled rather than mislabeling as audio.

---

### Summary

~49 functions labeled. The picture that emerges: this DLL implements `CSoundSystem` as a thin **orchestration layer** — XML config loading (SoundConfig.xml, SoundRolloff.xml, SoundRegions.xml, ReverbEchoLengthMap.xml, baltazar/soundbank.xml), 3D positional/doppler/occlusion channel setup, a reverb-zone and DSP-effect-parameter-set manager, a sound-mixing-preset manager, managed/tracked sound-instance bookkeeping (play/update/prune), and Lua script bindings (`PlaySound`, `PlaySoundAtPosition`, `StopSound`, `Start/StopSoundMixingFromLua`, plus an older `CDominoSoundManager` Lua facade) — all delegating actual audio decode/mix/output to an external engine through a small, consistent vtable interface on the `CSoundSystem` singleton (slots +0x94/+0x98 play, +0xa0 stop, +0xbc is-playing, +0xb0 play-at-position, +0x6c/+0x70 mute/unmute, +0x74 channel count, +0x20 base sound directory). The actual runtime sound container format was recovered directly from string evidence: a proprietary `.spk` package (magic `0x53504b01` = "SPK"+v1) addressed by 32-bit hash id, built from `SoundDataIDs.bin`/vorbis-decoded assets at content-build time (explaining why no `.ogg`/`vorbis`/`Wwise` string literals exist anywhere in this DLL despite `ww2ogg.exe`/`revorb.exe` shipping in `tools/`).


---

## Asset Loading (FCB/XBT) and World/Level XML/Resource (background sweep)

Scope: beyond already-documented FUN_10111af0/FUN_10112430 (FCB reader/writer), XBT parser,
tools/avatar_class_hierarchy.tsv RTTI getters, and terrain functions (InitTerrainSystem etc).
This file covers resource managers, archive/file loading, CResource/CMetaSector/CWorldSector
member functions, world/level XML parsing, sector streaming, entity spawning, name hashing.

### Sector Descriptor Parsing (attribute-flag builder, ~0x100ecxxx-0x100edxxx cluster)

- `FUN_100ed410` (line 170399... actually 170141 header/170143 body) — **ParseSectorDescriptorFlags** — iterates a sector list (vtable+0x14 count / +0x18 getAt), reads boolean attrs `SectorId`(as int, vtable+0x11c), `HasNavMesh`, `HasDescriptor`, `HasMainSectorData`, `HasLandmarkNear`, `HasLandmarkFar` (all via vtable+0x130 bool getter), `isSectorAccessible` (inverted: false→flag set), and int attr `DetailMask` (vtable+0x11c) — packs them into a single bitfield byte per sector, matches AGENTS.md-documented worldsector descriptor attribute names exactly.
- `FUN_100ece60` (line 169887) — **ParseSectorGridOffset** — reads `OffsetX`/`OffsetY` float attrs into sector struct offsets +0x10c/+0x110, then probes `SectorCountX`/`SectorCountY` and calls FUN_100ca0c0 to size the grid.
- `FUN_100ecfa0` (line 169953) — **FindOrInsertSectorDescriptorEntry** — tree/map find (FUN_101a96e0) by key; on miss constructs a new node via FUN_103efbf0 (map insert) and returns `param_2+3` (payload pointer past key).
- `FUN_100eca10` (line 169699) — **ResolveSectorDataSubpath** — builds a working string, finds `.` via FUN_100a7820, then byte-compares two path/extension strings; branches on equality — likely selects preload vs. main sector data file variant.
- `FUN_100ed040` (line 169984) — **SectorDescriptorResource_Destructor** — frees ~6 dynamic string members (each guarded by `>0xf`→heap free pattern typical of small-string-optimization CStrings) then resets vtable to `&DAT_1101a198` (base class vtable, i.e. this is a "downgrade to base" destructor pattern).
- `FUN_100ed220` (line 170058) — **SectorDescriptorResource_Constructor** — sets vtable to `&DAT_1101d364`, default-constructs ~6 CString members, registers with `&DAT_11010a5c` refcount table via FUN_10003590.
- `FUN_100ed3f0` (line 170129) — **SectorDescriptorResource_ScalarDeletingDestructor** — calls destructor FUN_100ed040, then conditionally frees `this` if low bit of param_2 set (standard MSVC `scalar deleting destructor` thunk pattern).

### String/Name Hashing (CRC-32 family, used for asset lookup)

- `FUN_101031c0` (line 185772) — **ComputeCRC32Buffer** — standard reflected CRC-32 over `(byte*, int length)` using table `DAT_1117a7f0`; seed `0xffffffff`, final `~result`. Confirms AGENTS.md note that FCB name hashing is reflected CRC-32.
- `FUN_10103200` (line 185789) — **ComputeCRC32BufferSeeded** — same table-driven CRC-32 but takes an explicit running seed `param_1` (not hardcoded `0xffffffff`) — used to hash across multiple buffer chunks incrementally (e.g. path segments).
- `FUN_10103240` (line 185804) — **ComputeCRC32String** — case-sensitive null-terminated string CRC-32, same table `DAT_1117a7f0`. This is the core asset-name → hash function used throughout FCB/resource lookups.
- `FUN_10103270` (line 185826) — thunk to `FUN_101031c0` — skip (pure thunk), not separately labeled.
- `FUN_10103280` (line 185837) — **ComputeCRC32StringCI** — case-insensitive variant: runs each char through function pointer `DAT_11000468` (a case-folding callback, presumably `toupper`/`tolower`) before folding into the same CRC-32 table. Matches AGENTS.md's "case-insensitive lowercase variant" note.
- `FUN_100ed6a0` (line 170274) — **ComputeResourceNameHash** — wrapper: if `param_2` is a non-empty string, dispatches to `FUN_10103280` (case-insensitive, when `param_3!=0`) or `FUN_10103240` (case-sensitive) and stores the hash in `*param_1`; empty/null string produces sentinel `0xffffffff`. This is the actual entry point resource-lookup code calls to turn a class/asset name into a lookup key.

### CResourceContainer child management (0x100aeXXX-0x100afXXX cluster)

- `FUN_100aebf0` (line 123516) — **NotifyChildrenUnloaded** — if container state == 1 (loaded), calls vtable+0xc ("OnUnload"-style callback) on every child resource.
- `FUN_100aeca0` (line 123535) — **RemoveChildResourceByTypeId** — reverse-iterates children array, compares each child's runtime type hash (vtable+4 → typeinfo, offset+4 dword) against `*param_2`, calls vtable+0x6c (remove) on matches.
- `FUN_100aecf0` (line 123557) — **UnloadResourceContainerChildren** — iterates children (vtable+0xb0 count / +0xb4 get-at), releases/unloads each via refcount decrement pattern, calling vtable dtor at refcount 0.
- `FUN_100aeed0` (line 123607) — **SerializeResourceContainerHeader** — writes `"nbChildren"` (vtable+300 setter) and reads `"nbChildrenLoaded"` (vtable+0x130 bool/int getter) attrs; for each child converts its type-hash to a base-10 string (`DAT_11000608`, itoa-style) and calls vtable+0x9c/+0x2c — this is the XML(-like) header (de)serialization for a resource container's child list, i.e. the sector/world XML `<object>` child-count bookkeeping.
- `FUN_100af0b0` (line 123658) — **ResourceContainer_InitFields** — zeroes child-array/count fields (offsets 0x28-0x34) as part of construction.
- `FUN_100af140` (line 123708) — **DetachChildResource** — decrements loaded-count if child reports loaded (vtable+0x20), calls unload (vtable+0xc)/cleanup (vtable+0x48) callbacks, releases refcount, and if this was the last live child of a container-type resource, calls further container-level unload hooks (vtable+0x78).
- `FUN_100af210` (line 123752) — **RemoveChildResourceByPointer** — linear-searches children array for `param_2`, calls `FUN_100af140`/DetachChildResource on match.
- `FUN_100af260` (line 123784) — **RemoveAllChildResources** — pops children off the back of the array via `FUN_100af140` until count is zero.
- `FUN_100af290` (line 123801) — **AttachChildResource** — checks child not already present in container, increments container's loaded-child counter, invokes load callbacks (vtable+8/+0x44), appends to dynamic array (`FUN_10a44270` push_back), calls `FUN_10439510` (index rebuild), and propagates loaded-state up (vtable+0x74) if needed.
- `FUN_100af360` (line 123847) — **BroadcastEventToChildren** — if container's "ready" flag (checked via `FUN_10185960`) is set, calls vtable+0x4c(param_2) on every child — generic event/message broadcast to all children of a resource container (used e.g. for sector-wide notifications).
- `FUN_100af3b0` (line 123870) — **ResourceContainer_Destructor** — resets vtable to base `CResource` (`&DAT_110198f8`), detaches all remaining children via `FUN_100af140` loop, then calls base cleanup.
- `FUN_100af6a0` (line 124019) — **CountChildrenByTypeId** — walks a linked list (offset 0x48), matches each node's runtime-type hash against `*param_2`, optionally collects matches into an output array (`param_3`), and returns total-count/loaded-count via `param_4`/`param_5` — used for e.g. "how many CSectorEntity children are loaded" queries.
- `FUN_100af770` (line 124063) — **ResourceRegistryEntry_Construct** — default-constructs a registry/map entry (CString key + zeroed value slot).
- `FUN_100af820` (line 124107) — **FindResourceClassByHash** — looks up a class-registry map entry by hash (`FUN_10892830`), returns the found class descriptor's field+0xc or 0 if not found (miss sentinel = `*(int*)(param_1+0x48)`, i.e. map end iterator).
- `FUN_100af860` (line 124127) — **ResourceClassRegistry_Destructor** — frees two dynamic buffers (offsets 0x1b/0x1c, each `FUN_100af5c0`-typed pooled blocks) plus a CString member, resets vtable.
- `FUN_100af930` (line 124169) — **CreateResourceEntryByHash** — early-outs if hash equals sentinel `DAT_1101d63c`; otherwise invokes a factory callback (vtable+4 on member at param_1+0xc) to construct a new resource-class entry, stamps its type hash at offset+0x1c, and registers it into two lookup structures via `FUN_100c0200` (called twice — likely both a hash-map insert and a linked-list insert).
- `FUN_100afac0` (line 124270) — **FindOrCreateResourceClassEntry** — looks up hash in map (`FUN_10892830`); on miss falls back to `FUN_100af930`/CreateResourceEntryByHash to construct it, then increments the entry's refcount.
- `FUN_100afb20` (line 124300) — **ResolveOrCreateNamedResourceClass** — given a type descriptor, checks its vtable+0x1c flag against `DAT_110199ac`; if set, reads its class name (vtable+0xc), hashes it via `FUN_100ed6a0`/ComputeResourceNameHash, and resolves it through `FUN_100afac0` — this is the core "look up (or lazily register) a resource class by name" path used by the FCB/XML deserializer when instantiating typed objects (e.g. `<object name="Entity">`).
- `FUN_100af9c0` (line 124194) — **ResourceClassRegistry_Constructor** — sets vtable `&DAT_110199a8`, allocates two 0x30-byte pooled record blocks (offsets 0x1b/0x1c) zero-initialized to 12 dwords each — paired allocation table for class-registry bookkeeping (mirrors `FUN_100af860` destructor).
- `FUN_100afaa0` (line 124256) — **ResourceClassRegistry_ScalarDeletingDestructor** — standard MSVC scalar-deleting-destructor thunk wrapping `FUN_100af860`.

### CArchiveFile — .fat/.dat container decompression thread (0x100c1dXX-0x100c21XX)

- `FUN_100c1d80` (line 138180) — **CastToArchiveFile** — dynamic_cast-style downcast helper: verifies vtable type-info array length and type-id `DAT_111ca800` match before returning `param_1`, else NULL.
- `FUN_100c1dc0` (line 138201) — **ArchiveFile_Constructor** — constructs `CArchiveFile`; spawns a worker thread literally named `"DecompressionThread"` (`FUN_10034fb0`) and allocates a `0x4000`-byte staging buffer — this is the archive (.fat/.dat) background decompression subsystem.
- `FUN_100c1e50` (line 138232) — **ArchiveFile_Destructor** — frees the decompression staging buffer, tears down the worker thread, unwinds two vtable stages.
- `FUN_100c1ea0` (line 138252) — **DecompressionThreadWorker** — pops one pending I/O job from a queue (`FUN_100f9a80`), downcasts it to `CArchiveFile` via `FUN_100c1d80`, streams compressed chunks (size `DAT_1117a7c8`) through a decompressor (`FUN_100fff60`) into the destination buffer, marks the job status `0xfffffffe` on failure/type-mismatch, then advances the queue (`FUN_100f98e0`). Core async-decompress-on-load path for archive-packed assets.
- `FUN_100c2080` (line 138348) — **DecompressionThreadMain** — thread entry point looping `FUN_100c1ea0` until the archive's stop flag (`param_1+0xe0`) is set.
- `FUN_100c2140` (line 138391) — **ArchiveFile_ReleaseChildHandle** — if a sub-resource handle (offset 0x16) is open, closes it (vtable+0x6c), detaches all children (`FUN_100af260`), releases it (vtable+0x68).

### CResourceNotifier / CResourceWatch — load/unload listener system (0x100c22XX-0x100c28XX)

- `FUN_100c2170` (line 138406) — **ResourceNotifier_MarkListenerInactive** — clears an active-listener flag, calls vtable+0x58(1) on target (deactivation callback).
- `FUN_100c2190` (line 138420) — **ResourceNotifier_MarkListenerActive** — sets active-listener flag, calls vtable+0x58(0) (activation callback).
- `FUN_100c2200` (line 138452) — **ResourceNotifier_HasPendingListeners** — returns whether combined listener-array size is non-zero.
- `FUN_100c2280` (line 138462) — **ResourceNotifier_MarkListenerDead** — scans both the load-listener and unload-listener arrays for `param_2`, flags the matching (still-live) entry dead.
- `FUN_100c2300` (line 138488) — **ResourceNotifier_InitFields** — base init: calls `FUN_100af0b0`/ResourceContainer_InitFields, zeroes two listener-array descriptors, defaults an "isReady" flag to true.
- `FUN_100c2360` (line 138523) — **ResourceNotifier_Destructor** — marks all listeners dead (`FUN_100c2280`), frees the two dynamic listener arrays, chains to `FUN_100af3b0`/ResourceContainer_Destructor.
- `FUN_100c23f0` (line 138538) — **ResourceWatchEntry_Construct** — zero-init small watch-pair struct.
- `FUN_100c2410` (line 138556) — **ResourceWatchEntry_Destructor** — frees the watch-pair's two dynamic arrays.
- `FUN_100c2480` (line 138569) — **ResourceNotifier_FireLoadUnloadCallbacks** — dual-pass: iterates the "load pending" array calling each live listener's vtable+4 (load-complete callback), then the "unload pending" array likewise, compacting each array afterward via `FUN_100ed7d0`. This is the tick/pump function that turns queued resource-load-completion events into listener callbacks.
- `FUN_100c2610` (line 138637) — **ResourceWatch_Constructor** — builds `CResourceWatch` (derives `CResourceNotifier` per class hierarchy TSV): base-inits, allocates an internal `IFile`-typed observer object (size 0x2c), attaches it as a child via `FUN_100af290`/AttachChildResource, and fires an initial load callback if not already fired.
- `FUN_100c26d0` (line 138679) — **ResourceWatch_Destructor** — detaches and releases the internal observer child (refcounted release + vtable dtor at zero), then chains to `FUN_100c2360`/ResourceNotifier_Destructor.
- `FUN_100c27a0` (line 138735) — **ResourceNotifier_RegisterLoadUnloadListener** — appends a load-listener and/or unload-listener descriptor into the pending arrays (`FUN_101f7960` push_back), then if the resource already reports loaded (vtable+0x20), immediately invokes the load callback (vtable+4) rather than waiting for the next pump — subscribe-with-immediate-fire-if-ready semantics.
- `FUN_100c2860` (line 138782) — **ResourceNotifier_RemoveListener** — finds a listener by pointer in the array and deactivates it (`FUN_10195ad0`), else falls back to scanning the target's own reverse-listener list.

### CXmlResource (0x100c2a90 cluster)

- `FUN_100c2e00` (line 139072) — **XmlResource_Constructor** — default-constructs `CXmlResource` (vtable `&DAT_1101a8cc`); sets several bool flags true, initializes a locale/string field to the literal `"english"` — this is the resource's default-language field, confirming localized XML text resources default to English.
- `FUN_100c2d60` (line 139029) — **XmlResource_Destructor** — frees two dynamic CString members, chains to `FUN_100c2b50` (global-resource-registry teardown helper).
- `FUN_100c2de0` (line 139058) — **XmlResource_ScalarDeletingDestructor** — MSVC thunk wrapping `FUN_100c2d60`.
- `FUN_100c2b50` (line 138936) — **ReleaseXmlResourceGlobalRegistry** — teardown routine releasing ~20 global singleton resource-registry pointers (`DAT_111ca...` refcounted class-registry entries) — called from engine shutdown, releases XML/Binary resource default-instance registries.
- `FUN_100c2ed0` (line 139121) — **XmlResource_InitLocalizationPaths** — copies a 6-field descriptor (probably a sound-bank/localization descriptor struct) into `this`, lazily allocates a global `0x10`-byte localization table (`DAT_111ca4ec`) on first use, and builds string members with defaults `"sound_"` prefix — localized sound-bank path resolution tied into XML resource loading.

### Entity spawning / reflected field registration

- `FUN_101e3f40` (line 338757) — **RegisterEntityBaseFieldDescriptors** — one-time init (guarded by `DAT_111e7310`) registering `CEntity`'s reflected base fields into a global descriptor table `DAT_111e7314`: `hidName` (CString, size 0x18), `disEntityId` (Id64, accessor `FUN_101e3db0`), `hidEntityClass` (accessor `FUN_1058a800`). This is the reflection table the FCB/XML serializer walks to emit/parse `<field name="hidName">`/`<field name="disEntityId">` — the exact tag names `simplified_map_editor.py` already parses from FCBConverter XML.
- `FUN_101e3db0` (line 338652) — **GetEntityDisEntityId** — reflected-field accessor, returns the 8-byte `disEntityId` at `this+0x10`.
- `FUN_101e3dc0` (line 338662) — **SerializeReflectedFieldGeneric** — generic reflected-field write helper: calls a getter (vtable+0x18) then a field-writer callback (vtable+0x5c).
- `FUN_101e3df0` (line 338676) — **SetReflectedField64** — generic reflected-field setter storing an 8-byte value with refcounted swap-out of the old value.
- `FUN_101e3eb0` (line 338715) — **CopyReflectedField64** — copies an 8-byte field value from a global source into this field slot with refcount bookkeeping (used for default-value fields like `hidName`'s empty string).
- `FUN_102b22b0` (line 471148) — **SpawnDynamicEntityFromTemplate** — large runtime-entity-spawn routine keyed by mode `param_3` (0/1/2). Mode 1 constructs a fresh entity handle and calls into the reflection setter API (vtable+0x98/+0x8c/+0x100/+0x154-style calls) to stamp `disEntityId`, `hidName`, `hidPos_precise`, optionally `tplCreatureType` (when a template-creature flag at `+0x92` bit0 is set), then resolves `CMissionComponent`'s "Components" child and attaches it — this is the engine's runtime entity-instantiation path (e.g. AI/creature spawners creating a live entity from a template resource), distinct from the static FCB-file sector load path.

### World Load Operation state machine (CFCXLoadWorldOp cluster, 0x106d7xxx)

- `FUN_106d7180` (line 1119786) — **FCXLoadWorldOp_Destructor** — releases a stored callback pointer (calls its vtable+0/dtor), frees two dynamic member arrays, chains to `FUN_106d6890`/`FUN_10769d30` base cleanup.
- `FUN_106d7260` (line 1119834) — **RunWorldLoadIntroSequence** — the load-op's tick logic: checks the `"fullscreen"` cvar, conditionally plays an ESRB ratings splash (`"ratings\intro_esrb"`) and an `"epilepsy_calibration"` / `"intro_fox"` video sequence gated by an internal step index, then sets console var `"forcevsync 1"` once done — this is the pre-world boot cinematic gate, sequenced before actual sector/world data streaming begins.
- `FUN_106d79c0` (line 1120034) — **FCXLoadWorldOp_OnStepFailed** — decrements a refcount and, if a sub-step condition (`FUN_102058d0`) is false, transitions the op's state machine via vtable+0x38(2) (abort/retry path).
- `FUN_106d7f50` (line 1120187) — **WorldLoadingScreenPumpLoop** — busy-loop that renders/presents (`FUN_1020bcb0(1)`), advances a frame (`FUN_100b1a90(0)`), and pumps input (`FUN_1000a8d0(0)`) repeatedly while polling an async completion counter (`FUN_10ad1910`) — the "spin and render the loading screen" loop that runs while a world/sector streaming set completes in the background.

### CSectorResource / C3DEngine resource-factory wiring (0x103b5xxx)

- `FUN_103b5460` (line 643525) — **ResetSectorResourceCacheIds** — resets two cached sub-object lookup fields (id pairs at two different member offsets) to `0xffffffff` — sector resource cache-id invalidation, typically on unload/reload.
- `FUN_103b54b0` (line 643543) — **InvalidateSectorResourceCacheGuarded** — reentrancy-guarded wrapper (`+0x3c` busy flag) around `FUN_103b5460`, only runs when the target sub-object (`+0x38`) exists.
- `FUN_103b55c0` (line 643640) — **BuildSectorCircleBoundsMesh** — generates a 25-segment circular polyline (sin/cos via `FUN_10ad1648`/`FUN_10ad164e`) of radius `param_5` around `(param_2,param_3,param_4)` and feeds each segment into a debug-line draw call (`FUN_10082450`) — a sector/streaming-radius debug-visualization helper (fits `CShortRangeResource`, i.e. the streaming radius around the camera).
- `FUN_103b57c0` (line 643717) — **DrawSectorRadiusDebug** — thin wrapper unpacking a `{x,y,z}` position struct into `FUN_103b55c0`.
- `C3DEngine::C3DEngine` (line 643756, demangled symbol `??0C3DEngine@@IAE@HHABVCPlatformContext@@@Z`) — 3D engine constructor; among its setup work it registers create/destroy factory-callback pairs (`FUN_100af800`/`FUN_100fa120`) for built-in resource types — `CTextureMipResource`, `CBinkResource`, `CTextureResource`, `CMaterialResource`, and more — into the global by-name resource-class registry. This is the wiring that feeds `FUN_100afb20`/ResolveOrCreateNamedResourceClass (see above) when the FCB/XML deserializer instantiates a typed resource object by class name.

### Sector Streaming / Active-Region Grid manager (0x100ca0xx-0x100cb0xx) — HIGH SIGNAL for editor's sector/heightmap focus

This cluster is the engine's runtime sector-grid streaming manager: tracks a rectangular "active region" of loaded sectors around the camera/player and issues load/unload requests as it moves. Confirms the world-space sector tile size is **64 units** (`<<6`/`*0x40` appears throughout).

- `FUN_100ca040` (line 145110) — **SectorGrid_Constructor** — initializes a circular sentinel list (pending-request queue) and zeroes region-size fields.
- `FUN_100ca0c0` (line 145151) — **SetSectorGridDimensions** — clamps negative width/height/offset to 0, stores grid width/height, and calls the polymorphic resize hook (vtable+4) with flag `0x40` — this is what `FUN_100ece60`/ParseSectorGridOffset calls after reading `SectorCountX`/`SectorCountY` from the descriptor XML.
- `FUN_100ca110` (line 145180) — **IsSectorXYInActiveRegion** — bounds-checks a `(x,y)` sector-grid coordinate against the current active-region rectangle.
- `FUN_100ca150` (line 145197) — **IsSectorLinearIndexInActiveRegion** — same check but takes a flattened linear sector index (divides/mods by the global grid width `DAT_111cab8c+0x24`).
- `FUN_100ca1a0` (line 145217) — **WorldToSectorLocalCoords** — subtracts `(offsetX*64, offsetY*64)` from a world-space `(x,y)` to get sector-local coordinates — **confirms 64-world-unit sector tiles**.
- `FUN_100ca1e0` (line 145229) — **ComputeSectorLoadRegionByIndex** — given a linear sector index and a radius, computes the clamped `[x0..x1]×[y0..y1]` rectangle of sectors that should be active, then resizes the grid to it (vtable+4) — the core "which sectors should be streamed in around sector N with radius R" computation.
- `FUN_100ca2b0` (line 145291) — **SetSectorActiveRegionFromOffsets** — reads `SectorOffsetX`/`SectorOffsetY` via the reflection getter (vtable+0x80) and resizes the active region to them — companion to `FUN_100ece60`.
- `FUN_100ca340` (line 145332) — **WorldPosToSectorLinearIndex** — converts a float world `(x,y)` to a clamped, LOD-shifted (`>>` by a stored shift amount) flattened sector-grid index; called by the entity-spawn code (`FUN_102b22b0`) to determine which sector a spawned entity belongs to.
- `FUN_100ca3a0` (line 145362) — **ClearSectorActiveRegion** — resets the active region to empty (0,0).
- `FUN_100ca3c0` (line 145376) — **IsWorldPosInActiveSectorRegion** — checks a float world `(x,y)` against the active region's world-space bounds (`offset*64` .. `offset*64+size-1`) — same 64-unit tile confirmation, world-space variant of `FUN_100ca110`.
- `FUN_100ca420` (line 145396) — **ResizeSectorGridToRegionDescriptor** — like `FUN_100ca1e0` but takes a pre-built region descriptor struct directly (fields at `+4/+8/+0x1c/+0x20`) rather than computing it from an index+radius.
- `FUN_100ca470` (line 145433) — **SectorActiveRegion_ConstructEmpty** — two-stage vtable init, zeroes region fields, resizes grid to `(0,0)`.
- `FUN_100ca570` (line 145491) — **IsSectorRegionEmpty** — true when the region's width is 0 and a secondary flag is clear.
- `FUN_100ca590` (line 145504) — **SectorLoadRequest_Construct** — zero-inits a small pending-load-request record (vtable `&DAT_1101aa80`).
- `FUN_100ca5b0` (line 145520) — **RemoveSectorLoadRequestsByField2** — removes all pending-request list entries whose secondary key (offset+8) matches `param_2`.
- `FUN_100ca620` (line 145543) — **RemoveSectorLoadRequestsByField1** — same but matches the primary key (offset+4) — likely the by-sector-id vs by-requester-id removal pair.
- `FUN_100ca6f0` (line 145581) — **AddUniqueSectorLoadRequest** — dedup-inserts a new pending sector-load request (only appends if `param_2` isn't already queued).
- `FUN_100ca770` (line 145611) — **FlushPendingSectorLoadRequests** — snapshots the pending-request list into a temp array, invokes each entry's callback (vtable+0) with `param_2`, then destroys the temp array — the "process this frame's queued sector load/unload requests" pump.
- `FUN_100cafc0` (line 145746) — **SectorDescriptorMapEntry_ConstructFromKey** — copy-constructs a name→sector-descriptor map node: CString key plus a 5-field payload (id/flags/detail-mask style record matching `FUN_100ed410`'s output).
- `FUN_100cb030` (line 145771) — **SectorDescriptorMapEntry_CopyConstruct** — same map-node copy-construct but sourced from another node (self-copy constructor overload).

- `FUN_100c9ec0` (line 145012) — **SectorGrid_DestroyPendingRequestMap** — walks an internal `std::map`-style tree of per-sector-index pending-request sub-lists, destroys each sub-list (`FUN_100c9de0`), then frees the active-region array (`FUN_100b8810`/`FUN_100c8c60`) — the map-of-lists backing store for `FUN_100ca5b0`/`FUN_100ca620`/`FUN_100ca6f0`'s per-request bookkeeping.
- `FUN_100c9fc0` (line 145081) — **SectorGridManager_Destructor** — top-level destructor chained from the grid manager's scalar-deleting-destructor (`FUN_100ca0a0`): destroys the pending-request map (`FUN_100c9d20`) and frees the region array.

### Landmark / Sector-Spawn-Category streaming priority (0x10204xxx-0x10205xxx) — directly relevant to landmark editor feature

This cluster computes streaming/spawn *priority scores* for `CLandmarkNearCategory`/`CLandmarkFarCategory` entries (both derive `CSectorSpawnCategory`, per the class hierarchy TSV) based on Chebyshev distance from the player's current sector — this is the runtime counterpart to the editor's `landmarkfar_*.data.fcb`/`landmarknear_*.data.fcb` files.

- `FUN_10204990` (line 360337) — **ComputeLandmarkSectorLoadPriority** — given a target sector's flat grid index (`param_3`, must be `< 10000`) and a reference `(x,y)`, computes Chebyshev distance in sector-grid units (`index / gridWidth`, `% gridWidth`, abs, then max of the two — matches the same grid-width global `DAT_111ca75c+8` used elsewhere) and returns a priority score; the score is boosted when the sector matches special-case globals — exact match with `DAT_1117bbf4` (+5), a "near" global resolved via `FUN_102a8960` (+5 more), or a "far" global resolved via `FUN_102a8930` matched against `*param_5` (+10 more, capped bonus +15) — i.e. landmark-near/-far sectors get load-priority boosts over plain distance sorting.
- `FUN_10204de0` (line 360659) — **ComputeLandmarkEntryPriority** — per-landmark wrapper: if there's no active reference sector, priority defaults to `100` (lowest urgency); otherwise resolves the current camera/player sector position (`FUN_101b7bd0`/`FUN_101b7b80`) and calls `FUN_10204990` to derive the entry's priority.
- `FUN_102051d0` (line 360895) — **RecomputeAllLandmarkPriorities** — walks a landmark linked list and recalculates each node's cached priority (`node[2]`) via `FUN_10204990` against a new reference `(param_4,param_5)` — the batch re-sort triggered when the player/camera moves to a new sector, re-ranking which landmark-near/-far entries should stream in next.
- `FUN_10204840` (line 360214) — **GetLandmarkFarReferenceHandle** — lazily resolves (via `FUN_102a8930`, the same "far" global used in `FUN_10204990`) and caches a global handle representing the active far-landmark reference.
- `FUN_10204870` (line 360231) — **SetSectorDescriptorAccessibleFlag** — trivial setter for the sector-descriptor byte at `+0x155` (matches the `isSectorAccessible` bit built by `FUN_100ed410`).
- `FUN_10204a20` (line 360378) — **RefreshSectorDescriptorAccessFlag** — copies a global accessibility byte (`DAT_111e5da0+0x81`) into the sector-descriptor's `+0x155` field after invoking `FUN_101aacc0`.
- `FUN_10204a80` (line 360400) — **CacheLandmarkReferencePosition** — copies a 20-byte position/id record into 3 global slots (`DAT_111e75e8/f0/f8`) — stores the "current landmark reference point" (likely player/camera sector+offset) consumed by the priority functions above.
- `FUN_10204ab0` (line 360413) — **StoreSectorSpawnCategoryBounds** — copies three 20-byte bound/position records into a `CSectorSpawnCategory`-family object at offsets `0x158/0x16c/0x180` — near/far/extra streaming-bounds storage.
- `FUN_10205000` (line 360780) — **AppendLandmarkEntryFast** — fast-path append onto a landmark dynamic array when spare capacity exists (capacity encoded via the same shift-pair pattern seen in the sector-grid code), else falls back to grow+insert (`FUN_100ed980`).
- `FUN_10205220` (line 360914) — **EnsureLandmarkArrayCapacity** — grows a landmark dynamic array's backing storage to at least `param_2` elements via `FUN_100edbd0` if the current capacity is insufficient.

### CGeometryResource — mesh-part reflected fields (0x101c9xxx)

- `FUN_101c9e80` (line 319903) — **RegisterGeometryPartFieldDescriptors** — one-time init (`DAT_111e713e` guard) registering reflected fields for a geometry "part" record into `DAT_111e7158`: `PartID` (int), `TextureIndex` (int, offset 8), `ColorIndex` (int, offset 4) — the reflection table FCB geometry resources use for per-part texture/color-index assignment.
- `FUN_101c9dd0` (line 319828) — **CompareGeometryPartKey** — 3-field lexicographic less-than comparator (PartID/TextureIndex/ColorIndex-style composite key) used by the part lookup tree.
- `FUN_101c9e00` (line 319851) — **FindGeometryPartByKey** — red-black-tree search for a geometry part matching a 3-field composite key.
- `FUN_101c9cf0` / `FUN_101c9d60` (lines 319790, 319809) — **EnsureGeometryPartArrayCapacity** (two near-identical copies for different member arrays) — grows a dynamic array's capacity via `FUN_100edbd0`, same shift-encoded capacity pattern seen in the sector/landmark array-growth helpers.

---

## Networking (background sweep)

Scope: sockets, packet serialization/replication, multiplayer entity sync, RPC, session/matchmaking.

STATUS: COMPLETE. 81 entries (~95 distinct FUN_ addresses, several ctor/dtor pairs share one entry)
labeled across 4 regions. Headline finding: the DLL statically
links the full **Quazal Rendez-Vous (RDV)** middleware SDK (`Quazal::` namespace, thousands of
functions) — this is the real online/session/replication engine; Ubisoft's Dunia-side `CSession*`/
`CNet*` classes and the "Plaza" service layer are thin wrappers around it. See section B for the
SDK curated sample, section C for the game-specific `Plaza*Service` RPC call sites (high-confidence,
anchored by literal `"PlazaClient::<Service>::<Method>"` strings), and section A for the unrelated
low-level Havok BSD-socket wrapper (used for Havok's own telemetry/remote-debugger transport, not
game traffic).

### Regions:
### A. Havok BSD socket wrapper layer (`.\System\Io\Socket\Bsd\hkBsdSocket.cpp`) — low-level Winsock wrapper used by Havok subsystems (telemetry/remote debugger transport), lines ~1791300-1793900

- `FUN_10b5c5c0` (line 1793494) — **InitWinsock** — lazy-init guarded by `DAT_11243fd0`; calls WSAStartup-equivalent thunk (`FUN_1003cabc` -> `DAT_11000844`), logs `"(Windows)WSAStartup failed with error!"` and hkError-reports with source tag `hkBsdSocket.cpp:0x48` on failure.
- `FUN_10b5c3f0` (line 1793369) — **CreateBsdSocketHandle** — calls `socket(AF_INET=2, SOCK_STREAM=1, 0)` via thunk `FUN_1003ca74`, stores handle at `param_1[8]`, returns true if handle == -1 (failure).
- `FUN_10b5c3d0` (line 1793355) — **CloseBsdSocketHandle** — calls `closesocket()`-equivalent thunk `FUN_1003ca62` on the stored handle if valid, resets handle to -1.
- `FUN_10b5c420` (line 1793384) — **RecvBsdSocketData** — calls `recv()`-equivalent thunk `FUN_1003ca8c(handle, buf, len, 0)`; treats WSAEWOULDBLOCK (`0x2733`) as non-fatal.
- `FUN_10b5c470` (line 1793406) — **SendBsdSocketData** — calls `send()`-equivalent thunk `FUN_1003ca86(handle, buf, len, 0)`; treats WSAEWOULDBLOCK (`0x2733`) as non-fatal.
- `FUN_10b5c4d0` (line 1793441) — **ConnectBsdSocket** — builds a `sockaddr_in` (family=AF_INET) on stack, lazily creates the socket handle via `FUN_10b5c3f0`, resolves hostname (digit-check via `FUN_10b5c4c0` decides literal-IP `inet_addr` path vs `gethostbyname` path through thunks `FUN_1003cab0`/`FUN_1003cac2`), then calls `connect()`-equivalent thunk `FUN_1003ca80`.
- `FUN_10b5c4c0` (line 1793428) — **IsAsciiDigitChar** — helper predicate (`c - '0' < 10`) used by `ConnectBsdSocket` to distinguish a literal dotted-IP string from a hostname needing DNS resolution.
- `FUN_10b5c690` (line 1793550) — **BindAndListenBsdSocket** — sets `SO_REUSEADDR`, calls `bind()`+`listen()`-equivalent thunks (`FUN_1003ca92`/`FUN_1003ca7a`), logs `"Listening on host[%s] port %d"` via hkError-style logging tagged `hkBsdSocket.cpp:0x16c`.
- `FUN_10b5c890` (line 1793650) — **AcceptBsdSocketConnection** — calls `accept()`-equivalent thunk chain, on success logs `"Socket got connection from [%s:%d]\n"` (tag `hkBsdSocket.cpp:0x194`), sets the new handle non-blocking and wraps it via `FUN_10b5c660` into a new socket object.
- `FUN_10b5c660` (line 1793534) — **ConstructBsdSocketFromHandle** — thiscall ctor: installs `hkBsdSocket::vftable`, stores an existing OS socket handle at `param_1[8]`, calls `FUN_10b5c3f0` (create new handle) if none passed.
- `FUN_10b5c640` (line 1793519) — **DestructBsdSocket** — dtor: installs `hkBsdSocket::vftable` then unwinds base-class vtables (`hkBaseObject::vftable`), calls `FUN_10b5c3d0` (close handle).
- `FUN_10b59a40` (line 1791431) — **ConstructHkSocketBase** — ctor installs `hkSocket::vftable` plus nested `hkSocket::ReaderAdapter::vftable` / `hkSocket::WriterAdapter::vftable` sub-objects; one-time lazy global init hook `DAT_1119e134`.
- `FUN_10b59960` (line 1791363) — **HkSocketReaderRead** — loop reading up to `param_3` bytes through the reader-adapter vtable slot `+0x14`, retrying until buffer full or a zero-byte read (stream closed).
- `FUN_10b599d0` (line 1791397) — **HkSocketWriterWrite** — loop writing up to `param_3` bytes through the writer-adapter vtable slot `+0x18`, retrying until fully written or a zero-byte write.

- `FUN_10cb1d30` (line 2037576) — **ConstructQuazalPacketOut** — ctor installs `Quazal::PacketOut::vftable`; conditionally allocates a worker `GThread` (source tag `PacketOut.cpp:0x26`) for async/bundled packet send when a flag bit (`&0x20`) is set — Quazal RDV's outgoing packet builder.
- `FUN_10cb1df0` (line 2037624) — **DestructQuazalPacketOut** — dtor for `Quazal::PacketOut`; tears down the optional worker thread (`GThread::OnExit`) before freeing.
- `FUN_10cbe180` (line 2048876) — **ConstructQuazalPacketIn** — ctor installs `Quazal::PacketIn::vftable`; allocates a 0x400-byte receive buffer (source tag `PacketIn.cpp:0x1c`) — Quazal RDV's incoming packet parser/reader.
- `FUN_10cbdf50`/`FUN_10cbdff0` (lines 2048760/2048803) — **ConstructQuazalHighLevelStream / DestructQuazalHighLevelStream** — ctor/dtor pair for `Quazal::HighLevelStream::vftable`, the higher-level (reliable/ordered) packet stream layered over the raw transport.
- `FUN_10cbe0b0` (line 2048841) — **HighLevelStreamSendMessage** — allocates a new `Quazal::PacketOut` via `FUN_10cb1d30`, stamps channel/flags fields, then dispatches it through a vtable call at `+0x1c` on the owning stream — the actual "send an RMC/message" path for `Quazal::HighLevelStream`.
- `FUN_10cb21f0`/`FUN_10cb2270`/`FUN_10cb22b0` (lines 2037839/2037871/2037888) — **ConstructQuazalPacket / DestructQuazalPacket (x2)** — base ctor/dtor for `Quazal::Packet::vftable`, the common base of `PacketIn`/`PacketOut`.

### B. Quazal Rendez-Vous (RDV) — embedded 3rd-party networking middleware SDK, lines ~1974800-2060500

MAJOR FINDING: the DLL statically links the full **Quazal Rendez-Vous (RDV)** middleware (`Quazal::` namespace) — a commercial UDP-based (PRUDP) online/session/matchmaking/object-replication library widely used by Ubisoft titles of this era. This explains the `_RdV` suffixed classes seen in the Dunia class hierarchy (`CNetMessageClientReady_RdV`, `CSessionInfo_RdV`) — the Dunia engine's own `CSession*`/`CNet*` layer (section D below) is a thin wrapper around this SDK. Given the sheer size (thousands of functions), this is a curated sample of the clearest anchor points (mostly constructors identified via their `Quazal::X::vftable` install), not an exhaustive listing — exhaustively labeling a whole vendored SDK is out of scope for this sweep.

### B1. Packets, streams & transport
- `FUN_10c8cf20` (line 2003264) — **ConstructQuazalJobConnectStation** — ctor for `Quazal::JobConnectStation::vftable`, logs job name `"JobConnectStation"` — async job that performs a PRUDP connect to a remote station (peer).
- `FUN_10c8e130` (line 2004150) — **QuazalJobConnectStationChooseURLStrategy** — logs `"JobConnectStation"`, then branches between `"JobConnectStation::PrepareURLs"` and `"JobConnectStation::RetrieveURLs"` continuation steps depending on whether target connection URLs are already known — part of the connect-station job's state machine.
- `FUN_10ca8a80`/`FUN_10ca8b20` (lines 2029450/2029482) — **ConstructQuazalJobDisconnectStation / DestructQuazalJobDisconnectStation** — ctor logs `"JobDisconnectStation"`, builds a disconnect-reason code (default `0xe000000e`) before tearing down a station connection.
- `FUN_10c99350`/`FUN_10c999a0` (lines 2014860/2015156) — **ConstructQuazalUDPTransport (x2 overloads)** — ctor for `Quazal::UDPTransport::vftable`, the concrete UDP-socket transport backing PRUDP.
- `FUN_10ca7eb0` (line 2028691) — **ConstructQuazalPRUDPStream** — ctor for `Quazal::PRUDPStream::vftable` — Quazal's Packet-based Reliable UDP stream implementation (the core reliable-transport wire protocol, "PRUDP" is Quazal/Nintendo's well-known reliable-UDP scheme).
- `FUN_10cba210`/`FUN_10cbb060` (lines 2045773/2046418) — **ConstructQuazalPRUDPEndPoint / DestructQuazalPRUDPEndPoint** — ctor/dtor for `Quazal::PRUDPEndPoint::vftable`, represents one remote peer's PRUDP connection endpoint (sequencing/ack state).
- `FUN_10c974f0`/`FUN_10c98300` (lines 2013188/2013861) — **ConstructQuazalNATTraversalEngine (x2)** — ctor for `Quazal::NATTraversalEngine::vftable` — NAT hole-punching / public-URL probing for P2P connections (works with `Quazal::URLProbe`).
- `FUN_10c973b0`/`FUN_10c97450` (lines 2013128/2013152) — **ConstructQuazalZLibCompression / DestructQuazalZLibCompression** — ctor/dtor for `Quazal::ZLibCompression::vftable`, a pluggable packet-payload compression codec.
- `FUN_10cc0690`/`FUN_10cc0780` (lines 2051277/2051361) — **ConstructQuazalKeyedChecksumAlgorithm / ConstructQuazalHMACChecksum** — packet-integrity checksum plugins (`Quazal::KeyedChecksumAlgorithm`, `Quazal::HMACChecksum::vftable`) used to authenticate PRUDP packets.

### B2. Sessions, stations (peers) & replication (object duplication)
- `FUN_10c78140` (line 1982880) — **ConstructQuazalDOSession** — ctor for `Quazal::_DO_Session::vftable` — the distributed-object representation of a game session (room) used by the replication layer.
- `FUN_10c84890`/`FUN_10c84900` (lines 1995433/1995461) — **ConstructQuazalDOSessionAlt / ConstructQuazalDOCSession** — ctors for `Quazal::_DO_Session::vftable` / `Quazal::_DOC_Session::vftable` (client-side "DOC" cached mirror of the session distributed object).
- `FUN_10c82380` (line 1993109) — **ConstructQuazalDOStation** — ctor for `Quazal::_DO_Station::vftable` — distributed-object representation of one connected peer/station.
- `FUN_10c85b00`/`FUN_10c85b90` (lines 1996417/1996449) — **ConstructQuazalDOStationAlt / CreateQuazalDOCStation** — ctor for `Quazal::_DO_Station::vftable`, and a factory function that heap-allocates and stamps a `Quazal::_DOC_Station::vftable` object (tagged `"StationDDL.cpp"`).
- `FUN_10c70390`/`FUN_10c70760`/`FUN_10c73950` (lines 1975369/1975661/1978255) — **ConstructQuazalDuplicatedObject (x3 overloads)** — ctors for `Quazal::DuplicatedObject::vftable` — the base class for any object mirrored/replicated across the network (the core of Quazal's replication system).
- `FUN_10c87550`/`FUN_10c87b30` (lines 1997939/1998363) — **ConstructQuazalObjDupProtocol / DestructQuazalObjDupProtocol** — ctor/dtor for `Quazal::ObjDupProtocol::vftable` — the wire protocol that synchronizes `DuplicatedObject` state between stations (the actual entity-replication protocol).
- `FUN_10c8e3e0`/`FUN_10c8e440`/`FUN_10c8e520` (lines 2004259/2004286/2004349) — **ConstructQuazalChangeDupSetOperation (variants) / DestructQuazalChangeDupSetOperation** — operation that adds/removes objects from a station's "duplication set" (i.e. which replicated objects a peer subscribes to) — logged to `"ChangeDupSetOperation.cpp"`.
- `FUN_10c8fb10`/`FUN_10c8fbe0` (lines 2005685/2005736) — **ConstructQuazalStationManager (x2)** — ctor for `Quazal::StationManager::vftable`, logs `"StationManager"` — owns/tracks all connected `Station` peers for a session.
- `FUN_10ca2780`/`FUN_10ca27e0` (lines 2023628/2023660) — **ConstructQuazalStationConnectionManager / DestructQuazalStationConnectionManager** — ctor/dtor for `Quazal::StationConnectionManager::vftable`, manages the low-level PRUDP connections underlying each Station.
- `FUN_10c8c2e0`/`FUN_10c8c740` (lines 2002529/2002741) — **ConstructQuazalDOCore (x2 overloads)** — ctor for `Quazal::DOCore::vftable` (allocates a working buffer tagged `DOCore.cpp:0x78`) — the central "distributed object" registry/kernel that all replicated objects and stations plug into.
- `FUN_10c8c930`/`FUN_10c8c990`/`FUN_10c8ca60` (lines 2002857/2002885/2002948) — **ConstructQuazalChangeMasterStationOperation / DestructQuazalChangeMasterStationOperation (x2)** — operation implementing host migration (transferring the "master station" role to a different peer).
- `FUN_10c905d0`/`FUN_10c90600`/`FUN_10c90650` (lines 2006274/2006295/2006321) — **ConstructQuazalCreateMasterOperation (x2) / DestructQuazalCreateMasterOperation** — operation electing/creating the initial master (host) station for a session; return value of a related helper is literally the string `"CreateMaster"`.
- `FUN_10c90530`/`FUN_10c90580`/`FUN_10c905a0` (lines 2006210/2006245/2006258) — **ConstructQuazalFaultRecoveryOperation / DestructQuazalFaultRecoveryOperation (x2)** — operation that runs when a station drops unexpectedly (connection fault), driving reconnection/cleanup logic.
- `FUN_10c933b0`/`FUN_10c93420` (lines 2009438/2009476) — **ConstructQuazalJoinSessionOperation / DestructQuazalJoinSessionOperation** — ctor/dtor for `Quazal::JoinSessionOperation::vftable`, drives the client-side "join an existing session" handshake.
- `FUN_10ca0aa0`/`FUN_10ca0af0` (lines 2021831/2021863) — **ConstructQuazalLeaveSessionOperation / DestructQuazalLeaveSessionOperation** — ctor/dtor for `Quazal::LeaveSessionOperation::vftable`, the counterpart session-leave handshake.

### B3. RPC (Remote Method Call) plumbing
- `FUN_10c7d350`/`FUN_10c7d3c0` (lines 1988000/1988023) — **ConstructQuazalRMCContext (x2 overloads)** — ctor for `Quazal::RMCContext::vftable` — "Remote Method Call" context: the RPC dispatch/marshalling context that all Quazal DO method calls (RPCs) flow through.
- `FUN_10c7e8f0` (line 1989447) — **ConstructQuazalActiveDOCallContext** — ctor for `Quazal::ActiveDOCallContext::vftable`, built on top of an `RMCContext`; represents an in-flight remote-call the local side has made against a distributed object.
- `FUN_10c818f0`/`FUN_10c81e50` (lines 1992545/1992767) — **ConstructQuazalDOCallContext (x2 overloads)** — ctor for `Quazal::DOCallContext::vftable` — base RPC call-context class carrying target-object/method-id/arguments for a distributed-object method call.
- `FUN_10c7ee10`/`FUN_10c7efd0` (lines 1989776/1989892) — **ConstructQuazalCallMethodOperation / DestructQuazalCallMethodOperation** — ctor/dtor for `Quazal::CallMethodOperation::vftable` — the operation object that actually issues an outgoing RPC call and waits for its reply.
- `FUN_10c7fc90`/`FUN_10c7fcd0` (lines 1990610/1990647) — **ConstructQuazalDDLDeclarations / DestructQuazalDDLDeclarations** — ctor/dtor for `Quazal::DDLDeclarations::vftable` — holds the "Data Description Language" schema (field layout) used to serialize/deserialize RPC arguments and replicated-object state; explains the `_DDL_*`-prefixed message classes seen throughout (e.g. `Quazal::_DDL_AvatarMetaGameMatch`, `Quazal::_DDL_FriendData`).

### B4. Back-end services, authentication & secure transport (Ubisoft "Rendez-Vous" online layer)
- `FUN_10cc28d0`/`FUN_10cc34a0` (lines 2053143/2053879) — **ConstructQuazalBackEndServices (x2)** — ctor for `Quazal::BackEndServices::vftable` — top-level facade for the online backend (login/matchmaking/session-directory service client).
- `FUN_10cc3f70` (line 2054596) — **ConstructQuazalRendezVous** — ctor for `Quazal::RendezVous::vftable`, the main client-facing Rendez-Vous SDK object games instantiate to go online.
- `FUN_10cc7810`/`FUN_10cc7840` (lines 2057656/2057678) — **ConstructQuazalRendezVousLoginOperation / DestructQuazalRendezVousLoginOperation** — async login-to-backend operation.
- `FUN_10cc7870`/`FUN_10cc78b0` (lines 2057691/2057725) — **ConstructQuazalRendezVousLogoutOperation / DestructQuazalRendezVousLogoutOperation** — async logout-from-backend operation.
- `FUN_10cc7980`/`FUN_10cc7b40` (lines 2057763/2057879) — **ConstructQuazalAuthenticationClient / DestructQuazalAuthenticationClient** — ctor/dtor for `Quazal::AuthenticationClient::vftable`, wraps a `TicketGrantingProtocolClient` for authentication-ticket exchange.
- `FUN_10cc7bc0`/`FUN_10cc7c40` (lines 2057923/2057950) — **ConstructQuazalSecureConnectionClient / DestructQuazalSecureConnectionClient** — ctor/dtor for `Quazal::SecureConnectionClient::vftable`, negotiates an encrypted `SecureConnectionProtocolClient`/`ClientProtocol` session.
- `FUN_10cc7e90`/`FUN_10cc81b0` (lines 2058076/2058441) — **ConstructQuazalSecureEndPoint / DestructQuazalSecureEndPoint** — ctor/dtor for `Quazal::SecureEndPoint::vftable`, an encrypted transport endpoint layered over a `PRUDPEndPoint`.
- `FUN_10cc6580`/`FUN_10cc68b0` (lines 2056440/2056712) — **ConstructQuazalSecureStream / DestructQuazalSecureStream** — ctor/dtor for `Quazal::SecureStream::vftable`, an encrypted `Quazal::Stream` (likely wraps `EncryptionAlgorithm`/`Key`).

### C. Ubisoft "Plaza" online service layer — game-specific glue over Quazal RDV

Each `Plaza*Service` client class wraps one or more Quazal RMC (remote-method-call) requests. Every dispatch site is uniquely and reliably anchored by an embedded `"PlazaClient::<Service>::<Method>"` diagnostic string literal passed straight to the outgoing-call builder (`FUN_10059b10` -> `FUN_10e100xx`/`FUN_10e0f0xx`), so these names are high-confidence — they are effectively the original method names.

- `FUN_1004db80` (line 51813) — **PlazaMetaGameServiceQuickJoinMatch** — builds and sends the `"PlazaClient::PlazaMetaGameService::QuickJoinMatch"` RPC request (`.\Services\PlazaMetaGameService.cpp:0xf2`); early-outs via a cached-result path (`param_1+0x4c`) when a result is already pending.
- `FUN_1004dc90` (line 51880) — **PlazaMetaGameServiceLeaveMatch** — sends the `"PlazaClient::PlazaMetaGameService::LeaveMatch"` RPC (`.cpp:0x119`), mirror-image of QuickJoinMatch (opposite early-out branch).
- `FUN_1004f310` (line 52899) — **PlazaPlayerProfileServiceSynchronizeInventory** — sends `"PlazaClient::PlazaPlayerProfileService::SynchronizeInventory"` (`.cpp:0xcc`) to pull the player's armoury/inventory state from the backend.
- `FUN_1004fe70` (line 53456) — **PlazaArmouryServiceGetBuyItemsByPage** — sends `"PlazaClient::PlazaArmouryService::GetBuyItemsByPage"` (`.cpp:0xb8`), paginated armoury shop query; builds a `Quazal::_DDL_ArmouryItemsPage`-style request.
- `FUN_1004ffc0` (line 53525) — **PlazaArmouryServiceGetSellItemsByPage** — near-identical twin sending `"PlazaClient::PlazaArmouryService::GetSellItemsByPage"` (`.cpp:0xd6`).
- `FUN_10051450` (line 54732) — **PlazaFriendServiceClearFriend** — sends `"PlazaClient::PlazaFriendService::ClearFriend"` (`.cpp:0x189`) — removes a friend list entry.
- `FUN_100514d0` (line 54778) — **PlazaFriendServiceAcceptFriend** — sends `"PlazaClient::PlazaFriendService::AcceptFriend"` (`.cpp:0x1a2`) — accepts a pending friend request.
- `FUN_10051550` (line 54824) — **PlazaFriendServiceDeclineFriend** — sends `"PlazaClient::PlazaFriendService::DeclineFriend"` (`.cpp:0x1bb`) — declines a pending friend request.
- `FUN_10052430` (line 55380) — **PlazaFriendServiceUpdateFriendsCache** — issues three sequential `"PlazaClient::PlazaFriendService::UpdateFriendsCache"` RPCs (lines 0x1db/0x1e8/0x1f5 in source) with different request-mode args (`FUN_10e6caf0`, `FUN_10e6cac0(...,2,0,...)`, `FUN_10e6cac0(...,2,1,...)`) — refreshes friends/online-status/blocked lists.
- `FUN_100545b0` (line 57231) — **PlazaPlayGroupServiceCreatePlayGroup** — sends `"PlazaClient::PlazaPlayGroupService::CreatePlayGroup"` (`.cpp:0x22c`); allocates a `Quazal::PlayGroupGathering` DO wrapped in `AnyObjectHolder<Gathering,String>` as the request payload — creates a party/group session.
- `FUN_10054750` (line 57311) — **PlazaPlayGroupServiceSendInvitations** — loops over a pending-invite array (`param_1+0x80`/`+0x7c`) sending one `"PlazaClient::PlazaPlayGroupService::SendInvitations"` RPC (`.cpp:0x265`) per invitee, then clears the queue.
- `FUN_10054830` (line 57367) — **PlazaPlayGroupServiceAcceptInvitation** — sends `"PlazaClient::PlazaPlayGroupService::AcceptInvitation"` (`.cpp:0x28b`), guarded against re-entry via a group-state field (`param_1+0xec`).
- `FUN_10054b90` (line 57542) — **PlazaPlayGroupServiceDeclineInvitation** — sends `"PlazaClient::PlazaPlayGroupService::DeclineInvitation"` (`.cpp:0x2d8`, line 57568).
- `FUN_10054c20` (line 57588) — **PlazaPlayGroupServiceLeavePlayGroup** — sends `"PlazaClient::PlazaPlayGroupService::LeavePlayGroup"` (`.cpp:0x2fc`), only valid while group state is 4 or 5 (in-group).
- `FUN_10054ce0` (line 57637) — **PlazaPlayGroupServicePromotePlayer** — sends `"PlazaClient::PlazaPlayGroupService::PromotePlayer"` (`.cpp:0x331`) — promotes a member to group leader; requires group state == 4.
- `FUN_10054dc0` (line 57689) — **PlazaPlayGroupServiceKickPlayer** — sends `"PlazaClient::PlazaPlayGroupService::KickPlayer"` (`.cpp:0x35d`) — removes a member from the play-group.
- `FUN_10054910` (line 57416) — **PlazaPlayGroupServiceOnInvitationReceived** — RPC-reply/callback handler: on success stashes the inviter's gathering/session IDs into `param_1+0xe4/+0xe8` and sets group-state field to `5` (invited); on failure resets state to `0` and forwards an error via `FUN_10059b50`.
- `FUN_10058630` (line 60162) — **PlazaNetworkServiceJoinPlaza** — sends `"PlazaClient::PlazaNetworkService::JoinPlaza"` (`.\Services\PlazaNetworkService.cpp:0x306`) — the top-level "log into the Plaza online service" RPC; gated on connection-state fields `param_1+0x38`/`+0x48`/`+0x54`.
- `FUN_10059700` (line 60855) — **PlazaChatServiceSendChatMessage** — sends `"PlazaClient::PlazaChatService::SendChatMessage"` (`.\Services\PlazaChatService.cpp:0xf4`); builds a `Quazal::TextMessage` payload and special-cases channel id `2` (looks up a `MessageRecipient` handle at `+0xe4`) before dispatch.
- `FUN_10059940` (line 60985) — **PlazaChatServiceBuildIncomingTextMessage** — allocates and casts a `Quazal::_DDL_TextMessage` object to `Quazal::TextMessage::vftable` (`.cpp:0x107`) then completes a pending async op — the receive-side counterpart that turns a raw DDL text-message into the client's `TextMessage` object.
- `FUN_10057eb0` (line 59792) — **InitPlazaNetworkServiceSubProtocols** — one-time setup allocating each of `PlazaNetworkService`'s Quazal sub-protocol client objects (network, playgroup-gathering, and several DAT-table-driven protocol stubs) tagged with source lines `PlazaNetworkService.cpp:0x382-0x3c8`; tears them all down again if the connect attempt (`param_2`) fails.

### VoiceChat (`.\VoiceChat\VoiceChannel.cpp`) — spot-checked
- `FUN_1005ef30` (line 64823) — **VoiceChannelInitParticipantMask** — allocates a small object with bitmask `0x3ff` (10-bit, plausibly a 10-slot participant/talk-mask) tagged `VoiceChannel.cpp:0x55` and stores it at `param_1+0x9c` on channel setup.
- `FUN_1005ef80` (line 64851) — **RegisterVoiceChannelRPCMethods** — constructs a `Quazal::RMCContext` (`FUN_10c7d3c0`, tag `VoiceChannel.cpp:0xc9`) then registers method IDs `0x400`/`2`/`4` and a flag `0x20` via `FUN_10c768b0`/`FUN_10c768c0` — wires up the voice channel's remote-callable methods (join/leave/talk) before dispatching via `FUN_1005db10`.
- `FUN_1005f180` (line 64952) — **VoiceChannelJoin** — constructs an `RMCContext` (tag `VoiceChannel.cpp:0xa9`), builds a participant record and a callback-object (vtable `DAT_11016e18`, callback `LAB_1005f100`), registers the same method IDs as above, then dispatches through `FUN_10c77420`/`FUN_1005da20` — the "join this voice channel" call.


---
## Physics / Collision (background sweep)

Source: `Avatar_Dunia_Retail_1.02_decrypted.dll_FULL_DECOMPILE.txt` (~2.61M lines).
Cross-referenced with `avatar_class_hierarchy.tsv`.

**Engine architecture finding:** the Dunia engine statically links the **Havok Physics SDK**
(classes prefixed `hkp`/`hka`/`hk`, confirmed via hundreds of `hkXxx::vftable` stores throughout
the binary — `hkpRigidBody`, `hkpWorldRayCaster`, `hkaRagdollInstance`, `hkpCharacterRigidBody`,
`hkpVehicleRaycastWheelCollide`, `hkpRagdollConstraintData`, etc.) underneath a thin Dunia
game-layer wrapper (`CPhysComponent` hierarchy, `CVehiclePhysComponent` hierarchy,
`CTriggerComponent`, `CPhysStim`/`CPhysCollisionQueryEvent`). One custom Dunia collector class
(`nomadPhysHeightFieldRayHitCollector`) confirms "Nomad" as an internal physics-layer codename.

A reusable ground-truth pattern for the Havok layer: `*this = ClassX::vftable; if ((flags & 1) != 0) { <free-like call>; }`
is the MSVC **scalar-deleting-destructor** idiom (vptr reset to the current class at destructor
entry, then the low bit of the second param means "also free the memory" — either via
`operator delete` or by returning the object to a per-type `hkThreadMemory` free list). Field-heavy
initializers with no such conditional-free param are constructors; bare `return hkXxx::vftable;`
functions are lightweight RTTI/vtable accessors.

Total functions labeled in this sweep: **~228** (after deduplicating 2 addresses claimed by two
passes — `FUN_10385470`/`FUN_10387fd0` are kept once, under the RayCast Query API section).

---

### 1. Game-Layer Physics Components (CPhysComponent hierarchy)

### CPhysComponent / CCharacterPhysComponent (0x1003exxx)

- `FUN_1003e5c0` (line 42913) — **InitCharacterPhysAnimBinding** — on first activation (guarded by a byte flag at `+0x94`) registers debug tunables via `FUN_101b8330`, looks up the owning entity's `CAnimationComponent` via cached RTTI, and wires up phys↔anim link fields at `+0x158`/`+0x188`/`+0x1a4`/`+0x16c`.
- `FUN_1003e6a0` (line 42957) — **HandleCharacterDamageStimTurnFlag** — RTTI-checks the incoming event against `CBTZDamageStim`, and when the owner has a `CCountersComponent` sets turn-around-damping flags at `+0x70`/`+0xcc` and loads timer `+0xb8` from tunable `s_333_TurnAroundAngleDampingMethod`.
- `FUN_1003e830` (line 43047) — **UpdateTurnAroundDampingTimer** — decrements the `+0xb8` damping timer by dt and fires an audio cue via `FUN_10318dc0` while active.
- `FUN_1003e260` (line 42829) — **GetCharacterPhysComponentTypeId** — resolves/caches the RTTI type-id for `CCharacterPhysComponent`; sibling near-identical id thunks at `FUN_1003e1d0`/`e200`/`e230`/`e2c0` cover `CAnimationComponent`/`CCountersComponent`/`CCharacterSheet`/`CAIComponent`.

### CRigidPhysComponent — config lookup & class-name matching (0x1021cxxx)

- `FUN_1021c810` (line 375400) — **MatchPhysComponentClassName** — hand-rolled byte-string compare against literals `"StaticPhysComponent"`/`"RigidPhysComponent"`, used to identify which phys-component subclass a config block describes.
- `FUN_1021cf40` (line 375861) — **FindPhysComponentConfigNode** — walks XML/config `"component"` child nodes comparing each `"class"` attribute via `MatchPhysComponentClassName`.

### CRigidPhysComponent — transform sync & turn-around damping impulse

- `FUN_1021c760` (line 375357) — **SyncPhysBodyTransform** — pushes computed position/orientation into the underlying Havok body via vtable slots `+0x88`/`+0x90`.
- `FUN_1021cdc0` (line 375791) — **ApplyTurnAroundDampingImpulse** — reads position/direction via vtable, scales by the `TurnAroundAngleDampingMethod` tunable, applies impulse via vtable `+0xac`, wakes the body via `+0xc4(1)`.

### CCompoundPhysComponent — typed-child broadcast helpers

- `FUN_1021d2c0` (line 376029) — **BroadcastSetTransformToTypedChildren** — iterates a child-pointer array, forwards `(pos, rot)` to children whose dynamic RTTI matches a cached type-id via vtable `+0x68`.
- `FUN_1021d340` (line 376060) — **BroadcastActivateTypedChildren** — same iteration/RTTI filter, invoking vtable `+0x6c()` (wake/activate) on each matching child.
- `FUN_1021d3b0` (line 376090) — **BroadcastQueryTypedChildrenFlags** — same iteration, OR-accumulates a boolean from vtable `+100()` across matching children.
- `FUN_1021da00` (line 376326) — **ReleasePendingActivationList** — iterates a vector of phys-component pointers, broadcasting transform (`FUN_1021d2c0`) before releasing during teardown of a compound's pending-activation queue.
- `FUN_1021dcc0` (line 376456) — **ReleaseTypedChildrenIfInactive** — same vector-walk as above but dispatches through the activate broadcast (`FUN_1021d340`).

### CRigidPhysComponent — deferred activation queue

- `FUN_1021dd70` (line 376511) — **RemovePendingRigidBodyActivation** — removes an entry from the global pending-activation list `DAT_111e791c` and clears the "queued" flag bit `0x13` on the underlying Havok object.
- `FUN_1021de30` (line 376546) — **CancelSinglePendingRigidBodyActivation** — same match/clear-flag pattern against a single global pending slot rather than a list.
- `FUN_1021dea0` (line 376574) — **FlushPendingRigidBodyActivations** — clears the queued-flag bit on every pending entry then tears the list down.
- `FUN_1021df40` (line 376607) — **IsRigidBodyBeyondActivationDistance** — computes camera-relative squared distance scaled by an FOV ratio; physics-activation LOD/culling gate.

### CStaticClusterPhysComponent (0x10258xxx) — instanced static physics (e.g. rock/debris clusters)

- `FUN_10258090` (line 413485) — **ResizeClusterInstanceArray** — capacity-aware grow/shrink of the cluster's packed instance array.
- `FUN_102581b0` (line 413544) — **FindOrInsertClusterInstanceSlot** — linear-searches the cluster-instance array for a slot keyed by id, growing/inserting if not present.
- `FUN_10258240` (line 413573) — **InsertClusterInstanceRange** — inserts a range of instance records into the array at a computed offset.
- `FUN_10258470` (line 413691) — **RebuildClusterInstanceArray** — clears then reinserts a source range — copy/rebuild of the cluster instance table.
- `FUN_102582a0` (line 413587) — **BindClusterParticleFXComponents** — lazily walks the cluster component list for children whose `"class"` attribute equals `"ParticleFXComponent"`, records a per-instance slot→component map.
- `FUN_102584d0` (line 413708) — **RegisterStaticClusterInstanceComponents** — triggers `BindClusterParticleFXComponents` once, then registers an instance→component mapping per cluster child item.
- `FUN_10258a80` (line 413900) — **DestroyClusterPhysComponentInstances** — walks a vector of instance handles freeing each via `FUN_102f4410`.
- `FUN_10258020` (line 413453) — **SerializeClusterInstanceRead** — forwards to `FUN_10257960` using a handle from vtable slot `+0x20`.
- `FUN_10258050` (line 413470) — **SerializeClusterInstanceWrite** — mirror of the above, sourcing from vtable slot `+0x28`.
- `FUN_10258d50` (line 413959) — **WriteClusterInstanceState** — serializes one instance's transform + id into a tagged buffer.
- `FUN_10258e10` (line 413997) — **ReadClusterInstanceState** — inverse of `WriteClusterInstanceState`.

### RagdollController reflection registration

- `FUN_101be570` (line 310879; `"RagdollController"` string at line 310947) — **RegisterCharacterPhysReflectionProperties** — builds the reflection/property table for a character definition resource: registers a `RagdollController` property (getter/setter pair), `PhysWeight`, and ragdoll-adjacent scalar knobs `Enable`/`ForceDisplacement`/`ForceDisplacementFactor`/`BackupGravity`/`selSkeletonType`/etc.

---

### 2. Physics Stims & Damage Events

### CPhysStim / CPhysCollisionStim (0x1028b000–0x1028c300)

- `FUN_1028b170` (line 445582) — **SetStimImpactPosition** — writes a vec3 into the base CPhysStim's position/impact-point fields and notifies an owner/listener via vtable `+0x68`.
- `FUN_1028b3e0` (line 445742) — **CastToPhysCollisionStim** — dynamic-cast helper checking the RTTI class-id chain against `CPhysCollisionStim`'s seeded static.
- `FUN_1028b4d0` (line 445800) — **RecordStimContactPoint** — pulls a pooled record, writes a compressed position + packed-short pair; used by the collision-stim event queue.
- `FUN_1028b8d0` (line 445986) — **ConstructPhysCollisionStim** — sets vtable chain, zero-inits handle fields to "invalid" sentinels, sets self-referential owner pointer.
- `FUN_1028b950` (line 446017) — **DestructPhysCollisionStim** — releases handle, invokes listener callback, walks vtable back to base classes.
- `FUN_1028bc30` (line 446124) — **RecordCollisionImpactEvent** — fuller "record a collision hit": copies a transform/quaternion block, stores entity/component handles, stamps a timestamp.
- `FUN_1028c230` (line 446263) — **ProcessCollisionStimUpdate** — the stim's per-tick driver: validates a weak reference, runs a 10-arg physics/collision query, records the impact event, refreshes position, stamps a new timestamp — the main "evaluate collision + emit event" tick function.
- `FUN_1028bd60` (line 446175) — **NotifyCollisionStimTargetChanged** — converts a weak ref to a smart pointer, checks validity predicates, cleans up on failure or forwards to a secondary listener — "stim target became invalid" handler.

### CPhysBulletHitStim / CPhysExplosionStim (0x102b3b00–0x102b4100)

- `FUN_102b3bd0` (line 472371) — **SetBulletHitImpactPosition** — writes a vec3 into the derived-class fields and sets a "has-position" flag.
- `FUN_102b3bf0` (line 472385) — **CopyPhysBulletHitStimData** — field-by-field `operator=` with proper refcounting on the two smart-pointer handle fields.
- `FUN_102b3d40` (line 472445) — **ConstructPhysBulletHitStim** — 10-arg constructor: entity handle, force/direction/magnitude triple, byte flag, two more refcounted handles, type tag, position vec3 — feeds the impulse-application dispatcher `FUN_102b7b80`.
- `FUN_102b4070` (line 472570) — **DestructPhysBulletHitStim** — releases two refcounted handles, resets vtable to shared base-class vtable.

### CRigidPhysOnDamageEvent / OnStateChangeEvent / OnDieEvent (0x102cf500–0x102d0800)

- `FUN_102cf520` (line 490299) — **SetDamageEventComponentRef** — releases prior held object, stores new one plus a scalar value — "attach colliding component" setter.
- `FUN_102cf580` (line 490320) — **CheckDamageImpactThreshold** — compares squared impact-vector length against a global threshold; gate feeding into damage-event dispatch.
- `FUN_102cf730` (line 490389) — **ConstructRigidPhysOnDamageEvent** — multi-base constructor setting two vtables and nulling three entity/component handles.
- `FUN_102cf910` (line 490496) — **ShouldTriggerDamageEvent** — predicate combining a "processed" flag, body index, force magnitude, and position, comparing against a stored threshold — gates whether a damage event should fire this tick.
- `FUN_102cfa10` (line 490544) — **TeardownRigidPhysOnDamageEvent** — releases the primary collision-component reference; the object's own destructor body.
- `FUN_102d0240` (line 490834) — **BroadcastRigidPhysStateChangeEvent** — posts a state/message, iterates a listener array notifying each — "state changed, tell everyone" for CRigidPhysOnStateChangeEvent.
- `FUN_102d0410` (line 490859) — **CastToRigidPhysOnDieEvent** — dynamic-cast-and-dispatch helper validating the RTTI chain against CRigidPhysOnDieEvent.
- `FUN_102d0750` (line 490997) — **EvaluateAndDispatchRigidPhysDamageState** — top-level per-tick orchestrator: branches into "fire now" (die-cast + broadcast) vs "defer" paths, ties damage/state-change/die dispatch together.

### CPhysCollisionQueryEvent (0x102fe200–0x102ff000)

- `FUN_102fec40` (line 521465) — **ConstructPhysCollisionQueryEvent** — stamps debug name `"PhysCollisionQueryEvent"`, magic id `0xf0000001`, stores two refcounted handles.
- `FUN_102fed10` (line 521511) — **DestructPhysCollisionQueryEvent** — releases the two handles, resets vtable to shared terminal base.
- `FUN_102fed70` (line 521542) — **CloneCollisionQueryEvent** — allocates + in-place constructs a copy, transfers a refcounted field.
- `FUN_102fee30` (line 521573) — **CopyCollisionQueryEventData** — field-by-field `operator=` companion to the clone helper.
- `FUN_102fe6a0` (line 521259) — **EvaluateCollisionQueryAndSpawnBulletHitStim** — computes impact speed, compares surface/material ids, calls `ConstructPhysBulletHitStim` to build/dispatch a bullet-hit stim from a raw Havok collision-query result — the bridge from raw physics query to game-layer event.

### CRigidGraphicComponent

- `FUN_101a78f0` (line 293444) — **TestBoundingBoxAgainstClipPlanes** — AABB-vs-frustum-planes test picking the box corner furthest along each plane normal, returns "outside" as soon as any plane test is positive. (Same function is also cross-referenced from the shape/broadphase side as a general AABB-vs-plane-array test — see `TestAabbOverlapsShapePlanes` below.)

---

### 3. Shape Entities & Trigger Components

Several nominal target classes (`IShapeComponent`, `CBasicShapeComponent`, `CSoundShapeComponent`,
`CSoundLineComponent`, `CBaseTriggerComponent`, `CProximityTriggerComponent`,
`CAvatarTriggerableComponent`) had **no domain code compiled adjacent to their RTTI getters** —
their real methods live elsewhere in the binary and were not chased further in this pass.

### Shape overlap tests

- `FUN_101a78f0` (line 293444) — **TestAabbOverlapsShapePlanes** — iterates a shape's plane array, tests an AABB's farthest corner against each plane; confirmed used by two independent broadphase/spatial-query call sites (lines 696585, 801346) testing octree-node AABBs against a shape.

### CBurnableRegion

- `FUN_104ccd30` (line 832532) — **ConstructCBurnableRegion** — installs a unique vtable, calls the shared base-entity init, lazily initializes a static default color/params block on first instance.

### CTriggerComponent — construction / destruction

- `FUN_1021ca20` (line 375591) — **ConstructTriggerComponent** — sets vtable pair, initializes two ref-counted smart-pointer members, a config-seeded byte flag, zeroes count/list fields.
- `FUN_1021caf0` (line 375639) — **DestructTriggerComponent** — releases members in reverse order, reassigns vtable down the inheritance chain.
- `FUN_1021d550` (line 376202) — **DeleteTriggerComponent** — scalar-deleting-destructor wrapper (calls `DestructTriggerComponent` then conditionally frees).

### CTriggerComponent — enter/exit notification fan-out

- `FUN_1021d2c0` (line 376029) — **NotifyTriggerEnter** — walks entity/listener array filtered by RTTI match, invokes vtable `+0x68` — "entity entered volume" callback.
- `FUN_1021d340` (line 376060) — **NotifyTriggerExit** — paired "left volume" callback via vtable `+0x6c`.
- `FUN_1021d3b0` (line 376090) — **CheckAnyEntityTriggerFlag** — ORs a per-entity bool query (vtable `+0x64`) — "is any contained entity still satisfying the trigger condition."
- `FUN_1021da00` (line 376326) — **NotifyEntitiesTriggerEnter** — batch driver for the enter fan-out, skipping already-flagged entities.
- `FUN_1021dcc0` (line 376456) — **NotifyEntitiesTriggerExit** — batch driver for the exit fan-out.

### CTriggerComponent — occupant registry

- `FUN_1021dd70` (line 376511) — **RemoveEntityFromTriggerRegistry** — searches the global per-trigger occupant vectors, erases the entity, clears the "inside trigger" bit — cleanup on entity destroy/deactivate while inside a trigger.
- `FUN_1021dea0` (line 376574) — **ClearAllTriggerOccupants** — clears the "inside trigger" flag on every global occupant then empties the list — level-unload/reset-all-triggers routine.
- `FUN_1021df40` (line 376607) — **IsWithinTriggerRadius** — squared-distance proximity/radius test scaled by an LOD ratio, consistent with a trigger volume's shape check.

### CTriggerComponent — event firing

- `FUN_1021d860` (line 376216) — **FireTriggerParticleEvent** — builds and dispatches a `CParticleFXEvent` when a trigger activates.
- `FUN_1021d910` (line 376257) — **FireTriggerDestroyEvent** — builds and dispatches a `CDestroyEvent` as a trigger consequence.

### CTriggerEvent

- `FUN_102dc560` (line 497922) — **ConstructTriggerEvent** — builds RTTI name `"TriggerEvent"`, initializes 64-bit source id, owner smart pointer, enter/exit state flag.
- `FUN_102dc6e0` (line 498011) — **DispatchTriggerExitEvent** — unlinks the occupant-list node for the entity, decrements occupant count, constructs/dispatches a `CTriggerEvent` with state flag `2` (exit).
- `FUN_102dcb40` (line 498195) — **DispatchTriggerEnterEvent** — inserts a new occupant node if not tracked, constructs/dispatches a `CTriggerEvent` with state flag `1` (enter). Together these confirm the state-flag encoding: 1=Enter, 2=Exit.

### CTriggerSimpleEvent

- `FUN_1052a7f0` (line 888877) — **IsTriggerSimpleEvent** — RTTI type-check/downcast helper; call sites read a name-string field and compare against literals like `"enter"`.

### CTriggerEnableEvent

- `FUN_105e1040` (line 985716) — **ConstructTriggerEnableEvent** — sets two vtables, zeroes member dwords, defaults an enable-byte flag to `1`.
- `FUN_105e1080` (line 985736) — **DestructTriggerEnableEvent** — decrements a contained object's refcount (freeing at zero), sets terminal base vtable.
- `FUN_105e1120` (line 985763) — **DeleteTriggerEnableEvent** — scalar-deleting-destructor wrapper.
- `FUN_105e1a50` (line 985933) — **NotifyEntitiesInTriggerRange** *(tentative)* — fetches an entity-range accessor and forwards bounds into `DispatchToEntitiesInRange`.
- `FUN_105e12e0` (line 985779) — **DispatchToEntitiesInRange** *(tentative, possibly generic container glue)* — loops an index range invoking a per-index target callback.

### CTriggerChangeCountEvent

- `FUN_107b2f40` (line 1246257) — **ConstructTriggerChangeCountEvent** — stores entity/trigger name, `selType` (offset 0x40), defaults `nQuantity` (offset 0x44) to `1`.
- `FUN_107b3020` (line 1246275) — **CloneTriggerChangeCountEvent** — allocates and copies name/`selType`/`nQuantity` — `Clone()` override.
- `FUN_107b30a0` (line 1246308) — **RegisterTriggerChangeCountEventReflection** — one-time reflection registration of `"selType"` enum (`"Invalid"`/.../`"Substract"`) and `"nQuantity"` int property.

### CVehicleEventLandTrigger

- `FUN_1059a6e0` (line 949565) — **ConstructVehicleEventLandTrigger** — sets vtable, initializes three fields to a shared default constant, clears a byte flag.
- `FUN_1059a6b0` (line 949549) — **DestructVehicleEventLandTrigger** — resets vtable, teardown call, conditional free.
- `FUN_1059a8b0` (line 949601) — **FireVehicleLandTriggerEvent** — verifies target is-a `CTriggerEvent`, packs a message and dispatches through the target's listener-list vtable slot — broadcasts the vehicle-landed event to a trigger listener.

---

### 4. Vehicle Physics

`CVehicleWheeledPhysComponent`/`CVehicleFloatingPhysComponent`/`CVehicleParagliderPhysComponent`/
`CVehicleCopterPhysComponent` have **no unique code found** anywhere in the decompile outside their
`GetClassInfo` getters (all vtables are anonymous `DAT_xxxxxxxx`, no other code references these
class names) — they appear to add no attributable unique members beyond inherited
`CVehiclePhysComponent` behavior in this decompile. `CVehicleTypeWheeled`'s address neighborhood is
dominated by an unrelated player-enter-vehicle camera/sound state machine (AI/UI logic) and was
excluded.

### CVehicleType / CVehicleTypeFlying (config copy, constructors)

- `FUN_10565040` (line 920471) — **CopyVehicleTypeBaseData** — copies handling limits, mass table, name-hash range, LOD flags — `CVehicleType::operator=`/CopyFrom.
- `FUN_10565450` (line 920633) — **CopyVehicleTypeFlyingData** — calls the base copy then copies 16 more flight-tuning dwords (lift/thrust/altitude-limit fields).
- `FUN_10565550` (line 920660) — **BuildWeaponMountSwapList** — builds replacement resource handles per weapon mount — per-seat weapon list for `CArmedVehicle`.
- `FUN_10565690` (line 920732) — **UpdateWeaponMountVisualsForWear** — checks wear level per turret/weapon slot, refreshes damaged weapon-mount visuals.
- `FUN_10565c10` (line 920849) — **ConstructVehicleTypeFlying** — sets vtable, allocates and initializes an 8-byte sub-object.
- `FUN_10565c80` (line 920879) — **DestructVehicleTypeFlying** — releases the sub-object; virtual/scalar destructor.

### CVehicleTypeEngine (fuel, RPM, audio, revive/ragdoll hooks)

- `FUN_105d2290` (line 977663) — **ConsumeEngineFuel** — depletes the fuel tank by `rate * dt`, clamped, with a "no-consumption" mode check.
- `FUN_105d2310` (line 977694) — **UpdateEngineRpmAndFuelState** — computes target RPM/throttle from speed vs. gear thresholds, special-cases handbrake/out-of-fuel, pushes result to engine sound/force update.
- `FUN_105d2720` (line 977852) — **GetCachedGroundMaterialFlags** — looks up and caches surface-material boolean flags at a world position (e.g. underwater/no-drive zones).
- `FUN_105d2910` (line 977955) — **NotifyEngineFaultEvent** — sets a fault byte, fires a hashed string event on abnormal engine state (failure/backfire notification).
- `FUN_105d2b50` (line 978086) — **ClampEngineOutputNearBoundary** — clamps throttle-limit by distance to a cached reference point or by accumulated damage — engine power governor near restricted areas.
- `FUN_105d2ef0` (line 978183) — **TriggerRagdollOnVehicleDestruction** — fires literal event `"start_ragdoll"` once when the vehicle "should ragdoll" — ejects/ragdolls the driver when the vehicle is destroyed.
- `FUN_105d2e30` (line 978157) — **DestructVehicleTypeEngine** — frees an inline array, calls base destructor.
- `FUN_105d2fd0` (line 978238) — **HandleReviveEnabledQuery** — answers whether a downed occupant can be revived in-vehicle (`CGRQueryIsReviveEnabled`).
- `FUN_105d3180` (line 978344) — **ConstructVehicleTypeEngine** — zero/`0xffffffff`-initializes ~20 fields, calls nested range-init helpers.
- `FUN_105d3210` (line 978373) — **LoadEngineAudioBankParams** — reads max-RPM/redline, looks up a hashed sound-bank parameter — engine sound tuning init.

### CVehiclePhysComponent — collision impact / sound response

- `FUN_1052f320` (line 891538) — **RegisterCollisionSoundProperties** — one-time registration of `fSmallCollisionSpeed`/`fMediumCollisionSpeed`/`fBigCollisionSpeed`/`sndSmallCollision`/`sndMediumCollision`/`sndBigCollision` — the collision-speed→sound-cue table for vehicle impacts.
- `FUN_1052f020` (line 891349) — **StopVehicleCollisionSoundsCallback** — stops/releases the three small/medium/big collision sound instances (shutdown callback registered by `RegisterCollisionSoundProperties`).
- `FUN_1052fb00` (line 891924) — **ClearCollisionSoundHandles** — releases the 3-element sound-handle array.
- `FUN_1052fb10` (line 891935) — **ProcessCollisionImpactSeverity** — buckets an impact speed against small/medium/big thresholds, plays the matching sound, fires `"bigAnimalCollision"` for the top bucket — central vehicle-collision-response dispatcher.
- `FUN_1052f760` (line 891758) — **PlayCollisionImpactSound** — computes relative impact velocity/position, drives impact FX/sound spawn with collision normal and speed.
- `FUN_1052f9c0` (line 891870) — **CheckCollisionBelowVehicleBounds** — gates the impact-sound trigger to avoid double-firing per contact.
- `FUN_1052f640` (line 891698) — **CacheAnimalCollisionClassInfo** — caches `CBtzHybridAnimal` RTTI info and pre-creates a `"CreatureImpactFxEvent"` for fast animal-collision checks.
- `FUN_1052ef60` (line 891319) — **DestructVehicleFlyingPhysComponent** — multi-stage virtual-destructor chain releasing a sub-object and owner reference.

### CVehicleNetworkComponent — seat / occupant replication

- `FUN_10690700` (line 1084083) — **BuildSeatChangeEventData** — builds "enter"/"leave" network event payloads for a seat occupancy change.
- `FUN_10690810` (line 1084140) — **NotifySeatOccupantChanged** — fires the seat-occupant-changed replication notification.
- `FUN_10690890` (line 1084167) — **RegisterOccupantsForReplication** — brings newly-added occupants under network sync.
- `FUN_10690980` (line 1084222) — **ConstructVehicleNetworkComponent** — initializes the occupant array (cap 0xf) and state bytes.
- `FUN_10690a80` (line 1084254) — **DestructVehicleNetworkComponent** — releases the occupant array and two auxiliary dynamic arrays.
- `FUN_10690cd0` (line 1084387) — **SyncEmptySeatEvents** — dispatches seat-change events for empty seats to keep replicated state consistent.
- `FUN_10690de0` (line 1084446) — **SpawnMissingSeatOccupants** — backfills empty seats with new occupant handles (e.g. spawning driver/gunner NPCs).
- `FUN_10691050` (line 1084549) — **HandleVehicleEnteredNetworkSync** — backfills missing occupants and pushes updated occupant state when a vehicle becomes network-relevant.
- `FUN_106910f0` (line 1084581) — **SetOwningArmedVehicleRef** — wires the network component to its owning `CArmedVehicle`; auto-fills unmanned armed vehicles with NPC occupants.

### Havok wheel raycast (hkpVehicleRaycastWheelCollide / hkpRejectRayChassisListener)

- `FUN_10c55b50` (line 1958150) — **ConstructRejectRayChassisListener** — constructs the ray-vs-own-chassis rejection filter used during wheel raycasts.
- `FUN_10c55b80` (line 1958165) — **DestructRejectRayChassisListener** — destructor counterpart.
- `FUN_10c55ba0` (line 1958178) — **ShouldRejectChassisRay** — compares ray-hit entity id against the listener's own chassis id; the actual raycast filter callback so wheel rays ignore the vehicle's own chassis shape.
- `FUN_10c55bd0` (line 1958201) — **ConstructVehicleRaycastWheelCollide** — top-level constructor for the Havok raycast-wheel-collision detector used by wheeled vehicles.
- `FUN_10c55c00` (line 1958219) — **CollectWheelRaycastResult** — fetches a wheel's raycast hit (position/normal/fraction), appends it to the per-wheel result array.
- `FUN_10c55cd0` (line 1958261) — **DestructVehicleRaycastWheelCollide** — releases the per-wheel result array and reject-ray listener.
- `FUN_10c55d20` (line 1958288) — **ComputeAggregateWheelAABB** — merges every wheel's individual AABB into one combined bounding box — builds the broadphase query volume for the vehicle's raycast wheels.

---

### 5. Havok Engine Layer — Broad-Phase Collision Detection / World / Ragdoll Constraints / Character Rigid Body

This is third-party Havok SDK code; labeling relies on unambiguous `hkXxx::vftable` store
instructions as ground truth, per the destructor/constructor idiom documented at the top of this
file.

### Broad-phase collision detection (hkpCd*/hkpAll* collectors, hkBaseObject)

- `FUN_1037ee90` (line 607361) — **hkBaseObject_Destructor** — scalar-deleting-dtor idiom (vtable store + conditional `operator delete` via `FUN_10ad111e`).
- `FUN_10381050` (line 608738) — **hkpBroadPhaseCastCollector_Destructor** — identical scalar-deleting-dtor pattern.
- `FUN_103817c0` (line 609120) — **hkpCdBodyPairCollector_Destructor** — pooled-allocator destructor (returns object to a `hkThreadMemory` per-type free list).
- `FUN_10381990` (line 609203) — **hkpCdPointCollector_Destructor** — same pool-return destructor pattern, different free-list slot.
- `FUN_10381e20` (line 609348) — **hkDefaultError_Constructor** — initializes refcount, error-id `0x80000000`, two user-data fields.
- `FUN_10383420` (line 610371) — **CheckBodyPairCollisionFilterFlag** — stack-constructs an `hkpFlagCdBodyPairCollector`, dispatches through a per-layer/material collision-table function pointer.
- `FUN_103844e0` (line 610996) — **hkBaseObject_Destructor (variant)** — frees an owned dynamic array first, then chains to `hkBaseObject::vftable`.
- `FUN_10386230` (line 612252) — **CollectAllPointsForShapeQuery** — stack-allocates `hkpAllCdPointCollector`, de-duplicates hits by owner id keeping minimum distance.
- `FUN_103867f0` (line 612469) — **CheckEntityPairCollisionFilter** — entity-vs-entity sibling of `CheckBodyPairCollisionFilterFlag`.
- `FUN_10389c60` (line 614615) — **hkThreadMemory_Destructor** — sets vtable, teardown helper, conditional free via registered thread-memory free function.
- `FUN_10393d80` (line 622345) — **hkBaseObject_Destructor (variant)** — clears an embedded sub-object's vtable slot before resetting the outer vtable.
- `FUN_10395b50` (line 623414) — **hkpAllCdPointCollector_Destructor** — frees the owned point-hit array, chains vtable to `hkpCdPointCollector`, returns to its free list.
- `FUN_10396180` (line 623614) — **SampleGroundContactPoints** — stack-scoped `hkpAllCdPointCollector` gathering ground/terrain AABB overlap points for a character-controller step.
- `FUN_10396480` (line 623736) — **SampleGroundAndCeilingContacts** — companion of the above: two back-to-back ground + ceiling probe queries.

### MOPP code / shape containers (hkpMoppCode, hkpShapeContainer)

- `FUN_103a1640` (line 630809) — **hkpMoppCode_Destructor** — frees the owned MOPP bytecode buffer, chains vtable to `hkBaseObject`.
- `FUN_103a8880` (line 634919) — **CreateMoppCodeObject** — heap-allocates and initializes a fresh `hkpMoppCode`, inserts it into a MOPP tree structure.
- `FUN_103b0190` (line 640090) — **hkpShapeContainer_Destructor** — canonical scalar-deleting-dtor idiom.
- `FUN_103b0210` (line 640141) — **hkpSingleShapeContainer_Destructor** — releases the single contained shape's reference, resets vtable to base `hkpShapeContainer`.
- `FUN_103b02b0` (line 640198) — **Shape_Destructor (embeds hkpSingleShapeContainer)** — releases a child-shape container member — a decorator/transform shape that owns a single child shape.

### Listeners (hkpConstraintListener / hkpCollisionListener)

- `FUN_103aaea0` (line 636584) — **hkpConstraintListener_Destructor** — base-interface scalar-deleting-dtor tail.
- `FUN_103aaec0` (line 636598) — **CompositeWorldListener_Constructor** — multiple-inheritance constructor wiring six distinct listener-interface vtable slots on one object (including `hkpConstraintListener`) — the engine's internal composite event router registered with `hkpWorld`.
- `FUN_103aafd0` (line 636631) — **CompositeWorldListener_Destructor** — teardown counterpart of the above.
- `FUN_103ade90` (line 638790) — **hkpCollisionListener_Destructor** — canonical scalar-deleting-dtor idiom.

### Pairwise collision filter queries

- `FUN_103ad0e0` (line 638310) — **CheckShapePairCollisionFilter** — stack-builds `hkpFlagCdBodyPairCollector`, dispatches through a per-layer collision-table entry keyed off shape info.
- `FUN_103ad170` (line 638339) — **CheckShapePairCollisionFilter (indirect-lookup variant)** — resolves the shape's owning body/entity first before running the same filter dispatch.

### hkpWorld / hkpPhysicsSystem / hkpWorldCinfo lifecycle

- `FUN_10ba9610` (line 1846658) — **hkpWorld_Constructor** — bulk-initializes ~20 broad-phase AABB-extent slots to the "empty" sentinel — `hkpWorld`'s spatial partition setup.
- `FUN_10ba9740` (line 1846720) — **hkpWorld_Destructor** — releases an owned list into the `hkThreadMemory` free-list.
- `FUN_10bae250` (line 1850356) — **hkpPhysicsSystem_Constructor** — zero-initializes entity/constraint/action array descriptors, sets an "active" flag byte.
- `FUN_10bae2a0` (line 1850383) — **hkpPhysicsSystem_Destructor** — releases each contained entity reference before freeing the array.
- `FUN_10bb25c0` (line 1853563) — **hkpWorldCinfo_Constructor** — fills default world-creation parameters (broadphase size `0x400`, gravity/collision-tolerance defaults) — matches the well-known `hkpWorldCinfo` default constructor.

### hkpEntity / hkpRigidBody lifecycle

- `FUN_10ba6820` (line 1844794) — **hkpRigidBody_GetVTable** — static RTTI/vtable accessor (invokes the hkpEntity constructor as a side-effect dependency init).
- `FUN_10ba6850` (line 1844805) — **hkpRigidBody_Destructor (scalar-deleting wrapper)** — calls hkpEntity teardown then conditionally pool-frees.
- `FUN_10ba68c0` (line 1844818) — **hkBaseObject_Destructor (chain tail)** — canonical scalar-deleting-dtor idiom, reused as terminal base-class step for several derived classes.
- `FUN_10bb2e30` (line 1853963) — **hkpEntity_Constructor (simple overload)** — default-initializes damping/friction/motion fields, embedding an `hkpMaxSizeMotion` sub-object directly.
- `FUN_10bb2f40` (line 1854009) — **hkpEntity_Constructor (with motion-type selection)** — placement-constructs the embedded motion sub-object as one of `hkpSphereMotion`/`hkpStabilizedSphereMotion`/`hkpBoxMotion`/`hkpStabilizedBoxMotion`/`hkpKeyframedRigidMotion`/`hkpFixedRigidMotion`/`hkpThinBoxMotion`/`hkpCharacterMotion` based on a type byte — `hkpEntity`'s cinfo-driven motion-type dispatch.
- `FUN_10bb3780` (line 1854384) — **hkpEntity_Destructor** — releases constraint-listener array, master/slave and simulation-island bookkeeping arrays.
- `FUN_10bb38f0` (line 1854441) — **hkpEntity_Destructor (scalar-deleting wrapper)** — calls the above then conditionally pool-frees.
- `FUN_10bb3920` (line 1854456) — **hkpRigidBody_Destructor** — re-asserts the derived vtable then calls `hkpEntity_Destructor` — the real body of the RigidBody destructor.

### Ragdoll constraint system (hkpRagdollConstraintData + prepareSystemForRagdoll helpers)

- `FUN_10bb7480` (line 1857030) — **hkpRagdollConstraintData_Destructor** — releases 3 owned sub-constraint-data references (twist/plane/cone limit constraints).
- `FUN_10bb7530` (line 1857087) — **hkpRagdollConstraintData_Constructor** — zero/identity-initializes ~20 fields including three quaternion-like twist/plane/cone limit blocks seeded to `1.0`.
- `FUN_10c3baa0` (line 1941302) — **GetConstraintPivotAndAxisForRagdoll** — extracts pivot-A/pivot-B vectors for known constraint types (hinge/limited-hinge/ragdoll/prismatic); logs `"Unsupported type of constraint in prepareSystemForRagdoll()"` for others (matches known `hkpConstraintUtils.cpp` source).
- `FUN_10c3bbe0` (line 1941346) — **GetConstraintMotorAxisForRagdoll** — extracts motor twist axis for ball-and-socket/ragdoll constraints, logs `"This type of constraint does not have motors"` otherwise.
- `FUN_10c3bd00` (line 1941384) — **ValidateAndAlignRagdollConstraintPivot** — verifies child-body pivot alignment (else logs a diagnostic), interpolates/blends the two bodies' constraint frames — the actual `prepareSystemForRagdoll()` per-constraint work function.

### Character rigid body (hkpCharacterRigidBody / hkCharacterRigidBodyCollisionListener)

- `FUN_10c47890` (line 1949003) — **hkpCharacterRigidBody_Destructor** — releases an owned collision-filter/listener sub-object and two more owned members.
- `FUN_10c47a40` (line 1949110) — **hkpCharacterRigidBody_Constructor** — bulk-copies fields out of a cinfo-like struct (shape, mass, up-vector, max-slope) — matches `hkpCharacterRigidBody(const hkpCharacterRigidBodyCinfo&)`.
- `FUN_10c488a0` (line 1949704) — **hkCharacterRigidBodyCollisionListener_Constructor** — explicit multiple-inheritance vtable layout (secondary slot stamped to `hkpCollisionListener::vftable`, then re-stamped to the MI-adjusted derived thunk) — the character controller's ground/wall collision callback object.

### hkaRagdollInstance lifecycle

- `FUN_10c6bd80` (line 1972229) — **hkaRagdollInstance_Constructor** — binds skeleton + rigid-body array + constraint array pointers, copies an optional bone-index mapping array — matches `hkaRagdollInstance(skeleton, rigidBodies, constraints)`.
- `FUN_10c6be60` (line 1972281) — **hkaRagdollInstance_Destructor** — releases each owned `hkpConstraintInstance` reference.

---

### 6. Havok Engine Layer — RayCast Query API / Collision Shapes / Collision Filters

### RayCast query API (Dunia-side wrappers around Havok raycasts — game-callable)

- `FUN_10b6a6a0` (line 1803519) — **PerformRayCast** — tagged `"TtRayCast"`; builds a ray-query descriptor and dispatches via the broadphase world vtable `+0x54` — core single-ray game-query entry point (likely AI line-of-sight / bullet hit-test root).
- `FUN_10b6a7b0` (line 1803586) — **PerformRayCastCached** — tagged `"TtRayCstCached"`; cached variant carrying an extra cache-hint param, used by repeated-frame raycasts (e.g. camera collision).
- `FUN_10b6a8c0` (line 1803654) — **PerformRayCastGroup** — tagged `"TtRayCastGroup"`; computes a merged AABB over an array of ray segments, loops `PerformRayCastCached` per ray — batched raycast entry point.
- `FUN_10b6ac50` (line 1803833) — **PerformRayCastFSP** — tagged `"TtRayCastFSP"`; larger result-struct "FSP" variant (likely first-shape-pierced / sub-part filter flavor).
- `FUN_10ba2890` (line 1842277) — **PerformWorldRayCastQuery** — tagged `"TtCollQueryWorldRayCast"`; installs `hkCpuWorldRayCastCollector::vftable`, iterates a ray array via the broadphase world vtable — world-level (broadphase) collision-query entry point.
- `FUN_10ba2a00` (line 1842369) — **PerformShapeRayCastQuery** — tagged `"TtCollQueryShapeRayCast"`; per-ray transforms into shape space and performs triangle-level ray/shape intersection directly — narrow-phase shape-level raycast query.
- `FUN_10f4a2b0` (line 2515307) — **PerformRayCastSimplified** — tagged `"TtRayCastSimpl"`; leaner sibling of `PerformRayCast` with a smaller result struct.
- `FUN_10f4a3b0` (line 2515373) — **PerformRayCastCachedSimplified** — tagged `"TtRayCstCchSim"`; cached counterpart of the simplified variant.
- `FUN_10f4a4b0` (line 2515442) — **PerformRayCastGroupSimplified** — tagged `"TtRayCstGrpSim"`; batched loop built on the simplified query family.
- `FUN_10385470` (line 611616) — **PerformCachedRayCastAgainstEntity** — stack-constructs an `hkpWorldRayCaster`, calls `PerformRayCastCached`, filters/dedupes the hit list — Dunia entity-level cached raycast wrapper.
- `FUN_10387fd0` (line 613475) — **PerformCachedRayCastAgainstObjectList** — same `hkpWorldRayCaster` pattern but iterates an explicit fixed-stride object array via each object's own hit-test vtable slot — sector/object-list cached raycast wrapper.

### Collision shape classes (constructors/destructors, ground-truthed via `hkpXxxShape::vftable` stores)

- `FUN_10b68140` (line 1801820) — **hkpSphereShape_Constructor** — type tag `2`, radius from param.
- `FUN_10b68170` (line 1801835) — **PerformSphereShapeRayCast** — tagged `"TtrcSphere"`; forwards to ray-vs-sphere intersection math.
- `FUN_10b68590` (line 1801981) — **hkMoppBvTreeShapeBase_Destructor** — releases child-shape refcount.
- `FUN_10b685f0` (line 1802005) — **hkpMoppBvTreeShape_Constructor** — copies child AABB/offset fields from the wrapped shape.
- `FUN_10b703b0` (line 1807284) — **hkpMoppBvTreeShape_Destructor** — three-stage teardown (single-shape-container, MOPP-code, base).
- `FUN_10b704a0` (line 1807348) — **hkMoppBvTreeShapeBase_Constructor** — copies AABB extents from the MOPP-code object.
- `FUN_10b70500` (line 1807372) — **hkpMoppBvTreeShape_Constructor2** — 2-arg convenience overload calling the base ctor.
- `FUN_10b6b670` (line 1804332) — **hkpCapsuleShape_Constructor** — type tag `6`, copies both end-points + radius.
- `FUN_10b6c6a0` (line 1804972) — **hkpBoxShape_Constructor** — type tag `5`, half-extents + derived inscribed-sphere radius.
- `FUN_10b6c720` (line 1805006) — **PerformBoxShapeRayCast** — tagged `"TtrcBox"`; slab-test ray-vs-AABB intersection.
- `FUN_10b6db00` (line 1805705) — **hkpCylinderShape_Constructor** — type tag `3`, copies both end-points.
- `FUN_10b6dba0` (line 1805741) — **hkpCylinderShape_Constructor2** — abbreviated cylinder ctor (type-tag-only path).
- `FUN_10b6ee40` (line 1806351) — **hkpTriSampledHeightFieldCollection_Constructor** — wraps a sampled heightfield object — terrain collision-collection wrapper.
- `FUN_10b6ee90` (line 1806373) — **hkpTriSampledHeightFieldCollection_Destructor** — releases wrapped heightfield's refcount.
- `FUN_10b6ef60` (line 1806434) — **GetHeightFieldTriangleAtIndex** — builds a scratch triangle from a terrain grid cell's height samples — terrain-to-triangle accessor for heightfield collision queries.
- `FUN_10b6f9d0` (line 1806852) — **PerformHeightFieldRayCastCollect** — installs `nomadPhysHeightFieldRayHitCollector::vftable` (Dunia-custom, non-stock-Havok collector) — confirms internal engine codename "nomad" for the physics layer.
- `FUN_10b6fa30` (line 1806876) — **hkpTriSampledHeightFieldBvTreeShape_Constructor** — terrain BV-tree shape root.
- `FUN_10b75850` (line 1810570) — **GetSimpleMeshShapeTriangleAt** — builds a scratch triangle by indexing a simple-mesh shape's vertex/index buffers.
- `FUN_10b7cdd0` (line 1815490) — **GetMeshShapeTriangleAt** — builds a scratch triangle from an `hkpMeshShape` sub-part's packed vertex/index data (with welding-flag lookup).
- `FUN_10b7dcb0` (line 1816289) — **GetExtendedMeshShapeTriangleAt** — decodes packed/quantized vertices (8-bit or 16-bit index paths) from an `hkpExtendedMeshShape` sub-part — main static-geometry triangle accessor.
- `FUN_10b73df0` (line 1809366) — **hkpListShape_Constructor** — allocates the child-shape-pointer array.
- `FUN_10b73e80` (line 1809403) — **hkpListShape_ReinitVTable** — post-load/placement-reinit helper, type tag `10`.
- `FUN_10b73eb0` (line 1809418) — **hkpListShape_Destructor** — releases every child shape's refcount, frees the pointer array.
- `FUN_10b74e80` (line 1810235) — **hkpConvexVerticesShape_Constructor** — type tag `7`, bulk-copies the vertex-plane array.
- `FUN_10b75140` (line 1810328) — **hkpConvexVerticesShape_Destructor** — releases connectivity-data refcount, frees plane/vertex arrays.
- `FUN_10b759e0` (line 1810650) — **hkpSimpleMeshShape_Constructor** — zero-inits vertex/triangle/material dynamic arrays.
- `FUN_10b75eb0` (line 1810944) — **hkpConvexTranslateShape_Constructor** — type tag `0xc`, translation offset + wrapped child shape.
- `FUN_10b76020` (line 1811004) — **PerformConvexTranslateShapeRayCast** — tagged `"TtrcConvTransl"`; un-translates the ray into child-shape space then forwards.
- `FUN_10b761b0` (line 1811101) — **hkpTransformShape_Constructor** — type tag `0x1c`, wraps child shape + full transform.
- `FUN_10b7c270` (line 1814958) — **hkpMultiRayShape_Constructor** — type tag `0x17`; appends ray segments into a dynamic array — used for e.g. wheel-suspension/multi-probe raycast shapes.
- `FUN_10b7d060` (line 1815658) — **hkpMeshShape_Constructor** — default identity scale, zero-inits sub-part arrays.
- `FUN_10b7d0c0` (line 1815684) — **hkpMeshShape_ReinitVTable** — post-load materialize helper, fixes sub-part welding flags/type tag.
- `FUN_10b7e650` (line 1816803) — **hkpExtendedMeshShape_Constructor** — main static-geometry collision-mesh constructor.
- `FUN_10b7e710` (line 1816853) — **hkpExtendedMeshShape_ConstructorFromSource** — deep-copy variant: bulk-copies index buffer, material array, per-sub-part records — builds the runtime collision mesh from baked level data.
- `FUN_10b7e980` (line 1816977) — **hkpExtendedMeshShape_Destructor** — releases every triangle/shape sub-part's child-shape refcount.

### Collision filters / groups (gameplay collision-layer system)

- `FUN_10b69480` (line 1802494) — **hkpMoppModifier_Constructor** — abstract base for MOPP terminal modifiers.
- `FUN_10b69500` (line 1802519) — **hkpMoppModifier_Destructor** — calls derived teardown then releases via refcounted-free helper.
- `FUN_10b69570` (line 1802534) — **hkpCollidableCollidableFilter_Constructor**.
- `FUN_10b69590` (line 1802548) — **hkpRayCollidableFilter_Constructor**.
- `FUN_10b695b0` (line 1802562) — **hkpShapeCollectionFilter_Constructor**.
- `FUN_10b695d0` (line 1802576) — **hkpRayShapeCollectionFilter_Constructor**.
- `FUN_10b695f0` (line 1802590) — **CompositeCollisionFilter_Destructor** — tears down all four filter-interface vtable slots — shared teardown for multi-interface collision-filter objects (e.g. `hkpGroupFilter`).
- `FUN_10b696a0` (line 1802629) — **hkpNullCollisionFilter_GetVTable** — RTTI accessor for the "collide with everything" filter.
- `FUN_10b69800` (line 1802743) — **hkpGroupFilter_GetVTable** — RTTI accessor.
- `FUN_10b6a240` (line 1803259) — **hkpGroupFilter_Constructor** — initializes a 14-word group-vs-group collision bitmask table to all-`0xffffffff` — Dunia's collision-layer matrix init.
- `FUN_10b6a2b0` (line 1803291) — **hkpGroupFilter_Destructor** — delegates to `CompositeCollisionFilter_Destructor`.
- `FUN_10b6a1a0` (line 1803216) — **EnableCollisionsBetweenGroups** — sets reciprocal bits in the group bitmask table for two group indices — gameplay collision-layer enable API.
- `FUN_10b6a200` (line 1803232) — **DisableCollisionsBetweenGroups** — clears reciprocal bits across all 14 groups for two group masks — gameplay collision-layer disable API.
- `FUN_10b69fc0` (line 1803141) — **IsCollisionEnabledBetweenLayers** — decodes packed layer IDs (group index + sub-layer bits), tests the group bitmask plus special-case bits — core layer-vs-layer collision test used by the raycast query wrappers.
- `FUN_10b69df0` (line 1803031) — **hkpCollisionFilterList_GetVTable** — RTTI accessor for the filter-list-composite filter.
- `FUN_10b79320` (line 1812965) — **CollisionQueryFilter_Constructor** — bootstraps a composite filter object's four interface slots before overwriting with the abstract `hkpCollisionFilter` base — shared filter-object bootstrap used by the `TtCollQuery*` raycast query setup path.

---

### Summary

| Cluster | Count |
|---|---|
| Game-layer Physics Components | 26 |
| Physics Stims & Damage Events | 25 |
| Shape Entities & Trigger Components | 26 |
| Vehicle Physics | 39 |
| Havok Broad-Phase / World / Ragdoll Constraints / Character Rigid Body | 53 |
| Havok RayCast Query API / Shapes / Filters | 61 (2 deduped against the broad-phase cluster) |
| **Total (deduplicated)** | **~228** |

---


## Rendering / Graphics (background sweep)

Source: `Avatar_Dunia_Retail_1.02_decrypted.dll_FULL_DECOMPILE.txt` (~2.61M lines).
Method: five parallel sub-sweeps (Shader/Effect, Texture, Mesh/VertexBuffer,
Camera/Viewport/Device, Particle/Lighting/Material/LOD), merged below. Pure
RTTI-name getter thunks (`FUN_XXXXXXXX` that just force-init a class-id and
return `&DAT_...`) were used only as anchors/vocabulary per instructions and
are not separately listed as findings.

**Cross-cutting engine-wide finding (from the Shader/Effect slice, relevant to
all other slices):** this DLL does **not** use the stock D3DX9 Effects
framework — no `ID3DXEffect`, `SetTechnique`, `BeginPass`, `CommitChanges`,
`D3DXCreateEffectFromFile`, `SetVertexShaderConstantF` etc. appear anywhere.
Ghidra also never resolves `IDirect3DDevice9`/vertex-buffer/texture COM
vtable calls to named D3D9 methods (no literal `CreateVertexBuffer`,
`DrawIndexedPrimitive`, `SetStreamSource`, `SetViewport`, `CreateDevice`,
etc.), so "grep for the D3D9 API name" mostly fails across every slice.
Instead Dunia implements everything through: (1) a custom
shader-parameter-provider registry (`*ParameterProvider` classes registering
named constants/samplers into a shared RB-tree table via
`FUN_10181ca0`/`FUN_10181d70`), (2) a text-format render-state-block
"compiled .fx pass" parser/compiler, and (3) profiler/debug-zone strings that
literally spell out `Class::Method` — which turned out to be the single
strongest anchor for finding real logic (e.g.
`"CSceneParticleEmitterRenderer::Render"`, `"CClusterRenderer::CreateInstancingRenderJobs"`,
`"CSceneRenderer::PrepareFrameGraph"`, `"CRealTreeRenderer::ProcessBatches"`).

Five (5) addresses were independently found and labeled consistently by two
slices (same function, same inferred purpose): `FUN_10eec050`, `FUN_10eec140`
(D3D10 compiler dynamic-export loaders — Shader & Camera slices),
`FUN_1046bbf0` (viewport shader-parameter registration — Shader & Camera
slices), `FUN_10086190` (CSceneGeometry property registration — Shader &
Mesh slices), `FUN_10085d50` (CSceneDecalMaterial shader-param registration —
Shader & Particle/Material slices). Listed once below, in their primary
cluster.

---

### Shader / Effect / Technique / D3D Pipeline-State

Scope note: no D3DX9 Effects framework in this binary. Dunia implements a
custom **shader-parameter-provider / pass-render-state system**: every
renderable "material-ish" C++ class statically registers a table mapping
shader-constant/texture-sampler names (identical to HLSL cbuffer member
names, e.g. `ViewProjectionMatrix`, `LightPositionWS`, `DiffuseTexture1`) to
byte offsets in its own instance data, via a shared red-black-tree-backed
registry. Separately, a large render-state-block parser turns text-format
pass state-assignment names (`ZEnable`, `SrcBlend`, `StencilFunc`,
`VertexShader`, `PixelShader`, ...) into a packed D3D9 pipeline-state
bitfield — i.e. this DLL's own reimplementation of an `.fx`
`pass { state = value; }` block compiler.

#### Pass / technique render-state block parser ("compiled .fx pass" system)

- `FUN_10eecbc0` (line 2466916) — **ParsePassRenderStateBlock** — walks a list of name/value pairs from a technique "pass" definition and string-matches each name against the full D3D9 render-state vocabulary (`ZCullForwardLimit`, `ZCullBackLimit`, `AlphaBlendEnable`, `ZWriteEnable`, `ZEnable`, `AlphaTestEnable`, `AlphaToCoverageEnable`, `StencilEnable`, `CullMode`, `ColorWriteEnable`, `SrcBlend`, `DestBlend`, `BlendOp`, `SeparateAlphaBlendEnable`, `SrcBlendAlpha`, `DestBlendAlpha`, `BlendOpAlpha`, `ZFunc`, `StencilFail/ZFail/Pass/Func/Ref/Mask/WriteMask`, `AlphaRef`, `DepthBias`, `WireframeEnable`, `SlopeScaleDepthBias`, `AlphaFunc`, `VertexShader`, `PixelShader`), packing results into a bitfield render-state struct — this is the core "compiled .fx pass state block" reader for the engine's own text-effect format.
- `FUN_10eecab0` (line 2466837) — **MatchPassStateName** — dereferences a pass-state key node (handles both inline and indirect string storage via the `<0x10`-length small-string check) and calls the CRT string-compare thunk `DAT_11000568` against a candidate state name; returns true on match. Called dozens of times by `ParsePassRenderStateBlock`.
- `FUN_10eecae0` (line 2466856) — **ApplyBooleanRenderStateFlag** — sets/clears a bit in the packed pass render-state bitfield (offsets +8/+0xc) based on whether the associated boolean state value string equals a known token, used for `AlphaBlendEnable`/`ZWriteEnable`/`ZEnable`-style toggles.
- `FUN_10eecb70` (line 2466886) — **ParseRenderStateEnumValue** — iterates a name/value lookup table comparing each entry's string via `DAT_11000568` and returns the matching enum's packed value; resolves `CullMode`, `SrcBlend`, `DestBlend`, `StencilFunc`, etc. tokens (`"Ccw"`, `"One"`, `"Zero"`, ...) into their D3D constant.
- `FUN_10eeca80` (line 2466822) — **RegisterDeferredPassStateFixup** — marks a pass-state block as "needs late binding" and appends it to a global fixup array (`DAT_1125adbc`), for pass states whose value depends on something resolved later (e.g. a shader constant not yet compiled).
- `FUN_10edede0` (line 2458052) — **InitShaderTechniquePass** — constructs a technique/pass object: stores up to two shader-stage sub-objects (vertex/pixel), copies flags, calls `ParsePassRenderStateBlock` to compile the pass's render-state block, then walks each shader stage's sub-tables via `FUN_10edebe0`.
- `FUN_10edebe0` (line 2458023) — **CollectPassShaderBindings** — for each of a shader stage's linked-list entries, tests validity and records the entry pointer + resolved handle into the pass object's binding arrays — resolving named shader-constant/texture bindings for one shader stage of a pass.

#### D3D10 HLSL compiler / D3DX10 dynamic export loader

- `FUN_10eec050` (line 2466204/2466200) — **ResolveD3D10CompilerExports / BindD3D10CoreProcAddresses** — `GetProcAddress`-resolves `D3D10CreateDevice[AndSwapChain][1]`, `D3D10CreateBlob`, `D3D10CompileShader`, `D3D10DisassembleShader`, `D3D10Get{Pixel,Vertex,Geometry}ShaderProfile`, `D3D10ReflectShader`, `D3D10PreprocessShader`, `D3D10Get{Input,Output,InputAndOutput}SignatureBlob`, `D3D10GetShaderDebugInfo` from a dynamically-loaded module handle — the tools-side HLSL shader compiler bootstrap (no direct device creation itself).
- `FUN_10eec140` (line 2466237/2466233) — **ResolveD3DX10Exports / BindD3DX10ProcAddresses** — companion loader resolving `D3DX10CreateDevice`, `D3DX10GetFeatureLevel1`, `D3DX10CompileFromMemory`, `D3DX10FilterTexture`, `D3DX10SaveTextureToFile{A,W,Memory}`, `D3DX10CreateTextureFromMemory`, `D3DX10GetImageInfoFromMemory`, `D3DX10SHProjectCubeMap` — offline HLSL compile + texture-processing utility exports; together with the above looks like an optional D3D10 back-end/tool path dynamically bound rather than statically linked.
- `FUN_10eec030` (line 2466189) — **BindDXGIFactoryProc** — resolves `"CreateDXGIFactory"` via GetProcAddress, stashes the pointer in `DAT_1125adb8`.

#### Shader-parameter registry core (generic RB-tree name→offset table)

- `FUN_10181d70` (line 266575) — **InitShaderParamTableHeader** — initializes a shader-parameter-provider registration record: stores the owning class's vtable/type tag and resets its RB-tree map fields, called at the top of every `*ParameterProvider` static-init function below.
- `FUN_10181ca0` (line 266514) — **RegisterShaderParamDescriptor** — inserts one named shader-constant/sampler descriptor (name string, byte offset, element count) into a class's parameter table via RB-tree insert; the single choke point every `...ParameterProvider` registration function calls once per exposed shader constant.
- `FUN_10181da0` (line 266593) — **ReleaseShaderParamTable** — refcount-releases a parameter table's backing storage, invoking its destructor vtable slot when the count hits zero; called at the end of every registration function to commit/finalize the table.
- `FUN_10181ea0` (line 266683) — **MergeInheritedShaderParams** — walks a base class's parameter RB-tree and copies each entry into the derived class's table at a caller-supplied base offset, implementing shader-parameter inheritance between provider classes.
- `FUN_10181b80` (line 266474) / `FUN_10181a10` (line 266415) / `FUN_10181950` (line 266364) — **ShaderParamTable RB-tree find/insert helpers** — internal red-black-tree lower-bound/insert machinery used by `RegisterShaderParamDescriptor`.

#### Per-class shader-parameter-provider registration tables ("what constants/samplers this object exposes to shaders")

- `FUN_10082920` (line 94319) — **RegisterGraphicObjectInstanceShaderParams** — registers `CSceneGraphicObjectInstance`'s exposed constants `GraphicInstanceParam`, `GraphicInstanceParam2`.
- `FUN_10085d50` (line 96580) — **RegisterDecalMaterialShaderParams** — registers `CSceneDecalMaterial`'s `DiffuseTexture1`, `SpecularTexture1`, `NormalTexture1`, `ParallaxHeightAndOffset`, `MaxLifeTime_FadeInDuration_rcpFadeInDuration_rcpFadeOutDuration`, `DiffuseColor1`, `DiffuseColor2`, `Anim_Amp_Freq_Offset_Blend` — full decal-material shader-constant/texture layout used by impact-FX decals (bullet holes etc.).
- `FUN_10086190` (line 96781) — **RegisterSceneGeometryShaderParams** — registers `CSceneGeometry`'s `MeshDecompression`, `MeshLocalHeight`, `NormalizedXYBBox` mesh-compression shader constants; also calls `FUN_10086130` (**ResetSceneGeometrySubobjectVtables**, line 96762) which resets three member sub-object vtable pointers back to a shared default before teardown.
- `FUN_103d2e40` (line 665029) — **RegisterMeshBoundingSphereShaderParam** — registers `CSceneMeshParameterProvider`'s single `BoundingSphere` constant.
- `FUN_103d2f20` (line 665083) — **RegisterGeometryParameterProviderShaderParams** — registers `CSceneGeometryParameterProvider`'s `MeshDecompression`, `MeshLocalHeight`, `NormalizedXYBBox` (parallel/duplicate provider variant of `FUN_10086190`, distinct class).
- `FUN_103debd0` (line 672752) — **RegisterTerrainShadowShaderParams** — registers `CSceneTerrainShadowPrivateData`'s `BigSelfShadowSampler` texture sampler.
- `FUN_10410ba0` (line 707994) — **RegisterWaterCameraPlaneShaderParam** — registers `CWaterCameraPlaneParameterProvider`'s `WaterLevel` constant.
- `FUN_10410c40` (line 708027) — **RegisterWaterVisibilityTestShaderParams** — registers `CWaterVisibilityTestParameterProvider`'s `Positions` array (element count 0x10).
- `FUN_1041e0c0` (line 717172) — **RegisterUserClipPlaneShaderParam** — registers `SUserClipPlaneParameterProvider`'s `UserClipPlane` constant.
- `FUN_10433fb0` (line 732754) — **RegisterBoundingBoxShaderParam** — registers `CBoundingBoxParameterProvider`'s `BBoxMatrix` (4-element matrix).
- `FUN_10442190` (line 741992) — **RegisterTransformShaderParams** — registers `CSceneTransformPrivateData`'s `WorldMatrix` (4-wide), `WorldPositionFractions`, `Scales` — standard per-object world-transform shader constants.
- `FUN_10442bb0` (line 742409) — **RegisterGlobalShaderParams** — registers `CGlobalShaderParameterProvider`'s engine-wide constants: `GlobalScalars`, `WindSimParamsX/Y`, `CascadedShadowScaleOffsetTile0/1`, `AlignedFor360CommandBuffers2/3/4`.
- `FUN_10449210` (line 746963) — **RegisterFakeTerrainGeometryShaderParam** — registers `CFakeTerrainGeometry`'s `MeshDecompression` constant.
- `FUN_10454e00` (line 754369) — **RegisterVertexInstancingTransformShaderParams** — registers `CVertexConstantInstancingTransformParameterProvider`'s `VertexCstInstancingWorldMatrices` (0x14 elements) and `VertexCstInstancingUniformScales` (5 elements) — GPU vertex-shader-constant instancing transform data.
- `FUN_10454f40` (line 754430) — **RegisterVertexInstancingAmbientShaderParams** — registers `CVertexConstantInstancingAmbientParameterProvider`'s `VertexCstInstancingParams` (5) and `VertexCstInstancingAmbientValues` (0x1e) — instancing ambient-lighting constants.
- `FUN_10455030` (line 754472) — **RegisterWaterParameterShaderParam** — registers `CWaterParameterProvider`'s `BorderAlphaMask`.
- `FUN_10465840` (line 764861) — **RegisterLightingDataShaderParams** — registers `CNewLightingDataProvider`'s large lighting/shadow constant set: `LightPositionWS`, `RcpSquaredLightRadius`, `LightDirectionWS`, `LightUpWS`, `LightRightWS`, `LightColor`, `LightColorUpNormal`, `SpotFactors`, `ShadowSampler`, `DepthSampler`, `DepthSamplerF4`, `VSMDepthSampler`, `ShadowFactor`, `ShadowDepthFadeFactor`, `ShadowMapSize`, `ShadowProjectionMatrix`, `CascadedShadowRanges/Scale/SliceScaleOffsets[Biased]/SliceDepthScales/SliceDepthOffsets/DepthRanges` — the full per-light/shadow shader-constant layout.
- `FUN_1046bbf0` (line 768752/768756) — **RegisterViewportShaderParameters** — registers `CViewportShaderParameterProvider`'s ~50 per-viewport constants: `ViewProjectionMatrix`, `ProjectionMatrix`, `ViewMatrix`, `InvViewMatrix`, `GrassCylindricalBillboardMatrix`, `ViewRotProjectionMatrix`, `InvProjectionMatrix[Depth]`, `ViewPoint`, `CameraPosition_DistanceScale`, `CameraPositionFractions`, `CameraRight/Direction/Up`, `CameraDistances`, `CameraNearPlaneSize`, `ViewportSize`, `DepthVPSampler`, `ResolvedDepthVPSampler`, `DepthTextureTransform/RcpSize`, `WaterReflectionTransform/Color/Plane`, `WaterLevelAdjustment`, `WaterReflectionTexCoordRange`, `Reflection/RefractionRealTexture`, `FogColorVector/Color/ColorRange/FinalColor/Values/HeightValues/ColorSunSide/ColorSunOppositeSide`, `UncompressDepthWeights[WS]`, `CullingViewProjectionMatrix`, `BloomAdaptation_SunOcclusion`, `CurvedHorizonFactors`, `ShadowProjDepthMinValue`, `StereoscopicZCurves/XFactors`, `CorpHighlightColor`, `ViewProjectionMatrixInfinite` — the master per-viewport/camera shader-constant binding table. Companion `FUN_1046b810` (line 768591) — **InitViewportShaderParameterSlots** — zero-initializes ~35 fixed-size parameter-slot structures before they get named/populated (effectively the provider's ctor/reset).
- `FUN_10ecb660` (line 2444496) — **RegisterRenderStateAlphaShaderParam** (variant 1) — registers `SRenderStateParameterProvider`'s `AlphaValues` constant.
- `FUN_10edd2b0` (line 2457334) — **RegisterRenderStateAlphaShaderParam2** (variant 2) — duplicate registration of `SRenderStateParameterProvider`'s `AlphaValues` at a separate static-init site.

Note: there are **131 total** `FUN_10181d70(DAT_...)`-style parameter-provider registration functions in the DLL; ~21 of the most distinctly-named are documented above. The remaining ~110 follow the identical pattern and are enumerable via `grep "FUN_10181d70(DAT_"` for a future full-coverage pass. `CShaderPreloadOperation`/`CShaderPreloadOperationBoot` (pure name-registration thunks) and `CStimEffectTable`/`SSkillFxPostFx`/`CRealtreeFx` (gameplay VFX/skill classes) were checked and found out of scope for D3D shader logic.

---

### Texture

Key format anchor: the Dunia texture container extension is **`.xbt`**
(confirmed by string literal `"engine\textures\iz3d_conv.xbt"`), with 32-bit
LE magic `0x00584254` = `'X' 'B' 'T' 0x00`.

#### CTextureResource cache / lookup (RTTI at `FUN_1018d200`, factory global `DAT_111e5d64`)

- `FUN_1018db40` (line 275112) — **GetOrCreateTextureResource** — resource-cache pattern: looks up a texture by hashed-path key; on miss creates via the `CTextureResource` class factory. The central "acquire a CTextureResource by path-hash" entry point, called from `FUN_103e4bb0` and material/light setup code.
- `FUN_101e74b0` (line 340608) — **BindSevenMaterialTextureSlots** — iterates 7 texture-slot fields (path-hash key vs. sentinel `DAT_1101d63c`), for each present slot does the GetOrCreate-from-cache pattern inline, swaps the resource reference via `FUN_101e6ad0`, then calls a vtable "SetTexture"-style call (`+0x68`) on a shader/material-binder interface — pushes a material's full texture set (diffuse/normal/specular/etc.) onto a renderable.
- `FUN_101e6ad0` (line 340161) — **AssignTextureResourceRefWithLoadCallbacks** — smart-pointer swap between old/new `CTextureResource` handles, firing vtable "unload/detach" on the old resource and "load/attach" on the new one before/after the swap.
- `FUN_100f1e90` / `FUN_100f1f30` / `FUN_100f1f50` (lines 174175 / 174217 / 174228) — **ResolveTexturePathToResourceKey / wrappers** — normalizes a resource path (strips directory, path-separator fixup), then hashes it into the key used by `CTextureResource`/`CTextureMipResource` cache lookups; used at every `.xbt` load site.
- `FUN_103e4bb0` (line 677506) — **BindFourNamedTextureSlots (material/light ctor)** — object constructor taking 4 optional texture-path strings; for each non-empty path resolves to a key, gets/creates the `CTextureResource`, and stores the ref — a light/decal/material descriptor holding up to 4 texture references.

#### CTextureMipResource / texture-mip streaming state (RTTI at `FUN_103b5530`, factory global `DAT_1121d404`)

- `FUN_103bb900` (line 648383) — **ParseXbtTextureHeader** — validates the 4-byte magic `0x00584254` ("XBT\0"), branches on a version/field-count word (11-field vs 10-field header) to copy out width/height/format quads plus a trailing-data pointer/size — the concrete `.xbt` container header cracker used by the mip-streaming path.
- `FUN_103bbbd0` (line 648492) — **ApplyParsedXbtHeaderToMipResource** — calls `ParseXbtTextureHeader`, and if the parent record's ref-count-ish field is under 2 and has an owner, requests a mip upgrade via `FUN_10eb5fc0`.
- `FUN_103bbe90` (line 648690) — **GetOrCreateTextureMipResource** — same GetOrCreate-from-cache pattern as `GetOrCreateTextureResource` but against the `CTextureMipResource` RTTI/factory.
- `FUN_103bbf30` (line 648743) — **RequestTextureMipLoad** — main streaming entry point for a mip-resource: resolves the texture path, computes streaming state, gets/creates the backing `CTextureMipResource`, wires ownership pointers, notifies the owner — "start/refresh streaming a texture's mip chain."
- `FUN_103bbcb0` (line 648519) — **StepTextureMipLevelTowardTarget** — compares desired mip index against current; loops stepping the live mip level toward the requested one one level at a time (streaming LOD ease-in).
- `FUN_103bbd80` (line 648588) — **TextureMipStreamState::ctor** — initializes a per-texture streaming-state record: current mip index defaults from the renderer's default mip bias when streaming config exists, else 0.
- `FUN_103bbdd0` (line 648618) — **TextureMipStreamState::dtor** — releases the ref held on the child `CTextureMipResource` handle.
- `FUN_103bbe10` (line 648644) — **UnloadTextureMipStreamState** — releases the loaded mip resource ref (firing teardown at refcount 0), fires detach vtable call, releases the owner ref — the mip-state "give everything back" routine.
- `FUN_103bb9c0` / `FUN_103bba00` (lines 648438 / 648459) — **BeginMipStreamOwnerScope / EndMipStreamOwnerScope** — paired increment/decrement of an owner refcount-ish field with owner-notify vtable calls — a scope guard bracketing a mip-streaming operation on the owning resource.

#### Texture streaming manager (singleton `DAT_1125a1a0`, constructed via `FUN_10eb63b0` in `C3DEngine::C3DEngine`)

- `FUN_10eb63b0` (line 2429145) — **TextureStreamingManager::ctor** — zero-inits the request-queue/array fields, reserves scratch storage; gated everywhere by "streaming enabled"/"streaming initialized" byte flags. Paired dtor: `FUN_10eb6410` (line 2429175).
- `FUN_10eb6170` (line 2428987) — **BuildTextureLoadInfoAndComputeMipCount** — fetches image dimensions/format for a texture (falling back to a 1x1/error state on failure), repeatedly halves width/height counting iterations while dimensions stay above a floor (64px) — computes available/streamable mip levels — then queues an async request or issues one synchronously.
- `FUN_10eb5fc0` (line 2428902) — **RequestNextHigherMipLevel (mip upgrade)** — increments a load-in-flight counter, queues an upgrade-request when streaming is ready, doubles tracked width/height, bumps the mip-level counter. Mirror: `FUN_10eb60a0` (line 2428942) — **RequestNextLowerMipLevel (mip downgrade)** — decrements in-flight counter, queues a downgrade-request (or falls back to a vtable call when streaming isn't ready), halves width/height, decrements mip counter; driven in a loop by `StepTextureMipLevelTowardTarget` to step down N levels at a time.
- `FUN_10eb6300` (line 2429086) — **SwapTextureMipStreamBuffers** — swaps paired front/back fields and clears a dirty/pending flag — double-buffer commit of a newly-streamed-in mip level into the live texture record.
- `FUN_10eb6500` (line 2429192) — **PurgeCompletedTextureStreamRequests** — walks the pending-request array, releases/erases entries that report "done" via vtable.
- `FUN_10eb6580` (line 2429223) — **EnforceTextureStreamingMemoryBudget** — walks pending requests accumulating size while under a 64-bit byte budget, releases entries once exceeded — the streaming memory-budget eviction pass.
- `FUN_10eb6630` (line 2429266) — **QueueTextureStreamRequestOnOwnerThread** — checks caller is on the manager's owning thread; if not, marshals cross-thread, else appends the request directly.
- `FUN_10eb6680` (line 2429290) — **QueueTextureStreamCompletionCallback** — appends into a second "completed/callback" queue distinct from the pending-request queue.
- `FUN_10eb66a0` (line 2429304) — **QueueWrappedTextureStreamCallback** — only proceeds if enable flags are set; wraps the callback pointer and appends it, else frees it.
- `FUN_10eb6700` (line 2429331) — **DispatchOrQueueTextureStreamRequest** — the single funnel point used by nearly every mip-upgrade/downgrade/build call above; queues immediately if already on the right thread, else probes and latches.
- `FUN_10eb6740` (line 2429359) — **ProcessTextureStreamRequestQueue** — batch-processes the pending array: cancels invalid entries, moves valid ones into a secondary in-flight array, drains a second iteration source with duplicate-suppression before dispatching outstanding callbacks — reads as the manager's per-frame pump.

#### Renderer texture-quality/streaming config accessors

- `FUN_101606a0` (line 247030) — **IsTextureStreamingEnabled** — reads whether high-res/streamed textures are active from the global renderer-settings object; gates the initial mip index chosen in `TextureMipStreamState::ctor`.
- `FUN_101606c0` (line 247046) — **GetDefaultTextureMipBias** — reads the configured default mip level/bias from the same renderer-settings object; used to seed a mip-stream-state's initial level.

#### CBTZOffscreenViewportTextureResource (render-to-texture; RTTI at `FUN_10198370`)

- `FUN_1019de30` (line 285316) — **CBTZOffscreenViewportTextureResource::ctor** — constructs an offscreen viewport/render-target texture object: allocates several sub-objects and wires them into a device-context-like interface via vtable registration calls, force-initializes the RTTI and registers a destructor callback pair.
- `FUN_1019d1a0` (line 284768) — **CBTZOffscreenViewportTextureResource::dtor** — tears down the same set of sub-object refs acquired by the constructor (standard smart-pointer release pattern).

---

### Mesh / VertexBuffer / IndexBuffer / VertexDeclaration / Draw-call

Scope note: Ghidra did not resolve `IDirect3DDevice9`/`IDirect3DVertexBuffer9`
vtable calls to named methods anywhere (no `CreateVertexBuffer`,
`DrawIndexedPrimitive`, `SetStreamSource` literal text; raw vtable-offset
grepping for canonical D3D9 offsets hits hundreds of unrelated engine
vtables). Findings anchored instead on RTTI class names
(`CSceneMesh`, `CSceneGeometry`, `CGeometryResource`), reflection field names,
and embedded profiler/debug-zone strings naming the enclosing function
outright — the strongest signal, anchoring the instanced-draw-call cluster.

#### CSceneGeometry / CSceneMesh (base mesh data classes — reflection + defaults)

- `FUN_10086810` (line 97139) — **RegisterCSceneMeshProperties** — tags the class `"CSceneMesh"` and registers the reflected field `"BoundingSphere"`; calls `FUN_10086660` (defaults) then `FUN_10086780` (cleanup).
- `FUN_10086660` (line 97049) — **InitSceneMeshBoundsDefaults** — initializes ~20 `CSceneMesh` fields to shared default globals, including an LOD/threshold-looking constant `0xc0`, a `0xffff` sentinel, and a fixed capacity `0xf` — per-instance default-state setup for a mesh's bounds/LOD record.
- `FUN_10086780` (line 97107) — **FreeSceneMeshDynamicArray** — frees the buffer at `+0x5c` if tracked capacity exceeds the inline-storage threshold `0xf`, resets the array to empty — paired destructor logic for the small-buffer-optimized array `InitSceneMeshBoundsDefaults` sets up.
- `FUN_10086920` (line 97176) — **InitSceneMeshDefaultFields** — thiscall constructor writing ~30 default field values across a `CSceneMesh`-shaped record (mirrors the layout touched by `InitSceneMeshBoundsDefaults`).

(`FUN_10086190`/`RegisterSceneGeometryShaderParams` and its
`ResetSceneGeometrySubobjectVtables` helper `FUN_10086130` — see Shader
section above; both operate on `CSceneGeometry`.)

#### CGeometryResource (submesh-part resource, `CResourceContainer`-derived)

- `FUN_101c9e80` (line 319901) — **RegisterGeometryPartProperties** — allocates 3 reflected-field descriptors: `"PartID"`, `"TextureIndex"` (offset 8), `"ColorIndex"` (offset 4) — the per-submesh material-binding fields of a `CGeometryResource` part.
- `FUN_101c9e00` (line 319849) — **FindGeometryResourceNodeByKey** — RB-tree style lookup keyed by a 3-uint composite key — looks like an index into cached `CGeometryResource` nodes keyed by e.g. (LOD/sector/part) triple.
- `FUN_101c9f90` (line 319954) — **FindGeometryPartIndexByID** — linear scan of an int array returning the matching slot index for a part ID; part-ID → index lookup, sits directly after `RegisterGeometryPartProperties`.

#### Mesh resource cache (`_Mesh_Cache` named pool)

- `FUN_10d24a80` (line 2119908) — **ConstructMeshResourceCache** — creates a named allocator pool via `FUN_10cee470("_Mesh_Cache", cfg, 0)`, binds two fixed-size sub-allocators for block sizes `0x3bc` (956B — per-mesh-resource record) and `0x90` (144B — sub-object).
- `FUN_10d24950` (line 2119831) — **DestructMeshResourceCache** — tears down the cache, walking two intrusive circular lists and freeing every node.
- `FUN_10d24b60` (line 2119954) — **DestroyMeshResourceCache** — thiscall scalar-deleting-destructor wrapper over the above.
- `FUN_10d24a00` (line 2119871) — **InsertMeshCacheEntry** — inserts a new node into a keyed bucket's doubly-linked list inside the mesh cache, creating the bucket if needed, incrementing entry counters.

#### Mesh render-technique / vertex-feature selection (material → shader define dispatch)

- `FUN_1041db00` (line 716976) — **SelectMeshRenderTechnique** — reads a material's texture-priority reflected fields, compares against a quality threshold, falls back to `"Mesh_Error"` or builds a `DIFFUSE_MAP_BASE`/`BILLBOARD`/`GLASS`/... shader-define bitmask; umbrella dispatcher branching into `"Mesh_BigLeaf"`, `"Mesh_Grass"`, `"Mesh_Cloth"`, `"Mesh_Flesh"`, `"Mesh_FX"`, `"Mesh_Procedural"`, `"Mesh_Unlit"`, `"Mesh_PostFxMask"` per material-name match — selects both the shader technique and (implicitly) the vertex-declaration variant a mesh needs.
- `FUN_1041daa0` (line 716960) — **CheckMeshMaterialTexturePropertyPresent** — helper testing whether a named material property (`"NormalTexture1"`, `"SpecularTexture1"`, `"HeightTexture1"`, etc.) resolved to a non-null value.
- `FUN_1041e000` (line 717121) — **ApplyBigLeafVertexColorAndSpecularFlags** — called from the `"Mesh_BigLeaf"` technique branch; sets shader define `"VERTEXCOLOR"` when the material's per-vertex-color flag is set, `"FAKE_SPECULAR"` when a `"SpecularID"` property is present — directly gates whether the foliage mesh's vertex declaration needs a `COLOR` stream element.

#### Convex collision-piece mesh stream serializer

- `FUN_10b84cb0` (line 1821463) — **SerializeCvxPieceMeshStreams** — writes a `"CvxPieceMesh"` section then up to three named `"Stream"` sub-blocks as `(dataPtr, count*4, capacity*4)` — matches the shape of a vertex/index-array dump — followed by a `"DisplayMesh"` object reference; a debug/export serializer for a Havok-style convex collision piece's render/collision mesh streams.

#### Mesh reference / attachment property loaders

- `FUN_102b15d0` (line 470589) — **RegisterMeshAttachmentProperties** — registers reflected fields `"EntityId"`, `"BoneId"`, `"MeshIndex"` — descriptor for attaching a sub-mesh/prop to a specific bone + mesh-index slot on a skinned entity.
- `FUN_1065f330` (line 1054373) — **LoadInventoryItemMeshAndSlotData** — reads an inventory item's `"EquipSlot"`, `"InventoryIcon"`, `"InventoryMesh"` (fallback path `"graphics/av_Weapons/Corp/Medium/Standard_Issue/STANDARD_ISSUE.xml"`), and `"Stacks"` properties — resolves which mesh resource file an inventory-carried weapon/item renders with.
- `FUN_107df260` (line 1273255) — **ResolveObjectMeshNameFromStateGraph** — walks a `"states"`/`"object"` node graph and reads a matching indexed object's `"meshName"` property — scene/animation-state deserialization resolving a mesh reference per state object.

#### Instanced cluster/foliage draw-call pipeline (highest-confidence cluster — anchored by embedded profiler-zone strings naming the enclosing class::method)

- `FUN_1044c1a0` (line 748621) — **BuildClusterInstancingRenderJobs** — body literally tagged `"CClusterRenderer::CreateInstancingRenderJobs"`. Reserves two streaming instance-buffer regions sized `stride * instanceCount` (one "opaque"-like group, one gated by a bitflag), fills them via a SIMD path or scalar fallback depending on a CPU-feature check, releases each reservation, hands both filled regions to `FUN_1044ba80` to build the render job.
- `FUN_1044ba80` (line 748279) — **BuildClusterInstanceRenderJob** — iterates a cluster's per-item array, copies each item into a render-job record, resolves an LOD-distance override (forced to `999` when a "no-LOD" flag is clear), selects vertex/blend data based on a stream/pass index, applies blend-mode bit flags, appends the assembled job to the output list — the per-cluster draw-call descriptor builder feeding instanced-rendering submission.
- `FUN_104220f0` (line 720200) — **ReserveDynamicBufferRegion** — 16-byte-aligned sub-allocator: finds/creates a pool node of the requested size in a growable buffer pool, lazily creates the node's backing store on first use rounded up to 8KB granularity (create-once-then-suballocate pattern for a streaming/dynamic vertex buffer); falls back to growing the pool when no node fits. Shared by both instancing paths — reads as the engine's generic per-frame dynamic-VB ring-buffer reservation routine.
- `FUN_104217b0` (line 719625) — **ReleaseDynamicBufferHandle** — clears the in-use/lock flag after a caller finishes writing a reserved region; pairs with `ReserveDynamicBufferRegion`.
- `FUN_103feba0` (line 695161) — **ProcessRealtreeInstanceBatches** — body literally tagged `"CRealTreeRenderer::ProcessBatches"`. Reserves a streaming instance-buffer region, allocates two parallel CPU-side arrays sized `instanceCount*0x78` (120B/instance — transform+color-looking record) and `instanceCount*0x10` (16B/instance) to stage per-instance foliage batch data before submission — the RealTree (procedural foliage) counterpart to `BuildClusterInstancingRenderJobs`.

---

### Camera / Viewport / RenderTarget / D3D Device Management

Methodology note: since named D3D9 vtable calls are essentially absent,
signal instead came from log/profiler tag strings matching `Class::Method`,
named-resource string literals passed into render-target/depth-stencil
registration helpers (`"DepthStencil"`, `"GlowRenderTarget"`, ...),
shader-parameter names tied to camera/viewport constants, and the
`CCamera*` RTTI getters in the TSV used only as breadcrumbs to find the real
dynamic_cast/dispatch call sites around them.

#### D3D9 device creation (tool-mode)

- `FUN_104665a0` (line 765119) — **CreateNomadTool9D3DDevice** — registers/creates a hidden window ("NomadTool9Win"/"NomadTool9"), loads `d3d9.dll`, resolves `Direct3DCreate9` via GetProcAddress, calls it (SDK version 0x20), then invokes `IDirect3D9::CreateDevice` (vtable +0x40) to spin up an off-screen/tool-mode D3D9 device — a standalone helper device separate from the main game renderer, likely embedded asset-processing/export tooling.
- `FUN_104666e0` (line 765198) — **DestroyNomadTool9D3DDevice** — companion teardown: releases the device and swap-related sub-objects, unregisters the window class, frees the `d3d9.dll` module handle.

#### CSceneRenderer — render target / depth-stencil / viewport composition

- `FUN_103d0820` (line 663273) — **RenderSceneView2D** — profiler-tagged `"CSceneRenderer::Render2DView"`. Registers/looks up a `"DepthStencil"` surface, reads a viewport-like rect, feeds it into a big draw/blit call together with matrices.
- `FUN_103d7d70` (line 667624) — **PrepareFrameGraph** — profiler-tagged `"CSceneRenderer::PrepareFrameGraph"`. The frame-graph builder: creates/looks up named render targets `"FakeHDRSurface"`, `"GlowRenderTarget"`, depth-stencil targets `"DistortionDepthStencil"`, plus a `"Distortion"` render-target slot, conditionally based on HDR/glow/distortion feature flags — the central per-frame render-target allocation function for the deferred/post-fx pipeline.
- `FUN_103eced0` (line 682831) — **AcquireNamedDepthStencilTarget** — generic pooled-resource helper looking up/creating a depth-stencil surface keyed by name+width/height/format via an associative container. Confirmed central transient depth-stencil pool: called with `"DepthStencil"`, `"DistortionDepthStencil"`, `"LDRSurface"`, `"HDRSurface"`, `"Depth"`, `"Z Buffer"`, `"Shadow Z buffer"`, `"DepthMSAA"` etc. across the whole renderer.
- `FUN_103ecdf0` (line 682777) — **AcquireNamedRenderTargetEntry** — same pattern for the render-target container (9-field descriptor incl. width/height/format/flags), keyed by name.
- `FUN_103ed100` (line 682936) — **AcquireNamedRenderTarget** — thin wrapper over `AcquireNamedRenderTargetEntry` hard-coding one flag to `1`; the actual entry point used everywhere in the renderer for the transient/pooled render-target system (`"GlowRenderTarget"`, `"FakeHDRSurface"`, `"Distortion"`, `"leftRT"`/`"rightRT"`, `"MinimapTexture1/2"`, `"Blur 0/1"`, `"nVidia blit texture"`) — the single most-referenced render-target factory function in the DLL (50+ call sites), effectively Avatar's frame-graph transient resource pool.
- `FUN_103ecfe0` (line 682881) — **ReleaseRenderTargetSlot** — erases/releases an entry from the named render-target map.
- `FUN_103eccf0` (line 682729) — **ReleaseDepthStencilSlot** — same erase pattern for the depth-stencil map.

#### Stereoscopic (3D) camera render targets

- `FUN_103d3490` (line 665305) — **AcquireStereoEyeRenderTargets** — acquires `"leftRT"` unconditionally and, when the stereo-3D flag is set, also `"rightRT"` (format `0x15`); clamps requested width/height against globals populated by the `gfx_maximumViewportSizeX/Y` cvars — the per-eye viewport sizing path for stereoscopic rendering.

#### Viewport scale console variables

- `FUN_10fabed0` (line 2593405) — **RegisterViewportScaleConsoleVars** — registers `gfx_stereoViewportScalePercentX/Y`, `gfx_viewportScaleStereoOnly`, `gfx_maximumViewportSizeX/Y` cvars with help strings ("Scale percentage of viewport width to save fillrate", "Maximum width of viewport").

#### CCamera*Component dynamic-cast / dispatch helpers

Each performs a real `dynamic_cast<T*>`-style class-id check and returns the typed pointer (distinct from the plain RTTI getters skipped per instructions):

- `FUN_10501ce0` (line 864958) — **DynamicCastToCameraPlanetComponent** — checks RTTI id against `CCameraPlanetComponent`; called from the planet-camera blend/transition state machine below.
- `FUN_10501d20` (line 864979) — **DynamicCastToCameraBoneComponent** — same pattern for `CCameraBoneComponent`.
- `FUN_1051baf0` (line 880805) — **DynamicCastToCameraThirdComponent** — same pattern for `CCameraThirdComponent`.
- `FUN_1051bb30` (line 880826) — **DynamicCastToCameraFreeComponent** — same pattern for `CCameraFreeComponent`.
- `FUN_106078b0` (line 1006449) — **DynamicCastToCameraGameComponent** — same pattern for `CCameraGameComponent`.
- `FUN_1053bcf0` (line 899718) — **DynamicCastToCameraModeGameplay** — same pattern for `CCameraModeGameplay`, testing whether a `CCameraMode` instance is specifically the gameplay-mode subclass.
- `FUN_105ae1d0` (line 960437) — **GetCameraShakeAndPadRumbleComponentClassInfo** — lazily fetches `CCameraShakeAndPadRumbleComponent` RTTI then calls a generic component-factory/lookup — a "get-or-create this component type" entry point one level above the plain getters.

#### Planet-camera transition state machine

- `FUN_108f9970` (line 1438896) — **TickCameraPlanetTransitionState** — large state-machine tick (fields `+0xc78..0xca4`) driving blending in/out of the planet camera mode: loads/plays the `"Cameras.Camera.Planet"` animation-blend resource, looks up the `"Camera_Pandora"` blend space by name, calls `DynamicCastToCameraPlanetComponent` to check whether the active camera is the planet camera before finalizing the transition — the function that switches between normal gameplay camera and Avatar's orbital/RDA-base "planet view" camera.

#### Camera-relative (floating-origin) position precision

- `FUN_1024a7a0` (line 406524) — **SetCameraRelativePositionOffset** — setter storing a 3-float vector into offsets `0x7c`/`0x80`/`0x84` of a `CCameraComponent`-associated object; write side of the camera-relative-offset field.
- `FUN_10270f40` (line 429760) — **ComputeCameraRelativeEntityOffset** — large per-entity update computing a world-space delta using Knuth/Kahan-style two-sum compensated float arithmetic (splitting each coordinate into "high"/residual "low" parts to cancel float rounding error) — the classic floating-origin / camera-relative-rendering trick for precision near the camera in a large open world. If the entity resolves to `CCameraComponent`, the compensated delta is written via `SetCameraRelativePositionOffset`; otherwise a different path is taken.
- `FUN_10248ed0` (line 405423) — **ReleaseEntityAndFetchCameraComponentInstance** — checks an entity flag bit, lazily resolves the `CCameraComponent` RTTI singleton and fetches/creates the component instance, then decrements/frees the entity's refcount — "borrow the camera component off this entity, releasing our reference in the process."

#### Script-exposed camera actions (context only, not individually labeled)

Around line 1636477, `FUN_10a8ac70` registers ~80 mission-script action callbacks including `"CameraShakeAndGamePadRumble"`, `"SetLookAtTargetID"`, `"LookAtTarget"`, `"StopLookatTarget"`, `"SwitchCamera"` (bound to `LAB_...` thunks, not standalone functions, so out of scope for individual naming).

---

### Particle Rendering / Lighting / Materials / LOD

#### CSceneParticleEmitterRenderer core (billboard particle draw pipeline)

Dense cluster in one translation unit implementing the particle emitter
renderer, whose profiler scope string is literally
`"CSceneParticleEmitterRenderer::Render"` (line 761003).

- `FUN_1045c390` (line 759239) — **ParticleDepthHeapSiftUp** — binary max-heap sift-up over an array of (id:uint, key:float) pairs; builds a depth-sorted heap of particles for back-to-front alpha blending.
- `FUN_1045c460` (line 759298) — **ParticleDepthHeapSiftDown** — companion sift-down/pop routine for the same max-heap, confirming a heapsort used to order particles by camera distance.
- `FUN_1045c3f0` (line 759261) — **SortParticleTripletByKey** — 3-element median/bubble sort network on (id, float key) pairs, used alongside the heap sort.
- `FUN_1045c4e0` (line 759332) — **TestParticleNearFadeCull** — dot-products a particle's world position (float4 sphere: xyz + radius) against camera-plane row vectors; compares against a threshold and only runs when the NEAR_FADE technique flag bit is set — a per-particle distance-cull/fade gate.
- `FUN_1045c570` (line 759353) — **ReserveParticleDrawBuffers** — calls dynamic VB/IB reservation helpers sized off per-particle stride*count — reserves vertex/index space for a particle batch before fill.
- `FUN_1045c610` (line 759376) — **BuildParticleBatchDescriptor** — packs ~20 fields (blend flags, camera-relative fade bool, 9 view/proj-like floats) into the batch descriptor consumed by the render loop.
- `FUN_1045c850` (line 759427) — **ApplyParticleTechniqueRenderStates** — reads an emitter material flags dword, ORs packed bit-ranges into shader constant slots, then based on flag bits calls a bank of render-state setter thunks (blend mode / point-sprite-like state) applied per particle draw technique.
- `FUN_1045cea0` (line 759642) — **ComputeParticleBillboardAxes** — branches on emitter orientation-mode flag bits (camera-facing vs. fixed-axis vs. local-space) to build a right/up basis pair for the particle quad — the billboard-orientation computation for point-sprite-style particles.
- `FUN_1045d350` (line 759796) — **ComputeParticleNearClipFadeAlpha** — computes signed distance to the near clip/fade plane, sets clip-flag bits (matches the "NEAR_FADE" technique key) and writes an RGBA fade-alpha color — the near-camera particle soft-fade used to hide clipping against the camera.
- `FUN_1045dcc0` (line 760295) — **ConstructParticleFillCallbackObj** — trivial vtable-stamped constructor used as the "fill" function object registered for a particle render technique.
- `FUN_1045dd00` (line 760312) — **RegisterParticleRenderTechnique** — allocates a descriptor storing Fill/Render callback pointers + flags, appends it into a growable technique table — wires the Fill callback (`ConstructParticleFillCallbackObj`) and render-state-apply callback (`ApplyParticleTechniqueRenderStates`) together per shader permutation.
- `FUN_1045de60` (line 760398) — **InitParticleShaderPermutationTable** — resolves the `"Particle"` shader/technique and registers named permutation keys `TEXTURED, ADDITIVE_BLEND, ALPHA_BLEND, NEAR_FADE, FIREADD_BLEND, MULTIPLY_BLEND, DISTORTION, NORMALMAP, SHADOW_OCCLUSION, FAR_SOFT, ALPHA_DISSOLVE, UNIFORM_FOG, SOFT_CLIPPLANE, AMBIENT, DIRECTIONAL` plus a quad index buffer (600 indices, 6-per-quad fan pattern) — the particle material/technique table builder.
- `FUN_1045e4a0` (line 760641) — **RenderParticleEmitterBatch** — ~500-line function carrying the profiler tag `"CSceneParticleEmitterRenderer::Render"`; batches particles in groups up to 100, allocates per-batch VB/IB chunks via `ReserveDynamicBufferRegion`, invokes the billboard/fade/technique helpers above, issues draw submissions — the particle system's main per-frame render entry point.

#### Particle emitter / entity integration

- `FUN_102582a0` (line 413585) — **BuildParticleFXComponentPropertyCache** — one-shot cache builder walking an entity template's component list, string-comparing each component's `"class"` property against `"ParticleFXComponent"`, caching its property list on match — editor/tool support for particle-emitter properties on entity templates.
- `FUN_102584d0` (line 413706) — **CollectEntityParticleEmitterAttachments** — iterates an entity's sub-objects, registers the `psEmitter`/`bFollowEntity` reflection block on candidates and inserts into a map — builds the set of particle-emitter attachment points on an entity.
- `FUN_10256ba0` (line 412580) — **RegisterParticleEmitterAttachmentReflection** — reflection-field registration for a `psEmitter` (particle system handle) + `bFollowEntity` (bool) pair — schema for "particle emitter bound to an entity/bone" objects (reused for weapon muzzle-flash-style attachments).
- `FUN_103e6900` (line 678681) — **ConstructParticleMeshInstanceGroup** — registers RTTI class `"ParticleMeshInstanceGroup"` then default-constructs an instance — the mesh-based particle instancing group (particles rendered as full meshes rather than billboards).
- `FUN_103e34b0` (line 676157) — **HashParticleEmitterParamName** — computes a bucket index from a string hash masked against a power-of-two table size — the named-lookup hash for `CParticlesEmitterParamResource`'s parameter table.
- `FUN_103e3510` (line 676185) — **FindParticleEmitterParamRange** — linear scan over a bucket's entries locating a named emitter parameter entry, used with the hash above.

#### Fire / smoke emitter LOD-replacement params

- `FUN_1066c110` (line 1062907) — **RegisterFireResourceParamsReflection** — reflection registration whose fields include `sndmlSoundMultilayer`, `bIsBudgetIndependent`, `fFireBudgetCostModifier` and a nested `"Fire_EmitterParams"` block registering `fEmitterRoaming`, `fMinStartingSize`, `fMinEndingSize`, `fReplacementLOD` (offset 0x54), `fReplacementSize` (offset 0x58) — `fReplacementLOD` is a distance/LOD threshold at which the live fire particle emitter is swapped for a cheaper replacement (billboard/decal); concrete evidence of particle-system LOD swapping.

#### Mesh/geometry LOD data (CGeometryResource)

- `FUN_101d6b40` (line 330100) — **GetGeometryLODEntry** — bounds-checks and returns the LOD-array element pointer for `CGeometryResource`.
- `FUN_101d6b60` (line 330113) — **CopyGeometryLODBoundsData** — copies a 16-dword block per LOD index — per-LOD bounding/transform data (bounding box or LOD-switch metrics).
- `FUN_101d6bf0` (line 330178) — **ForEachValidGeometryLOD** — iterates the LOD array, calling a per-LOD-entry visitor/validation pass on non-null entries.
- `FUN_102895c0` (line 444392) — **RegisterGeometryRenderFlagsReflection** — reflection registration for a renderable-object's shadow/lighting/LOD flags: `bCastShadow, bOnlyCastShadow, bReceiveShadow, bCastAmbientShadow, hidUseTerrainHemiMap, olgLightGroup, bShowInReflection, bAlwaysShowInReflection, iFirstLOD, iLastLOD, lpAmbientPreset` — the property schema tying per-object lighting flags and LOD range together.
- `FUN_10288700` (line 443669) — **GetLastLODLevel** — reads a packed 3-bit `iLastLOD` field via `(flags >> 4) & 7`; confirms LOD range is stored as two 3-bit fields inside a single flags dword. Sibling `FUN_10288750` (line 443683) — **GetFirstLODLevel** — reads packed 3-bit `iFirstLOD` via `(flags >> 7) & 7` from the same dword.
- `FUN_103c1180` (line 652831) — **DumpGeometryLODMemoryStats** — walks a geometry resource's LOD array, checks IsLoaded/LoadFailed state per LOD, formats labels with `"LOD #%d"` and `"%s_LOD%d"`, accumulates per-LOD vertex/index-like counters — a per-LOD resource/stat report generator for an in-engine memory-profiling menu.

#### Materials

(`FUN_10085d50`/`RegisterSceneDecalMaterialShaderParams` — see Shader
section above for the `CSceneDecalMaterial` shader-constant table including
the impact-decal fade-lifetime constant.)

- `FUN_101f36c0` (line 348932) — **GetOrCreateMaterialResource** — looks up a `CMaterialResource` by key, lazily creates a default instance if missing, smart-pointer-wraps with refcount increment — the "find-or-load material resource" entry point.
- `FUN_101f3710` (line 348954) — **ConstructMaterialResource** — default constructor stamping the `CMaterialResource` vtable, initializing texture/index-like fields to `-1` (sentinel "unset").
- `FUN_101f3750` (line 348977) — **ReleaseMaterialResourceRefs** — destructor-style teardown releasing three ref-counted sub-object pointers (texture/shader references owned by the material).
- `FUN_102be140` (line 478980) — **RegisterPhysMaterialReflection** — reflection registration for `SPhysMaterial`: `physmatPhysicMaterial, iPiercingResistance, bFireGoesThrough, fTransparency, fFireStickyBurnFactor, selFireStickyKindOfSmoke` with enum values `LightSmoke/HeavySmoke/NoSmoke` — ties a physics material to a fire/smoke visual-FX response class (which smoke particle system plays when the surface burns).

#### Environment lighting / light-fx

- `FUN_101e59e0` (line 339989) — **RegisterEnvironmentLightingSpecularCloudReflection** — reflection block combining light-like specular params (`bEnable, clrColor, clrSpecularColor, fSpecularPower, fSpecularMultiplier`) with volumetric cloud/fog params (`fThickness, fMinHeight, fMaxHeight, fCameraHeightMinHeight, fCameraHeightMaxHeight, vectorCloudRotationFactor, vectorDensityRotationSpeed`) — a sun-lit volumetric cloud/atmosphere layer definition under `CEnvironmentLighting`.
- `FUN_108cc330` (line 1411418) — **RegisterBoneLightFxReflection** — reflection registration for a bone-attached effect: `BoneName, psLightFx (particle system handle), sndRotatorSound, SoundOffset` — schema for a rotating-beacon-style light effect (e.g. vehicle emergency light) driven by a particle system and attached to a skeleton bone.

---

### Summary

**156 unique `FUN_` addresses** appear in this file (verified by grep), the
large majority of them primary labeled findings plus a smaller number of
directly-related helper/paired functions (ctors/dtors, sift-up/down pairs,
etc.) mentioned inline for context. Roughly balanced across the five slices:
Shader/Effect, Texture, Mesh/VertexBuffer, Camera/Viewport/Device, and
Particle/Lighting/Material/LOD (5 addresses were independently found by two
slices and de-duplicated above). All labels are anchored on genuine signal —
named Win32/D3D API calls (where present), embedded profiler/debug-zone
strings that literally spell out `Class::Method`, reflected property-name
strings, or RTTI class names from `avatar_class_hierarchy.tsv` — rather than
speculation.

---

## AI / Scripting (background sweep)

Target file: `Avatar_Dunia_Retail_1.02_decrypted.dll_FULL_DECOMPILE.txt`
Cross-referenced against `avatar_class_hierarchy.tsv`.

Methodology note: the AI class hierarchy TSV maps ~360 `CTask*`/`CScanner*`/`CBrain*`/`CEvent*`
classes to a `FUN_<addr>` each, but essentially all of those addresses are trivial RTTI
`GetClassInfo` accessors (`if (DAT==0) { FUN_100016b0("ClassName", parentInfo); } return &DAT;`).
Those are already mechanically covered elsewhere and are intentionally **excluded** below. This
sweep instead targets the real logic functions: script-binding registration/marshaling, brain/
dispatcher/event-queue plumbing, navmesh volume & grid management, pathfind tuning-parameter
registration, blackboard/fact primitives, and faction/alert/FCX-AI-component logic.

---

#### Lua / Domino Script-Binding Core

- `FUN_100de5f0` (line 157761) — **RegisterScriptMethod** — called everywhere as `("ClassName","MethodName",&LAB_impl)`; pushes class/method name strings via `FUN_100cc700`/`FUN_100cc680`, wraps the function pointer via `thunk_FUN_100e1880`, then commits the binding via `FUN_100cca20`/`FUN_100cc150` into the table at `*DAT_111ca7c4` (the script binding state). When `param_1==0` it does a simple global-function bind instead (push funcptr, `FUN_100cc9e0(name)`). This is the core Lua/Domino native-method registration primitive.
- `FUN_100cce50` (line 147638) — **RegisterScriptClassType** — calls `FUN_100cfa80(state,name,basicType)` to create a new named script type slot; emits `"type name '%.30s' already exists"` on collision — the class-registration primitive used before method binding.
- `FUN_100cc700` (line 147188) — **PushScriptNameToken** — pushes a raw C string onto the script-state stack via `FUN_100e3450`/`FUN_100e1ad0`; used to push class names and generic identifiers.
- `FUN_100cc680` (line 147155) — **PushScriptNameTokenOrNil** — same string-push as above but special-cases `param_2==0` into a nil/marker byte; used for the (possibly-null) method name argument.
- `FUN_100cc9e0` (line 147354) — **BindScriptGlobalName** — pops the stack (`*param_1 += -5`) and commits top-of-stack under `param_2` via `FUN_100e1b60`; used for global (non-class-scoped) function registration and for finalizing per-class type objects.
- `FUN_100cca20` (line 147376) — **JoinScopedScriptName** — combines the two most-recently pushed tokens (class + method) into one qualified binding entry via `FUN_100e1a20`.
- `FUN_100cc150` (line 146723) — **CommitScriptMethodBinding** — final stack-adjust/insert step (`FUN_100d2450`) that finalizes a class-scoped method registration.
- `FUN_100e1880` (line 160300) — **CreateScriptFunctionRefToken** — allocates/tags a stack slot as a native-function reference (`*puVar1=1; puVar1[2]=funcptr`); invoked as `thunk_FUN_100e1880` from `RegisterScriptMethod` to wrap the `&LAB_...` implementation pointer before binding.

#### Domino Manager Script Bindings

- `FUN_102a1ec0` (line 458873) — **RegisterCDominoManagerScriptBindings** — registers `"CDominoManager"` and binds `SpawnDominoEntity`, `RemoveDominoEntity`, `RemoveCommandEventToEntity`, `SendCommandEventToEntity`/`SendCommandEventToEntity2`, `QueueCommandEventToEntity`/`QueueCommandEventToEntity2`, `SendRegisteredEventToEntity`, `TraceConnection`, `IsScriptAutorunEnabled`, `SetWorldSynchFlag` — the core Domino entity/event dispatcher exposed to script.
- `FUN_10217490` (line 372119) — **RegisterCDominoDelayManagerScriptBindings** — registers `"CDominoDelayManager"` and binds `CreateDelay`, `CreateOnscreenTimer`, `CreateOnscreenZoneTimer`, `RemoveDelay`, `SetDelay`, `SendCommand`.
- `FUN_10217060` (line 371902) — **RegisterCDominoDelayManagerScriptClassType** — creates the `"CDominoDelayManager"` script type via `FUN_100cce50`, hooks its `"gettable"` metamethod, stores the type id into `DAT_1117b480`.
- `FUN_102167f0` (line 371529) — **CDominoDelayManagerGetInstance** — zero-arg script binding impl: pushes the singleton (`DAT_111e783c`) tagged with class-type id `DAT_1117b480`.
- `FUN_10218030` (line 372637) — **RegisterCDominoSoundManagerScriptBindings** — registers `"CDominoSoundManager"` and binds `PlaySound`; also builds a `"Sounds"/"Sound"` resource-map entry.
- `FUN_10217e30` (line 372529) — **RegisterCDominoSoundManagerScriptClassType** — class-type bootstrap for `"CDominoSoundManager"` (type id stored in `DAT_1117b49c`).
- `FUN_10217750` (line 372232) — **CDominoSoundManagerGetInstance** — zero-arg singleton-push impl tagged with `DAT_1117b49c`.
- `FUN_102190b0` (line 373296) — **RegisterCDominoSequenceManagerScriptBindings** — registers `"CDominoSequenceManager"` and binds `CreateListener`, `DeleteListener`; builds a `"Listeners"/"Listener"` resource map.
- `FUN_102182a0` (line 372736) — **CDominoSequenceManagerGetInstance** — zero-arg singleton-push impl tagged with `DAT_1117b4a4`.
- `FUN_102dfad0` (line 499667) — **RegisterCDominoBoxResourceScriptBindings** — registers `"CDominoBoxResource"` and binds `RegisterBox`, `LoadResource`.
- `FUN_102e1c40` (line 501373) — **RegisterCDominoConsoleCommandManagerScriptBindings** — registers `"CDominoConsoleCommandManager"` and binds `RegisterConsoleCommand`, `UnregisterConsoleCommand`; builds a `"CommandMap"/"Command"` map keyed by `"CommandName"`.
- `FUN_102dfcb0` (line 499814) — **CDominoConsoleCommandManagerGetInstance** — zero-arg singleton-push impl tagged with `DAT_1117bc6c`, bound as `"GetInstance"` inside `FUN_102e1c40`'s registration.
- `FUN_102e2d40` (line 502030) — **RegisterCDominoBoxInstanceScriptBindings** — registers `"CDominoBoxInstance"` and binds `CreateBox`, `GetParentEntity`.

#### Script Callback System & Music-From-Lua Bindings

- `FUN_102680a0` (line 424263) — **RegisterCScriptCallbackSystemScriptBindings** — registers `"CScriptCallbackSystem"` and binds `RegisterEventCallback`, `RegisterOnSpawnCallback`, `RegisterOnRemoveCallback`, `RemoveCallback`, `RemoveCallbacks`, `RegisterMessageListener`, `UnregisterMessageListener`, `BroadcastMessage`; also registers a `"SerializationEvent"` handler (`FUN_10266d50`) and a `"NextCallbackID"` counter field — the Lua/Domino event-listener and message-broadcast hub for script-side entity callbacks.
- `FUN_10262280` (line 418982) — **CScriptCallbackSystemGetInstance** — zero-arg singleton-push impl tagged with `DAT_1117b738`, bound as `CScriptCallbackSystem::GetInstance`.
- `FUN_105cb120` (line 973421) — **RegisterCMusicManagerScriptBindings** — registers `"CMusicManager"` and binds `SetActionLevelOverride`, `PlayMusicFromLua`, `SetMusicFromLua`, `RemoveLuaMusic`, `PauseFromLua`, `ResumeFromLua`, `PauseMapMusicFromLua`, `ResumeMapMusicFromLua` — the explicit `...FromLua` suffixes directly confirm the Lua binding naming convention used throughout this subsystem.

#### AI Object Base / Brain Class Registry

- `FUN_104a1d00` (line 803348) — **ConstructAIClassRegistry** — sets vtable, lazily inits CAIObject/CDispatcher/CCollective classinfo, builds 3 default/null AI-object singletons, and registers per-class factory callbacks (CTask, CAction, CDecision, CScanner, CPlan, CBrain, CDispatcher, CAIWorkspaceResource, CNavMeshSectorResource) into a class-ID→factory map.
- `FUN_104a1b60` (line 803273) — **DestroyAIClassRegistry** — mirror-image teardown: releases the 3 default singleton instances via virtual dtor calls and cleans up parent state.
- `FUN_104a1ce0` (line 803334) — **AIClassRegistryScalarDtor** — MSVC scalar-deleting-destructor wrapper (calls dtor, then optional `operator delete`).
- `FUN_104a1ad0` (line 803230) — **RegisterAIClassFactory / InsertOrUpdateKeyedEntry** — generic find-or-insert of a `(key → value)` pair into a sorted array/map container; used both as the AI class-ID→factory registrar in `ConstructAIClassRegistry` and as the shared registration primitive sitting among the `CScanner`/`CDecision`/`CBrain`/`CDispatcher`/`CCollective` RTTI-getter cluster — a generic keyed-container helper reused across the AI decision/scanner tree.
- `FUN_104a3170` (line 804543) — **ConstructNullBrainSingleton** — real ctor (not RTTI getter): sets vtable, a critical section, 3 map-sentinel members, and builds an rb-tree root; constructs the first (~0x6c-byte) lazily-created default AI object in the registry.
- `FUN_104a7cf0` (line 807088) — **ConstructNullDispatcherSingleton** — real ctor for the second lazily-created default object (~0x2c bytes); re-parents vtable after base-class init.
- `FUN_104b6130` (line 815155) — **ConstructNullCollectiveSingleton** — real ctor for the third lazily-created default object (~0x30 bytes).

#### AI Event Dispatch Core

- `FUN_104a7e30` (line 807143) — **DispatchAIEventIfReceivable** — checks the target's "can receive event" virtual predicate (vtbl+0x4c) before ref-counting and queuing the event; always releases its own reference afterward.
- `FUN_104a7df0` (line 807120) — **DispatchAIEvent** — unconditional variant: bumps the event's refcount, queues it, then releases.
- `FUN_104bfa10` (line 821656) — **QueueAIEvent** — inserts an event node into the target object's `std::list`-based event queue (bucket/chain insert), throwing `"list<T> too long"` on overflow — the low-level enqueue beneath both dispatch functions above.
- `FUN_109a3e40` (line 1526921) — **CreateAndPostAIEvent** — allocates+constructs a full event object (type tag = 6), double-increments refcount, posts it via the dispatch path, then releases its local reference.
- `FUN_109a3ea0` (line 1526951) — **CreateAndPostSimpleAIEvent** — lighter-weight variant: allocates a small event, bumps refcount, and posts it to the target with no extra tagging.

#### Dispatcher Handler / Registry Map

- `FUN_104a20e0` (line 803532) — **FindEventHandlerForKey** — hash-bucket + chained-list search returning the handler/value whose key field matches `*param_2`; classic dispatcher lookup-by-ID.
- `FUN_104a2170` (line 803587) — **FindEventHandlerSlot** — same bucket-chain search as above but returns a sibling field (slot/index) instead of the handler pointer.
- `FUN_104a2210` (line 803644) — **RemoveArrayEntryByKey** — linear scan + erase of a fixed-stride array entry matching `*param_2`.
- `FUN_104a22f0` (line 803701) — **InsertArrayEntryIfAbsent** — find-or-insert into the same array container, skipping duplicates by key.
- `FUN_104a2280` (line 803668) — **RemoveTreeEntryAndRelease** — erases a node (matched by identity) from a tree/list, releasing (virtual dtor call) the entry's owned value first.
- `FUN_104a23c0` (line 803756) — **GetOrCreateRegistrySingleton** — via a manager's virtual `Find/Allocate` (vtbl+4), fetches or creates a keyed singleton instance and links it into a global instance list; underlies `GetAIWorldSingleton` below.

#### Dispatcher & AIWorld Type Queries

- `FUN_1097dcd0` (line 1500848) — **CastToCAIWorld** — dynamic type-check: validates an object's RTTI depth/class-ID against CAIWorld's, returning it only on a match (else NULL); a `dynamic_cast`-style safe-cast.
- `FUN_1097ff30` (line 1501854) — **GetAIWorldSingleton** — fetches the global singleton keyed by CAIWorld's class ID (via `GetOrCreateRegistrySingleton`) and re-validates its type before returning it — the accessor for the engine-wide AIWorld instance.
- `FUN_109a3fc0` (line 1527049) — **CastToVehicleStrategyPosition** — safe-cast helper analogous to `CastToCAIWorld`, scoped to `CVehicleStrategyPosition`.
- `FUN_109a4030` (line 1527086) — **CastToVehicleStrategyAIObject** — safe-cast helper for `CVehicleStrategyAIObject`.

#### AI Event Payload Records

- `FUN_109b38c0` (line 1537701) — **InitVehicleStrategyRecordFields** — zero-initializes ~20 member fields (offsets 0x0-0x4c) of a strategy/report record; sits directly beside `CEventSocialReportSeePlayerBumpedMe`/`ShotFired` getters, consistent with being their shared payload-record constructor helper.
- `FUN_109b3b40` (line 1537785) — **DestroyVehicleStrategyRecord** — sets vtable, destructs 8 owned sub-members in a loop, then calls a base-class destructor (`FUN_104a8460`); the real destructor paired with the record `FUN_109b38c0` initializes.

#### NavMesh Volumes (CNavigationVolumeComponent)

- `FUN_105ab3f0` (line 958554) — **IsDisableNavMeshVolumeEvent** — dynamic-type check against the `CDisableNavMeshVolumeEvent` classinfo cell (`DAT_11224e98`), classic "is-instance-of" pattern.
- `FUN_105ab460` (line 958591) — **IsEnableNavMeshVolumeEvent** — same pattern for `CEnableNavMeshVolumeEvent` (`DAT_11224eb0`).
- `FUN_105ab4a0` (line 958612) — **IsNavMeshSectorEvent** — dynamic-type check against `CNavMeshSectorEvent` classinfo.
- `FUN_105ab4e0` (line 958633) — **UpdateNavMeshVolumeCachedTransform** — compares current position/orientation against cached values; if changed, refreshes the cache and invokes a virtual (offset 0x34) to trigger a rebuild.
- `FUN_105ab5f0` (line 958687) — **ApplyNavMeshCellEnableFlags** — walks a list of (x,y) grid coordinates, looks each up in the sector/cell grid (`DAT_11220694`), and writes enable/disable bits into byte `+0x39` of each cell.
- `FUN_105ab730` (line 958750) — **DispatchToggleNavmeshComponentEvent** — verifies the target is a `CEntityComponent`-derived object then forwards a `"CAIToggleNavmeshComponent"` event via `PostNamedComponentEvent`.
- `FUN_105ab840` (line 958784) — **ConstructDisableNavMeshVolumeEvent** — builds the `"DisableNavMeshVolume"` wire-event object with the two payload params.
- `FUN_105ab8f0` (line 958806) — **ConstructEnableNavMeshVolumeEventDefault** — builds `"EnableNavMeshVolume"` with default (-1,-1) payload.
- `FUN_105ab980` (line 958828) — **ConstructEnableNavMeshVolumeEvent** — parameterized variant of the above.
- `FUN_105abbd0` (line 958850) — **RemoveNavMeshCellEntry** — erases entries matching a given cell id from the volume's cell list.
- `FUN_105abd10` (line 958873) — **GatherNavMeshCellsInVolume** — iterates the sector grid, point/triangle-tests each cell (`FUN_104c2020`) against the volume's shape, and appends overlapping cell ids.
- `FUN_105abe50` (line 958940) — **TruncateNavMeshCellList** — shrinks the volume's tracked-cell array to a given count.
- `FUN_105abeb0` (line 958966) — **HandleNavMeshVolumeToggleEvent** — the real event handler: dispatches on whether the volume is "in update" state, doing either an incremental single-cell toggle or a full Enable/Disable pass via `ApplyNavMeshCellEnableFlags`.
- `FUN_105ac010` (line 959039) — **BroadcastNavMeshVolumeChangeEvent** — iterates a listener list and fires a change notification (message id `&DAT_11075844`) through each listener's vtable+0x58.
- `FUN_105ac0a0` (line 959076) — **DestructNavigationVolumeComponent** — component teardown: reverts cell flags, releases grid/pathfind references, decrements refcounts.
- `FUN_105ac180` (line 959116) — **ConstructNavigationVolumeComponent** — component constructor: sets vtable pointers and zeroes the cell-list/state fields.
- `FUN_105ac230` (line 959162) — **RebuildNavMeshVolumeCellList** — recomputes the set of grid cells covered by the volume's AABB (via `ComputeNavMeshGridCellRange`) and stores them, setting the "has cells" flag.
- `FUN_105ac350` (line 959221) — **RefreshNavigationVolumeCells** — top-level refresh: clears prior cell flags, rebuilds the cell list, and broadcasts a change event if the volume now covers cells.

#### NavMesh Sector Grid

- `FUN_104bdfa0` (line 820701) — **ClearNavMeshSectorGridBit** — clears a single bit in a row-major bitfield at `(y*width+x)`.
- `FUN_104be060` (line 820747) — **GetNavMeshSectorGridCell** — decodes a packed 7-bit/7-bit (x,y) coordinate and fetches the corresponding sector-cell pointer from the grid array.
- `FUN_104be0a0` (line 820765) — **RemoveEntityFromNavMeshSectorGrid** — clears an entity's grid slot and fires a "left sector" style event (`&DAT_11075844`) before doing so.
- `FUN_104be250` (line 820866) — **WorldPosToNavMeshGridCoord** — converts a world-space (x,y) into a packed grid coordinate, bounds-checked against the sector's min/max rect, returning `0xffff` if out of range.
- `FUN_104be5b0` (line 821009) — **ComputeNavMeshGridCellRange** — converts a world-space AABB into a clamped list of covered grid cell coordinates; reused by `RebuildNavMeshVolumeCellList`.
- `FUN_104be7e0` (line 821101) — **CollectNavMeshSectorsInAABB** — calls `ComputeNavMeshGridCellRange` then gathers the non-null sector pointers overlapping that range into an output array.

#### NavMesh Generation & Generic Event Factory

- `FUN_10203380` (line 359224) — **PostNamedComponentEvent** — builds a class-name string, looks up the type by name (`FUN_1036df60`), constructs an event instance, and posts it to the target object's handler; the generic name-keyed event factory used by `DispatchToggleNavmeshComponentEvent` and, per the code shape, many other subsystems.
- `FUN_1028e7a0` (line 447550) — **GenerateNavMeshGenObjectBoundaryMesh** — builds a ring of scaled/positioned quads (segment count derived from extent fields); the visual/debug boundary geometry of a nav-mesh-gen volume.
- `FUN_1028ef30` (line 447815) — **ConstructNavMeshGenObject** — constructor for the script-exposed `"engine.NavMeshGenObject.NavMeshGenObject"` type.
- `FUN_1028eff0` (line 447869) — **SyncNavMeshGenObjectTransform** — copies current world position/orientation from the owning entity into the gen-object's local transform fields.

#### Pathfind Tuning Parameters

- `FUN_10a6e440` (line 1622912) — **RegisterPathfindToDestinationParams** — STP (Scripted Task Parameter) registration for a chase/pathfind task: `destination`, `destinationOffset`, `minimumDistance`/`maximumDistance`, `newPathAheadTime`, `TargetRoadDist`, `MaxRoadDist`, `RoadLengthCutoffRatio`, `followTarget`, `continueOnFailedPathFind`, `useLessPathfind`, `"Pathfind even if min distance is reached"` (`pathfindEvenIfDistanceReached`), `useBlindPathfind`.
- `FUN_10a7a2b0` (line 1628345) — **RegisterChasePathfindTuningParams** — STP registration for a related chase behavior: `minimumDistance`/`maximumDistance`, `CheckSight`, `PathFindAttempts`, `SwitchMinTime`/`SwitchMaxTime`, and `"PathfindFrequency"` ("New pathfind request frequency"), plus `PathFindFailed`/`TooFarFromTarget` exit signals.

#### Blackboard / Fact (Stimulus-Event) Primitives

- `FUN_10252780` (line 409949) — **ExecuteAddSEFactEvent** — real logic for `CAddSEFactEvent`: looks up the target's `CAIStateComponent` (blackboard) and attaches a stimulus/event fact to it after a scanner-type compatibility check.
- `FUN_10252920` (line 409993) — **IsSEFactApplicable** — predicate helper checking whether the pending stimulus/event fact should still be applied (used just before `ExecuteAddSEFactEvent`'s effect).
- `FUN_10252990` (line 410027) — **ExecuteRemoveSEFactEvent** — real logic for `CRemoveSEFactEvent`: looks up the target's `CAIStateComponent` and detaches the stimulus/event fact from its blackboard.

#### FCX AI Components

- `FUN_10a1dfa0` (line 1587512) — **CollectAIShootMeObjectComponents** — walks an entity's component array, safe-casts each via `CAIShootMeObject` classinfo, appends matches into an output vector.
- `FUN_10a1e0f0` (line 1587583) — **TriggerRandomAIShootMeObject** — rebuilds the shoot-me-object bucket if empty, picks one pseudo-randomly, refcounts it, fires an event.
- `FUN_10a1e550` (line 1587665) — **RegisterAIShootMeObjectTypeEnum** — registers the editor enum property with values Normal/BarricadedEntrance/BuildingExteriorObject/BuildingInteriorObject/BargeObject.
- `FUN_10a1dd90` (line 1587461) — **GetAIShootMeObjectType** — safe-casts to the shoot-me-object base and returns its sub-type field.
- `FUN_105bf990` (line 968376) — **GetFCXAIComponentFromEntity** — the real `GetComponent<CFCXAIComponent>()` implementation: validates classinfo category then refcounts and returns the component.
- `FUN_1099c6d0` (line 1523954) — **GetFCXAIComponentLinkedId** — fetches an entity's `CFCXAIComponent`, then a linked object, returns its id field (or -1).
- `FUN_1099c730` (line 1523981) — **NotifyFCXAIComponentIfUnengaged** — same lookup chain gated by a bit flag; triggers an action callback if the linked object resolves.

#### AI Counters

- `FUN_10a59900` (line 1613753) — **GetMaxNearbyAICounterStat** — walks the global entity list, filters by type, reads each candidate's `CFCXCountersComponentAI` stat, tracks the max value vs. a threshold.
- `FUN_10abd4b0` (line 1666332) — **FindNearestValidAICounterEntity** — walks entities, validates a counter stat, computes squared distance, keeps the nearest entity satisfying the condition.

#### Faction System

- `FUN_104e5160` (line 847141) — **LoadPlayerProfileSaveData** — player-profile deserializer that loads ~10 named sub-blobs including `"FactionBaseProgression"` into a field at `param_1+0x50d0`.
- `FUN_106540f0` (line 1048241) — **DeserializeQuestDefinition** — quest-definition loader; reads `"Faction"` and maps its hashed value to a small faction-ID enum stored in the quest object.
- `FUN_1069fa40` (line 1091504) — **RegisterQuestOfferEventFields** — registers named/typed fields (`Faction`, `Reward`, `DiamondReward`, `Accepted`, ...) for a quest-offer event, Domino-style reflection.
- `FUN_1069fcb0` (line 1091613) — **RegisterQuestStateEventFields** — registers fields (`Faction`, `Active`, `Achievement`, `First`) for a related quest-state event.
- `FUN_1069e6e0` (line 1090900) — **GetFactionEnumFromEntityClass** — classifies an entity/class handle against three registered faction class-IDs, returns a 0/1/2 faction enum; backs the `"Faction"` field getters above.
- `FUN_108e1460` (line 1424489) — **SerializeFactionBase** — writes a faction military-base/outpost struct (`Faction`, `HomeBase`, `BaseUnits`, `SecondaryBase`, `DefenseFlags`, `FreeUnits`, `ActionID`) to a serializer.
- `FUN_108e15d0` (line 1424566) — **DeserializeFactionBase** — the matching reader for the same faction-base struct fields.
- `FUN_10975ac0` (line 1495311) — **BuildFactionTypeNameLocalizedString** — builds localized `FactionType`/`FactionName` token-substituted strings across 3 branches (Na'vi/RDA-Corporation/Neutral).
- `FUN_109344b0` (line 1467257) — **ConstructCFactionUpdateEvent** — inlined constructor for a `CFactionUpdateEvent` object; stamps its name via the generic `DAT_11000550(dest,0x30,src)` string-copy helper (a distinct event-naming mechanism from the `FUN_100016b0` RTTI-singleton pattern, used identically by dozens of unrelated event constructors).
- `FUN_10934570` (line 1467279) — **SetPlayerFactionAndRaiseUpdateEvent** — sets the global current-faction id, toggles player flag bits, constructs and dispatches a `CFactionUpdateEvent`, triggers a HUD refresh.

#### Alert System

- `FUN_106c2070` (line 1108770) — **ConstructAIAlertedNearbyEventDefault** — default constructor for the `CAIAlertedNearby` event object (name-string setup + base/derived vtable assignment).
- `FUN_106c2130` (line 1108792) — **ConstructAIAlertedNearbyEventFromParams** — parameterized constructor copying an entity/position handle and a flag byte into the same event type.

---

### Negative leads (investigated, found to be out of scope — noted so they aren't re-swept)

- `CFCXAIBehaviorService` RTTI getter (`FUN_106476b0`, line 1039718) is a trivial RTTI accessor; `CFCXGameModeRegistry::RegisterServices` (`FUN_106479d0`, line 1039789) likely registers it but Ghidra failed to recover its control flow ("Too many branches") — opaque, nothing extractable.
- The animal-AI `CBrain*`/`CTask*` tail cluster (lines ~1507425-1508100: `BrainDirehorse`, `BrainHexapede`, `BrainStingbat`, `BrainSturmbeest`, `BrainTapirus`, `BrainThanator`, `CBrainHammerhead`, `CBrainViperwolf`, `CTaskCheckAnimalIsMounted`, `CTaskWaitAnimGroup`, `CTaskJump`, `CTaskEndJumpDown`, `CTaskMeleeCombo`, `CTaskSelectHitAndRunPoint`, etc.) is ~38 functions, all confirmed trivial RTTI getters.
- The ~50-class `CEventMercCommand*`/`CEventDrive*`/`CEventMercReport*` cluster (lines ~1537700-1540000, ~1548900-1555800) is almost entirely trivial RTTI getters with no distinct per-event payload logic beyond the two `InitVehicleStrategyRecordFields`/`DestroyVehicleStrategyRecord` helpers listed above.
- Broad `"Fact"`/`"Blackboard"`/`"FOV"` string grep outside the `CAIStateComponent` SE-fact pipeline turned up mostly unrelated hits (faction/UI/camera-FOV tuning strings) — no further genuine AI perception primitives found beyond the three listed under Blackboard/Fact Primitives.
- No literal `lua_*` C-API call sites exist in the decompile (Lua is statically embedded and all script interop goes through the `FUN_100de5f0`/`FUN_100cc*`/`FUN_100e1*` binding-table primitives documented above, not direct `lua_push*`/`lua_call` symbol names).

---

## AI Considerations / Local-Avoidance / Runtime Internals — cluster formerly hypothesized as "Vegetation" (background sweep, hypothesis corrected)

#### HEADLINE / CORRECTION — read this first

**The "vegetation placement/foliage-scattering system" hypothesis for this cluster is
FALSIFIED.** Six independent sub-range sweeps (each ~65-120 functions, covering the full
531-function span with zero gaps) converged on the same conclusion: this address range is
**not** a vegetation placement/scattering/instancing system. It is a grab-bag of several
unrelated Dunia-engine subsystems that happen to sit next to each other in the binary:

1. **AI "Consideration"/utility-scoring framework** (lines 1668028–~1671881) — a set of
   named criterion classes (PawnSampling, Occlusion, **Vegetation**, Grass, Stance, Speed,
   AvatarSkill) used for AI behavior-selection/stealth-detection math. "Vegetation" and
   "Grass" are two *sibling* criteria among seven, not a distinct subsystem. The genuinely
   vegetation-specific code in the whole 531-function sweep lives here: `FUN_10ac5fb0`
   (**ComputeVegetationCoverageScore**) and its support functions compute how much
   foliage/canopy currently conceals a pawn from detection (a stealth mechanic), NOT where
   to place vegetation instances.
2. **2D local-avoidance / steering / turn-around-damping subsystem** for NPC/vehicle
   movement (lines ~1671882–1678485) — obstacle wedges, tangent computation, edge/corridor
   clipping, KD-tree neighbor queries, a debug HUD literally printing "Edges in memory" /
   "Obstacles in memory" / "TurnAroundAngleDampingMethod". Also contains a
   `GAcquireInterface` target-acquisition system and a `GroupAttackEvent` combat-message
   class.
3. **MSVC CRT/ATL runtime-support glue** (lines ~1678486–1680716) — DllMain, `_onexit`,
   SEH/EH prologs, `/GS` stack-cookie checks, PE image validation, 64-bit division/shift
   intrinsics, and dozens of bare IAT import thunks. 100% compiler-generated, zero
   application logic.
4. **Locale/category-name resolver + generic STL container internals** (lines
   ~1680716–1683888) — a `setlocale`-style category matcher tied to a string labeled
   `s_soundbinary_...` (likely audio/sound-bank path resolution, not vegetation), plus
   red-black-tree and vector/array clear/erase templates for several fixed element sizes.
5. **Lock-guarded diagnostics/event-report family + generic reflection/property-tree
   runtime** (lines ~1681709–1687828) — dozens of near-identical "build a tagged event
   record, dispatch to a virtual sink" functions (the engine's thread-safe logging
   front-end), plus a full reflection/property-value runtime: typed container
   constructors, a critical-section-guarded "variant" value type with a type-tag scheme,
   open-chained hashtables, recursive tree validate/has-value walks, and a
   `NotifyPropertyChanging`/`NotifyPropertyChanged` pair. This is almost certainly the
   generic machinery that a reflected class like `VegetationZoneData` (mentioned in the
   task brief) would be *built on top of* — but it is itself reused by many unrelated
   reflected types across the engine, so it carries no vegetation-specific semantics.
6. **Generic asset-streaming (`.bao`/`.sbao`) loader glue, a node/expression-tree
   evaluator, a CString class implementation, a growable hashmap, and CPU/GPU
   hardware-detection code** (lines ~1687829–1691789) — including unambiguous CPUID
   vendor-string matching (`"GenuineIntel"`, `"AuthenticAMD"`, etc.) and a table mapping
   Intel integrated-GPU PCI device IDs to a capability enum. Definitively unrelated to
   vegetation.

**Why the "Vegetation" string was misleading:** the entry point `FUN_10ac0960` (line
1668186) does log under category `"Vegetation"`, and does delegate to `FUN_10acc170` — but
`FUN_10acc170` turned out to be a generic small-buffer-optimized container/record
constructor reused verbatim elsewhere in this same address range for the unrelated
`GroupAttackEvent` combat-message class. It carries no vegetation-specific fields. The
"Vegetation" string names an AI *consideration/criterion class* (one of seven siblings),
not a placement/scattering subsystem.

**Recommendation:** if a true vegetation-placement/scattering system exists in this DLL, it
is NOT in `FUN_10ac0000`–`FUN_10adffff`. The one genuinely vegetation-relevant code path
found here — `FUN_10ac5fb0`/`FUN_10ac5420`/`FUN_10ac56f0`/`FUN_10ac57a0`/`FUN_10ac58e0`
(concealment/coverage-by-foliage query for stealth AI) — is worth keeping on file as it
does touch "vegetation collision objects" and "vegetation zones" via RTTI-typed lookups
(`DAT_11234f50`, `DAT_11224e68`), which could be a useful breadcrumb toward wherever the
real placement/zone-loading code lives (possibly reachable from `DAT_11224e68`'s
registration site, or from `RegisterVegetationZoneProperties`/`FUN_102f3050`'s
call graph, neither of which was traced in this sweep).

**531 functions total in range; ~540 labeled below** (slight double-count from a couple of
functions independently flagged by two sweeps' boundary notes) — effectively exhaustive
coverage, grouped by sub-range below.

---

### Part 1 — AI Consideration/Criterion Scoring Framework (lines 1668028–1671881)

#### Named-Criterion Classes (constructors / destructors)

- `FUN_10ac0520` (line 1668086) — **CtorConsiderationPawnSampling** — constructor: logs category "PawnSampling", calls shared base-init `FUN_10acc170`, installs vtable `DAT_110f0de8`. Sibling of the Vegetation/Grass/Occlusion criterion classes below.
- `FUN_10ac0660` (line 1668138) — **DtorConsiderationPawnSampling** — destructor pattern (`FUN_10ac05f0` cleanup + optional `FUN_100eddc0` free), pairs with FUN_10ac0520's vtable.
- `FUN_10ac05f0` (line 1668125) — **ConsiderationPawnSampling_ReleaseMembers** — shared member-teardown helper called by the PawnSampling dtor and its own callee `FUN_10acc0c0` (base-class dtor for this criterion hierarchy).
- `FUN_10ac0700` (line 1668152) — **CtorConsiderationOcclusion** — constructor: logs category "Occlusion", same `FUN_10acc170` base-init pattern, vtable `DAT_110f0e10`.
- `FUN_10ac0960` (line 1668186) — **CtorConsiderationVegetation** — constructor: logs category "Vegetation" (the string that triggered this whole sweep), same base-init via `FUN_10acc170`, vtable `DAT_110f0e34`. This is the entry point of the "Vegetation" AI-criterion class, not a vegetation placement object.
- `FUN_10ac0a10` (line 1668219) — **DtorConsiderationVegetation** — destructor: calls shared base dtor `FUN_10acc0c0`, optional free.
- `FUN_10ac0f80` (line 1668416) — **CtorConsiderationGrass** — constructor: logs category "Grass", same pattern, vtable `DAT_110f0e50`; sets extra field `param_1[0xd] = -1` (probably a cached "last surface type"/"sample index" sentinel).
- `FUN_10ac12d0` (line 1668494) — **CtorConsiderationStance** — constructor: logs category "Stance", vtable `DAT_110f0ebc`.
- `FUN_10ac1520` (line 1668527) — **CtorConsiderationSpeed** — constructor: logs category "Speed", vtable `DAT_110f0ed4`; takes two extra params stored at `param_1[0xc]`/`[0xd]` (likely min/max speed thresholds or an inverted flag).
- `FUN_10ac1890` (line 1668691) — **CtorConsiderationAvatarSkill** — constructor: logs category "AvatarSkill", vtable `DAT_110f0eec`; builds up to 3 *child* criteria via `FUN_10ac1c60` (composite-list ctor), a nested Speed sub-criterion, and skill-gated sub-conditions (`FUN_10abf500`/`FUN_10abf7d0`). Composite/"AND-list of sub-considerations" case.
- `FUN_10ac1a60` (line 1668762) — **DtorConsiderationAvatarSkill** — destructor: tears down the composite child list (`FUN_10ac1b90`) then base dtor `FUN_10acc0c0` twice (own + composite base).

#### Composite Criterion List Support

- `FUN_10ac1a90` (line 1668778) — **EvaluateCompositeCriterionList** — walks a vector of child criterion pointers, calls each child's virtual scorer, multiplies together float10 scores from `FUN_10acc020` (AND-combination of consideration scores), early-returns 1.0 on hard-fail flag.
- `FUN_10ac1b60` (line 1668824) — **CompositeCriterionList_Dtor_ReleaseElements** — iterates the vector, calls each element's dtor (vtable+0x10).
- `FUN_10ac1b90` (line 1668842) — **DtorCompositeCriterionList** — full destructor: releases elements, frees backing array, resets inline string buffer, frees vector storage.
- `FUN_10ac1c40` (line 1668885) — **DtorCompositeCriterionList_Thunk** — thin wrapper calling `FUN_10ac1b90` then optional free — scalar deleting destructor thunk.
- `FUN_10ac1c60` (line 1668899) — **CtorCompositeCriterionList** — constructs the empty vector-of-children object; vtable `DAT_110f0f10`; logs a category name (unresolved string here).
- `FUN_10ac1cd0` (line 1668928) — **CopyCriterionRecord** — flat 0x54-byte struct copy-assignment for one criterion-list element record.
- `FUN_10ac1de0` (line 1669006) — **ConstructCriterionListNode** — placement-inits a list node's key, copies the record via `FUN_10ac1cd0`.
- `FUN_10ac1f30` (line 1669090) — **AllocateCriterionListNode** — `operator new`-style allocation of a list node (`CMTSafeAllocator<_Ty,_THeap>::Allocate`), links prev/next, constructs payload via `FUN_10ac1de0`. Generic linked-list node allocator, not vegetation-specific.
- `Catch@10ac1fbf` (line 1669119) — **CriterionListNodeAlloc_ExceptionCleanup** — SEH catch handler freeing a partially-constructed node then rethrowing.
- `FUN_10ac2260` (line 1669242) — **InsertCriterionListNode** — allocates a node via `FUN_10ac1f30` and splices it into a doubly-linked list.
- `FUN_10ac22a0` (line 1669256) — **CopyInsertCriterionListRange** — copies a range of nodes via `FUN_10ac2260`, SEH-guarded.
- `Catch@10ac2308` (line 1669278) — **CopyInsertCriterionListRange_ExceptionCleanup** — SEH cleanup, erasing partially-inserted nodes.
- `FUN_10ac24c0` (line 1669404) — **SpliceOrCopyCriterionListRange** — in-place splice when sharing an allocator/container id, else falls back to copy+erase (`std::list::splice`-style).
- `FUN_10ac1d60` (line 1668957) — **EraseCriterionListNode** — unlinks and frees one node.
- `FUN_10ac1da0` (line 1668978) — **ClearCriterionList** — unlinks/frees every node, resets sentinel, count=0.
- `FUN_10ac1e00` (line 1669018) — **HashMap_EraseAndRehashSlot** — hash bucket erase with `0xdeadbeef`-seeded hash, rehash-slot fixup, frees node. Generic hash-map internals, unrelated to vegetation.
- `FUN_10ac1ec0` (line 1669062) — **EraseCriterionListRange** — erase-range variant (handles "erase whole list" fast path).
- `FUN_10ac2120` (line 1669181) — **VegClusterHelper_10ac2120** — iterates a circular linked list of records, AABB-mask filter + float threshold compare, appends matches. Generic spatial-record filter/query helper, not proven vegetation-specific.
- `FUN_10ac1fe0` (line 1669133) — **VegClusterHelper_10ac1fe0** — same AABB-mask + float-threshold filter as above but over an array via hash lookup + dynamic-array append. Likely a generic "query registered records overlapping this cell/threshold" helper reused by several systems.
- `FUN_10ac2220` (line 1669225) — **HashMap_FindOrEnd** — bounds-checks an iterator against an end sentinel, used by hash-map lookup wrappers.

#### Generic Hash-Map / STL Container Internals (unrelated to vegetation)

- `FUN_10ac2340` (line 1669298) — **HashMap_RemoveNonMatchingByFlagMask** — filtered-removal helper for a hash-keyed registry (e.g. removing stale listeners by category flags).
- `FUN_10ac23d0` (line 1669336) — **AgeAndExpireTimedRecords** — walks a linked list, ages each record's timestamp by delta time, moves expired records into a sub-list. Generic timer/decay-list maintenance.
- `FUN_10ac2460` (line 1669377) — **CtorHashMapControlBlock** — small control-block constructor (copies key, gets allocator/heap handle) — generic map bookkeeping init.
- `FUN_10ac2540` (line 1669437) — **HashMap_InsertWithRehash** — full hash-map insert implementation: grows bucket array, rehashes, inserts node, throws `std::length_error("list<T> too long")` on overflow. Definitively generic STL-style `hash_map` insert.
- `FUN_10ac27f0` (line 1669573) — **DtorHashMapControlBlock** — frees bucket array and node storage, calls `FUN_10ac1da0` (ClearCriterionList) to release contained list.
- `FUN_10ac2890` (line 1669594) — **CtorHashMapWrapperObject** — constructs a wrapper object embedding a hash-map control block plus two allocations.
- `FUN_10ac28e0` (line 1669617) — **HashMap_FindEntryByKey** — builds GThread-guarded temporaries, calls insert-or-find, returns pointer into found record. GThread usage suggests cross-thread registry.
- `FUN_10ac2af0` (line 1669694) — **CompareCachedVsCurrentThreatRecord** — compares two threat/target record triples for equality; classifies change via TLS-cached "current threat" data. AI target/threat change-detection helper.
- `FUN_10ac2d50` (line 1669792) — **CheckGlobalCombatModeActive** — reads global "current combat/threat" pointer, compares against thread-local cached state, returns bool for "combat mode changed/active". Feeds the FSM dispatchers below.

#### AI Perception / Concealment Helpers (front/left/right occlusion, sun/wind angle)

- `FUN_10ac0a30` (line 1668233) — **ComputeFacingOcclusionSide** — computes forward vector, dot-products against a queried direction, classifies "hidden from front(0)/left(1)/right(2)".
- `FUN_10ac0c60` (line 1668307) — **ComputeOcclusionCriterionScore** — the "Occlusion" criterion's scorer: dot product forward-vs-sun-direction, classifies side via `FUN_10ac0a30`, derives a penalty score with an AI-target-visibility gate that can zero the score.
- `FUN_10ac1040` (line 1668451) — **FormatOcclusionDebugString** — builds "hidden from front/left/right (%1.0f deg%s)" debug string.
- `FUN_10ac1610` (line 1668578) — **ComputeSpeedCriterionScore** — the "Speed" criterion's scorer: fetches thread-local speed-reference, computes ratio via `FUN_10acc020` shared curve/falloff evaluator, clamps [0,1].
- `FUN_10ac1750` (line 1668635) — **FormatSpeedOrStanceDebugString** — debug text for Speed/Stance criterion state.

#### Creature/Pawn AI Finite-State-Machine (perception-driven behavior states)

- `FUN_10ac3020` (line 1669933) — **TriggerAlertMemoryUpdateIfNear** — updates an AI's "point of interest" memory when the pawn moved beyond a threshold or target-type changed.
- `FUN_10ac31e0` (line 1669982) — **NotifyThreatStateChange** — compares cached vs current threat; on genuine change stores new threat position/handle into globals, else fires network/replication event for threat visibility change.
- `FUN_10ac3440` (line 1670065) — **DispatchCreatureStateEvent_Base** — switch on event/message id driving alert/threat notifications and generic FSM state-transition calls. Base/default event handler.
- `FUN_10ac3580` (line 1670120) — **DispatchCreatureStateEvent_VariantA** — near-duplicate of base handler with vtable-indirected per-event callbacks; one creature "behavior profile"/species FSM variant.
- `FUN_10ac38e0` (line 1670236) — **DispatchCreatureStateEvent_VariantB** — second species/profile variant.
- `FUN_10ac3c40` (line 1670330) — **DispatchCreatureStateEvent_VariantC** — third species/profile variant.
- `FUN_10ac3f00` (line 1670411) — **DispatchCreatureStateEvent_VariantD** — fourth variant.
- `FUN_10ac41c0` (line 1670496) — **DispatchCreatureStateEvent_VariantE** — fifth variant.
- `FUN_10ac4470` (line 1670577) — **DispatchCreatureStateEvent_VariantF** — sixth variant (identical body to VariantD).
- `FUN_10ac4720` (line 1670658) — **DispatchCreatureStateEvent_Minimal** — reduced-case version; likely "simple creature" (non-predator) FSM variant.
- `FUN_10ac4780` (line 1670691) — **TickCreatureAiPerceptionAndFsm** — master per-frame update: LOD/remote bail-out, target visibility distance, threat-change check, dispatches to species-specific Variant A–F handler, iterates a global creature-perception table checking each perceiver's LOS state.

#### AI Detection Meter (sight/sound/touch accumulation)

- `FUN_10ac4c90` (line 1670913) — **ClearAllPerceptionFlags** — clears 17 individual bit flags on a detection-meter status word.
- `FUN_10ac4cf0` (line 1670941) — **ResetDetectionMeterTimersA** — resets 8 timer/float fields to a sentinel, 2 counters to 0.
- `FUN_10ac4d30` (line 1670963) — **ResetDetectionMeterTimersB** — fuller reset: zeroes header fields, resets ~13 timer fields, copies shared "last known position" into sight/sound memory slots.
- `FUN_10ac4e30` (line 1671015) — **UpdateDetectionMeter** — core per-tick accumulator: for sight/sound/touch inputs, sets status bits and accumulates elapsed time into per-sense timers; sets escalation bits ("noticed"/"fully detected") past thresholds. Classic stealth-game "detection meter" tick.

#### Debug Visualization / Text-Overlay Helpers

- `FUN_10ac5c10` (line 1671658) — **DrawCriterionScoreLabel** — formats "Value: %0.2f", draws via 3D screen-space text. Used by Vegetation/Occlusion criteria to show live score above pawn's head in debug builds.
- `FUN_10ac5e20` (line 1671728) — **DrawTransparencyDebugLabel** — formats "Transparency: %0.2f,\nRunning transparency: %0.2f" — debug overlay for a (likely vegetation-driven) transparency/fade value, e.g. camera-occlusion-by-foliage fade.
- `FUN_10ac50d0` (line 1671173) — **TransformAndDrawDebugMarker** — generic debug-draw wrapper reused by `FUN_10ac5fb0`.

#### Vegetation-Coverage / Concealment Query (the one genuinely vegetation-relevant code path in the whole sweep)

- `FUN_10ac0300` (line 1668028) — **EvaluateNamedCriterionScore** — generic per-criterion score entry point: looks up a category record matching the pawn's zone/index, dispatches to `FUN_10ac5fb0` (Vegetation path, confirmed) or `FUN_10ac6220` (sibling Grass-path scorer, outside this file's range).
- `FUN_10ac5fb0` (line 1671787) — **ComputeVegetationCoverageScore** — the concrete Vegetation-criterion scorer: resolves "required vegetation types" list, gathers nearby foliage-collision objects near the pawn via `FUN_10ac58e0`, builds a coverage fraction in [0,1], draws debug feedback with distinct full/partial/none colors. A *concealment/coverage query* ("is the pawn hidden by enough vegetation"), not a placement or scattering routine.
- `FUN_10ac5420` (line 1671326) — **SampleFoliageCoverageAlongSegment** — iterates a global registered-zone list (`DAT_11224e68`), performs capsule/segment queries against each zone, accumulates a "covered length" vs total segment length. Underlying "how much of this line/capsule is inside foliage volumes" sampler.
- `FUN_10ac56f0` (line 1671433) — **GatherNearbyVegetationCollisionObjects_Single** — fetches pawn's collision zone, gets cached "vegetation collision" RTTI slot, appends matching object. One-object variant.
- `FUN_10ac57a0` (line 1671472) — **GatherNearbyVegetationCollisionObjects_Multi** — same RTTI-filtered gather but iterates a whole list of nearby collision proxies.
- `FUN_10ac58e0` (line 1671527) — **GatherNearbyVegetationCollisionObjects_Combined** — orchestrates single-zone and multi-proxy gathers into one combined output list, plus an extra RTTI-gated pass for "climbable"-tagged objects. Exact helper called by `FUN_10ac5fb0`'s coverage computation.
- `FUN_10ac5090` (line 1671152) — **IsClimbableSurfaceRttiMatch** — small RTTI-check predicate used to filter gathered objects.
- `FUN_10ac51a0` (line 1671205) — **GetOrRefreshLastKnownFoliagePosition** — RTTI-gated getter/setter for a cached position, refreshes internal timer when RTTI check passes.
- `FUN_10ac53b0` (line 1671301) — **GetCurrentFoliageContactPointOrFallback** — reads a cached contact-point record if present, else falls back to `FUN_10ac51a0`.

#### Audio / VO Trigger Helpers (adjacent, not vegetation-placement)

- `FUN_10ac4f80` (line 1671083) — **PlayFootstepOrMovementVoLoop** — plays/queues VO or SFX per position; likely a footstep-through-foliage rustle-sound trigger (thematically vegetation-adjacent but audio, not placement).
- `FUN_10ac5290` (line 1671248) — **PlaySurfaceContextVoLine** — resolves a material/surface id, plays a surface-dependent one-shot VO/SFX line (e.g. footstep-in-grass sound).

#### Small/Generic Vtable Wrappers

- `FUN_10ac5000` (line 1671112) — **CallCriterionSubsystemVtable_Idx4** — one-liner: `vtable[0x18](4, param_2)`.
- `FUN_10ac5020` (line 1671123) — **CallCriterionSubsystemVtable_Idx7** — one-liner: `vtable[0x18](7, param_2)`.
- `FUN_10ac5040` (line 1671134) — **CallCriterionSubsystemVtable_ConditionalIdx0OrDirect** — branches on a vtable+0xd8 bool to call one of two vtable slots.

---

### Part 2 — 2D Local-Avoidance / Steering Subsystem (lines 1671882–1675988)

Strongest evidence: `FUN_10aca480`'s debug-HUD string `"Speed: %0.1f\n%s\nDirection: %s\nAborted: %i\nEdges in memory: %i\nObstacles in memory: %i\n"`, and the named constant `s_333_TurnAroundAngleDampingMethod_11014d6c` referenced in `FUN_10acc1e0`.

##### Debug / Diagnostics

- `FUN_10aca480` (line 1674544) — **DrawAvoidanceDebugOverlay** — formats and draws the "Speed/Direction/Aborted/Edges in memory/Obstacles in memory" debug HUD.

##### Local-Avoidance / Steering Core

- `FUN_10ac6940` (line 1672225) — **InitAvoidanceCandidateEdgeBuffer** — resets a small candidate-edge array to shared zero-vector cache.
- `FUN_10ac6870` (line 1672182) — **ReleaseAvoidanceEdgeBuffer** — cleanup counterpart of `FUN_10ac6940`.
- `FUN_10ac6dd0` (line 1672410) — **ComputeObstacleTangentPoints** — computes tangent points from a query point to a convex obstacle boundary; visibility-graph tangent computation for path-around-obstacle planning.
- `FUN_10ac7a70` (line 1672984) — **ComputeCircularObstacleAvoidancePlane** — computes tangent contact point and avoidance half-plane/edge equation for a circular obstacle.
- `FUN_10ac7c40` (line 1673049) — **BuildObstacleAvoidanceContact** — produces an avoidance contact for a circular obstacle.
- `FUN_10ac7ea0` (line 1673141) — **BuildObstacleAvoidanceContactSimple** — simplified/stationary-obstacle variant.
- `FUN_10ac8dd0` (line 1673655) — **ComputeSteeringLookaheadDistance** — velocity-scaled lookahead/prediction distance, clamped to max.
- `FUN_10acc1e0` (line 1675662) — **ComputeSteeringLookaheadDistance_TurnDamped** — near-duplicate using `s_333_TurnAroundAngleDampingMethod_11014d6c`. Confirms "turn-around/steering damping" semantics.
- `FUN_10ac8e90` (line 1673686) — **SmoothSteeringDirectionChange** — blends with previous direction to smooth abrupt turns.
- `FUN_10ac9330` (line 1673863) — **ClipAndCacheAvoidanceCorner** — clips a segment against a half-plane, dedups corner point in a small hash-cache.
- `FUN_10ac9720` (line 1673985) — **SelectAndNormalizeSteeringDirection** — selects a candidate direction by mode flag.
- `FUN_10ac9800` (line 1674028) — **ProcessTriangleEdgesForAvoidance** — iterates a navmesh triangle's boundary edges, feeding each into `FUN_10ac9330`.
- `FUN_10ac9960` (line 1674076) — **GatherAvoidanceEdgesAlongSweep** — broad-phase swept query along movement direction; processes hit triangles and static obstacle records into a combined avoidance-edge list.
- `FUN_10ac9e30` (line 1674270) — **GatherNearbyAgentsForAcquire** — spatial-queries nearby entities, resolves to agent/character objects, filters by height/type + visibility-range test.
- `FUN_10aca400` (line 1674518) — **GatherNearbyAgentsProfiled** — profiling-wrapped call into `FUN_10ac9e30` with fixed capacity 16.
- `FUN_10aca290` (line 1674452) — **GetCurrentSteeringDirectionOrDefault** — returns normalized 2D steering direction, override to cached fallback when blocked flag set.
- `FUN_10acad40` (line 1674867) — **BuildObstacleAvoidanceContactList** — core per-obstacle solver: ray/segment intersection classifies moving vs static contact, builds contacts, caches per-obstacle direction data.
- `FUN_10acb3b0` (line 1675072) — **RegisterAvoidanceEdgesForFrame** — collects contacts from `FUN_10acad40` plus a static-obstacle pass, registers resulting edges into working edge-sets for the frame's steering solve.
- `FUN_10acb630` (line 1675224) — **ResolveSteeringDirectionAgainstEdges** — iteratively resolves desired direction against registered edges; sets "blocked" flag on hard block.
- `FUN_10acb8d0` (line 1675313) — **UpdateSteeringOutputDirection** — top-level per-tick steering update: speed, nav-triangle validation, gathers nearby agents, picks best avoidance target, resolves final direction.
- `FUN_10acbbe0` (line 1675417) — **GetOrUpdateSteeringOutput** — returns pointer to steering-output block; runs full update or returns static fallback.

##### Target Acquisition (`GAcquireInterface`)

- `FUN_10ac8610` (line 1673401) — **UpdateTargetAcquisition** — `GAcquireInterface`-based reacquisition: distance/visibility test, performs acquire, updates tracked position/radius via vtable dispatch.
- `FUN_10ac8f90` (line 1673719) — **IsCandidateWithinAcquireRange** — vtable LOS query + radius test.
- `FUN_10acc3b0` (line 1675766) — **IsCandidateWithinAcquireRange_Variant2** — near-duplicate using a second radius field, likely secondary/extended-range acquire check.

##### Nav-Triangle / Surface Queries

- `FUN_10ac7390` (line 1672657) — **IsEntityOnSpecialSurface** — queries a surface-type registry against a flag bit; likely "is on water" style check.
- `FUN_10ac9110` (line 1673793) — **TestPointAgainstNavTriangle** — resolves nav triangle at a query position, tests local coords against barycentric bytes within tolerance.
- `FUN_10acc2a0` (line 1675694) — **RefreshCachedNavTriangleRef** — re-resolves/caches a reference to the current navmesh triangle/surface object.
- `FUN_10ac7420` (line 1672694) — **ResolveComponentPointerViaRegistry** — resolves a sub-component pointer via one of two registries; generic component lookup used by steering code.
- `FUN_10ac88c0` (line 1673492) — **ResolveLinkedComponentHandle** — resolves a component pointer through masked id fields.

##### Obstacle / Edge Geometry Helpers

- `FUN_10ac6760` (line 1672127) — **SetEdgeEndpointAndLength** — sets segment end point and recomputes cached edge length.
- `FUN_10ac6c60` (line 1672361) — **IsDirectionPairWithinAngleThreshold** — normalizes two direction pairs, tests dot-product angle threshold; used for corner-validity checks.
- `FUN_10ac7610` (line 1672762) — **BuildPaddedEdgeQuad** — constructs a padded rectangle around a 2D segment offset outward by radius.
- `FUN_10ac7760` (line 1672806) — **ClipSegmentAgainstQuadEdges** — Sutherland-Hodgman-style clip of a segment against two half-plane edges.
- `FUN_10ac7a00` (line 1672949) — **FindNextValidPathCorner** — walks a chain of candidate points validating direction continuity; corner-chain traversal for path smoothing.
- `FUN_10acc510` (line 1675833) — **TestPaddedEdgeQuadsOverlap** — tests 4 padded rectangles pairwise for overlap to detect crossing/self-intersecting avoidance corridors.
- `FUN_10ac6220` (line 1671882) — **ComputeVisibilityOcclusionFraction** — accumulates a line-of-sight-blocking "coverage" fraction across a list of shape/obstacle records; debug-draws each contribution in a distinct color. Plausibly a cover/stealth-LOS helper adjacent to, but distinct from, the steering solver — and the same "Grass" sibling scorer referenced by `FUN_10ac0300` in Part 1.

##### Object Lifecycle (Constructors / Destructors)

- `FUN_10ac6690` (line 1672074) — **ConstructAvoidanceEdgeNode** — initializes an obstacle-avoidance graph edge/node object.
- `FUN_10ac8140` (line 1673238) — **ResetAvoidanceState** — unregisters an event/listener then resets avoidance counters/flags to defaults.
- `FUN_10ac8270` (line 1673259) — **SetAvoidanceTargetMode** — changes current avoidance target/mode field, releasing prior resource when applicable.
- `FUN_10ac8380` (line 1673279) — **InitThreeVectorsToZeroDefault** — initializes 3 consecutive Vector3 fields to shared zero-vector cache.
- `FUN_10ac8a90` (line 1673536) — **DestructAvoidanceComponentBase** — multi-stage destructor.
- `FUN_10ac8c40` (line 1673569) — **ScalarDeletingDtor_AvoidanceComponent** — wraps `FUN_10ac8a90` + conditional self-free.
- `FUN_10ac8c70` (line 1673583) — **ConstructAvoidanceComponentBase** — full constructor: vtables, zero-inits vector cache, registers with global system.
- `FUN_10ac8d40` (line 1673618) — **DestructDerivedAvoidanceComponent** — unregisters callback, then base dtor.
- `FUN_10ac8d80` (line 1673634) — **ScalarDeletingDtor_DerivedAvoidanceComponent** — as above + conditional self-free.
- `FUN_10aca890` (line 1674708) — **ConstructLocalAvoidanceController** — full constructor: reserves internal arrays matching the "Edges/Obstacles in memory" HUD counters.
- `FUN_10acaba0` (line 1674820) — **DestructLocalAvoidanceController** — mirrors teardown pattern.
- `FUN_10acad20` (line 1674853) — **ScalarDeletingDtor_LocalAvoidanceController**.

##### Combat Event Messaging (`GroupAttackEvent`)

- `FUN_10acbfa0` (line 1675545) — **ConstructGroupAttackEvent** — constructs a `"GroupAttackEvent"` message object (explicit string literal). Confirms a combat/AI-messaging class is interleaved in this address range.
- `FUN_10acbec0` (line 1675484) — **DestructGroupAttackEvent** — releases refs.
- `FUN_10acbf40` (line 1675513) — **ScalarDeletingDtor_GroupAttackEvent**.

##### Generic Container / Utility (incl. delegate target `FUN_10acc170`)

- `FUN_10acc0c0` (line 1675617) — **ConstructSmallBufferContainer** — default constructor for a 15-capacity small-buffer-optimized array/string container; companion to `FUN_10acc170`.
- `FUN_10acc170` (line 1675638) — **ConstructWeightedBufferFromSource** — **[delegate target of the "Vegetation"-tagged logger `FUN_10ac0960`]**. Generic constructor: stores an id/flags value, copies a field from source, initializes the same 15-capacity inline buffer as `FUN_10acc0c0`, move-clears the source, stores an instance "weight" multiplier. **Nothing references vegetation, zones, density, scatter, or terrain** — shape-identical to a reusable container used elsewhere in this same address range for the unrelated `GroupAttackEvent`. Confirms the "Vegetation" logger just reuses generic container infrastructure.
- `FUN_10acc020` (line 1675579) — **ApplyWeightedFalloff** — blends a base falloff/weight with the instance multiplier set by `FUN_10acc170`.
- `FUN_10acc080` (line 1675598) — **LinearRampFalloff** — standard clamped linear interpolation ramp; generic falloff curve helper.

##### Generic Array / Math Helpers

- `FUN_10ac6670` (line 1672060) — **ShiftEdgeSegmentToNext** — edge-iteration helper.
- `FUN_10ac67c0` (line 1672148) — **DestructElementRange_0x14** — erases/destructs a run of 20-byte-stride elements.
- `FUN_10ac6820` (line 1672159) — **FillElementRange_0x14** — fills a range of 20-byte elements with a copy.
- `FUN_10ac68d0` (line 1672203) — **ResizeEdgeArray_0x14** — vector-resize equivalent for the 20-byte-stride element array.
- `FUN_10ac6b30` (line 1672306) — **FindMinScoreElement** — linear scan for smallest-score array element.
- `FUN_10ac6b90` (line 1672332) — **NormalizeVectorWithFallback** — normalizes a vector, falls back on near-zero.
- `FUN_10ac8480` (line 1673327) — **UpdateSmoothedOrientationDerivative** — computes a dot-product metric and its rate of change over a timestep.
- `FUN_10ac9260` (line 1673849) — **DestructFourSubobjects_Trivial** — trivial destructor invoking a generic dtor thunk on 4 embedded sub-objects.

**Part 2 verdict:** Contradicts vegetation hypothesis — self-contained AI local-avoidance/steering subsystem plus `GAcquireInterface` acquisition and `GroupAttackEvent` messaging.

---

### Part 3 — Second Avoidance Block, then MSVC CRT/ATL Runtime (lines 1675989–1679909)

Hard transition at line **1678486** from avoidance/steering code into stock MSVC CRT/ATL runtime-support code.

#### Group A — Local-avoidance / turn-around steering subsystem (continued from Part 2)

- `FUN_10acc8c0` (line 1675989) — **ClearAvoidanceEdgeAndObstacleLists** — calls generic container-destroy helper four times; "reset working lists" call at top of the per-frame update.
- `FUN_10acc990` (line 1676003) — **PruneStaleObstacleEdgeCacheEntries** — drops edge-cache entries farther than a threshold from the agent's cached position.
- `FUN_10accad0` (line 1676055) — **PruneStaleObstacleVertexCacheEntries** — sibling of the above for the vertex array.
- `FUN_10accbc0` (line 1676104) — **RefreshNeighborAverageEdgeMidpoint** — averages an edge's two endpoints and stores the midpoint.
- `FUN_10accd20` (line 1676176) — **UpdateObstacleEdgeVisibilityFlags** — builds a normalized 2D movement tangent, constructs two wedge triangles, toggles visibility flag bits.
- `FUN_10acd310` (line 1676317) — **IsPointInsideObstacleWedge** — half-plane/wedge containment test against a 5-float edge struct.
- `FUN_10acd3d0` (line 1676342) — **IsPointStrictlyInsideObstacleWedge** — strict variant, used together with the above.
- `FUN_10acd490` (line 1676367) — **DoObstacleWedgesOverlap** — ORs four wedge-containment tests across two wedges' endpoints.
- `FUN_10acd4f0` (line 1676395) — **AreObstacleWedgesFullyContained** — combines strict/non-strict wedge tests to check subsumption.
- `FUN_10acd550` (line 1676423) — **ClipSegmentAgainstObstacleEdgeAndCache** — clips a segment against a plane, dedupes against a cached-quad array before inserting; core cache-builder feeding the pruned arrays above.
- `FUN_10acd910` (line 1676549) — **RaycastMidpointBetweenPositions** — averages two points, runs shared swept-raycast primitive pair to test LOS/collision between them.
- `FUN_10acda70` (line 1676610) — **TestAvoidanceWedgePathClear** — heaviest geometry routine: 3-stage gate scan; returns whether the avoidance corridor is fully clear.
- `FUN_10ace260` (line 1676899) — **ResolveWedgeEdgeDirection** — looks up a neighbor's cached edge; falls back to raw wedge direction test; normalizes and writes 2D result.
- `FUN_10ace340` (line 1676933) — **RebuildRelativeObstacleEdgeList** — re-expresses each raw edge relative to the agent origin, computes cross-product sign flag.
- `FUN_10ace4a0` (line 1676979) — **ProcessObstacleTriangleFanEdges** — for triangle-fan obstacle entries, forwards each mini-segment to `ClipSegmentAgainstObstacleEdgeAndCache`.
- `FUN_10ace5b0` (line 1677019) — **ComputeAvoidanceTangentCandidates** — largest per-agent routine: RVO/ORCA-style "candidate velocity" step, computes left/right avoidance tangent rays.
- `FUN_10aceee0` (line 1677276) — **TraceDirectionAcrossWedgeBoundary** — orders two directions by half-plane test, resolves the boundary-crossing exit direction.
- `FUN_10acf110` (line 1677370) — **GetAgentAvoidanceVelocityOutput** — rebuilds relative edge list, returns cached avoidance direction or raw stored velocity depending on "resolved" flag; increments an "aborted" counter consumed by the debug overlay.
- `FUN_10acf220` (line 1677424) — **CollectNearbyAgentsWithinTurnCone** — KD-tree-style recursive neighbor query, gated against `s_333_TurnAroundAngleDampingMethod` threshold. **Strongest single evidence for "turn-around damping" steering hypothesis.**
- `FUN_10acf660` (line 1677611) — **QueryTurnConeNeighborsProfiled** — thin profiler-wrapped entry point around `CollectNearbyAgentsWithinTurnCone`.
- `FUN_10acf6e0` (line 1677637) — **DrawAvoidanceDebugOverlay** — renders "Speed/Direction/Aborted/Edges in memory/Obstacles in memory" debug text. **Direct textual confirmation of the obstacle/edge avoidance subsystem.**
- `FUN_10acfaf0` (line 1677800) — **InitAvoidanceAgentRuntimeState** — constructor-shaped init of per-agent local-avoidance record.
- `FUN_10acfe30` (line 1677924) — **IntersectPathAgainstObstacleSet** — iterates obstacle-pointer array, runs segment-intersection tests, grows a result array — feeds `GatherObstacleHitsAroundAgent`.
- `FUN_10ad04a0` (line 1678129) — **GatherObstacleHitsAroundAgent** — calls `IntersectPathAgainstObstacleSet`, pushes hits into edge and raw-obstacle lists, folds in currently-locked persistent obstacles. Still part of the avoidance cluster (the flagged transition at this line is a false alarm — real break is ~360 lines later).
- `FUN_10ad0780` (line 1678228) — **SolveAvoidanceApexDirection** — iterative funnel/apex-refinement loop narrowing a steering direction until convergence, with a final clearance check.
- `FUN_10ad0a50` (line 1678326) — **UpdateAgentTurnAroundAvoidance** — per-frame driver: computes speed, derives turn radius, resets working lists, queries nearby agents in the turn cone, solves apex direction. Ties directly to the "TurnAroundAngleDampingMethod" string.
- `FUN_10ad0d10` (line 1678419) — **GetOrComputeAgentAvoidanceVelocity** — public "get this frame's steering velocity" entry point, checks a type-GUID cache to decide whether to run full avoidance update or return raw stored velocity. Last function of the avoidance cluster.

#### Group B — MSVC CRT / ATL / DllMain runtime support (transition at line 1678486)

Ghidra-identified library functions requiring no rename (listed for completeness): `std::_Init_locks::operator=`, `ATL::_AtlGetThreadACPFake`, `ATL::_AtlGetThreadACPThunk`, `` FID_conflict:`vector_deleting_destructor' ``, `__onexit`, `___DllMainCRTStartup`, `__DllMainCRTStartup@12`, `__alloca_probe`, `__alloca_probe_16`, `__alloca_probe_8`, `__aulldiv`, `__alldiv`, `__allmul`, `__aulldvrm`, `__aullrem`, `__allshl`, `__aullshr`, `__allrem`, `__allshr`.

- `FUN_10ad1240` (line 1678843) — **OnExitTableUnlock** — lock-release counterpart used inside `__onexit`'s critical section.
- `FUN_10ad1249` (line 1678854) — **OnExitPublicWrapper** — public-facing wrapper around `__onexit`; corresponds to CRT `_onexit()` entry point.
- `FUN_10ad12d8` (line 1678895) — **CrtLoaderLockAttachDetachHandler** — internal DLL_PROCESS/THREAD-ATTACH/DETACH synchronization used by `___DllMainCRTStartup`.
- `FUN_10ad15a6` (line 1679036) — **ClearCachedModuleHandle** — one-liner, part of DllMain cleanup.
- `FUN_10ad1910` (line 1679562) — **FloatToInt64_RuntimeDispatch** — branches between SSE-safe rounding path and raw x87 truncation (MSVC `_ftol3`-style).
- `FUN_10ad1946` (line 1679595) — **FloatToInt64_X87Round** — x87 round-to-nearest float→int64 conversion body (`_ftol2`-style).
- 41 bare IAT import-thunk trampolines at lines 1678573–1679899 (`FUN_10ad10e8` through `FUN_10ad1b1c`) — **CRT_ImportThunk_<addr>** — single indirect calls through imported-function pointers; zero semantic signal.

**Part 3 verdict:** Contradicts vegetation hypothesis for the first 27 functions (avoidance/steering continuation); the remainder is pure compiler-generated CRT/ATL glue.

---

### Part 4 — CRT Internals, Locale Resolver, STL Internals, Diagnostics-Event Family (lines 1679910–1683888)

#### Dense run — genuine MSVC/CRT runtime-support code (not application logic)

Recognizable library internals (no rename needed): `__security_check_cookie`, `__ArrayUnwind`, `` `eh vector destructor iterator' ``, `__SEH_prolog4`/`__SEH_epilog4`, `__ValidateImageBase`, `__FindPESection`, `__IsNonwritableInCurrentImage`, `_DllMain@12`, `___security_init_cookie`, `__get_sse2_info`, `___report_gsfailure`, `__EH_prolog3_catch`/`__EH_epilog3`.

- `FUN_10ad1b98` (line 1680107) — **EHCatchDispatch_10ad1b2e** — EH-prolog3/epilog3-wrapped call into an IAT thunk; catch-block trampoline.
- `Catch_All_10ad1bbd` (line 1680123) — **RTTI_CatchAllHandler_10ad1bbd** — SEH-generated `catch(...)`/unwind funclet.
- `FUN_10ad1c70` (line 1680187) — **EHVectorUnwindContinuation** — conditionally re-enters `__ArrayUnwind`; part of vector-dtor unwind chain.
- `FUN_10ad1f78` (line 1680481) — **ConstTrueHelper** — trivial `return 1` stub used as a feature-flag gate inside `__get_sse2_info`.
- ~24 bare IAT import-thunk trampolines interleaved through this section (lines 1679921–1680742) — **IATThunk_<addr>** — zero semantic signal.

#### Locale/category-name & path-normalization cluster (possible sound-bank path resolver; NOT vegetation)

- `FUN_10ad32b0` (line 1680742) — **InitCategoryNameDefaultBuffer** — copies a default category-name string into a fixed buffer; references string label `s_soundbinary__1123a600` as fallback value.
- `FUN_10ad3310` (line 1680762) — **TeardownCategoryLinkedList** — generic intrusive-list teardown (locale-category-object list, by structure).
- `FUN_10ad33d0` (line 1680806) — **FreeCategoryBuffer** — wrapper around a free call.
- `FUN_10ad33e0` (line 1680817) — **GetCategoryNameBufferPtr** — returns address of a fixed static buffer.
- `FUN_10ad3400` (line 1680827) — **ResetCategoryList** — resets/reinitializes the category buffer, tears down linked list.
- `FUN_10ad3430` (line 1680843) — **MatchAndCopyCategoryName** — `setlocale`-style category-name matcher, optionally case-normalizing.
- `FUN_10ad3540` (line 1680896) — **ResolveCategoryName** — walks the category list matching names, falls back to `s_soundbinary` default string.
- `FUN_10ad36c0` (line 1680943) — **GetOrCreateCategoryLockObject** — lazily allocates a lock/vtable object at `DAT_1123a718`.
- `FUN_10ad3710` (line 1680969) — **NormalizeAndStoreCategoryPath** — copies a string, flips `/`↔`\` path separators, stores normalized result while holding the lock.
- `FUN_10ad38b0` (line 1681072) — **RegisterCategoryEntry** — lock-guarded lookup/store into the category registry.
- `FUN_10ad39b0` (line 1681140) — **RBTreeInorderStep** — classic `std::_Tree` in-order predecessor/successor traversal (generic STL internals).
- `FUN_10ad3a00` (line 1681179) — **RegisterSdkVersion_34_0_21** — thin wrapper forwarding a literal `"34.0.21"` version string; likely a middleware/SDK version-registration or compatibility-check call.
- `FUN_10ad3a20` (line 1681190) — **ConvertScaledValue** — lock-guarded float conversion, multiplies by a global scale; generic unit-conversion helper.
- `FUN_10ad3bf0` (line 1681213) — **UMin** — trivial `uint min(a,b)`.
- `FUN_10ad3da0` (line 1681226) — **BoundedStringCopy** — `strncpy`-with-truncation-and-length-return helper.

#### STL container-internals run (vector/tree clear & erase templates — generic, size-parameterized)

- `FUN_10ad3f40` (line 1681260) — **RBTreeUnlinkNode** — splices a node out of a tree structure.
- `FUN_10ad3fa0` (line 1681289) — **FreeIfNonNull** — trivial guarded free.
- `FUN_10ad3fc0` (line 1681302) — **BoundedStringCopySameLen** — wrapper forwarding to `FUN_10ad3da0`.
- `FUN_10ad3fe0` (line 1681313) — **CheckedResourceQuery** — lock-guarded query with conditional cleanup; returns bool.
- `FUN_10ad4020` (line 1681330) — **ClearRecordArray_12B** — destroys a dynamic array of 12-byte records (`std::vector<T>::clear`-style).
- `FUN_10ad4070` (line 1681361) — **FreeBinaryTreeRecursive** — recursively frees a binary-tree-shaped structure (postorder teardown).
- `FUN_10ad40d0` (line 1681379) — **PopAndReleaseRefcountedStack** — pops stack slots, atomically decrements refcount, calls virtual dtor at refcount 0.
- `FUN_10ad4120` (line 1681410) — **ClearElementArray_24B_a** — fixed-stride (24B) array-clear loop, lock-guarded.
- `FUN_10ad4170` (line 1681431) — **ClearElementArray_24B_b** — same shape, distinct offset.
- `FUN_10ad41c0` (line 1681452) — **ClearElementArray_72B** — same shape, 72-byte stride.
- `FUN_10ad4210` (line 1681473) — **ClearElementArray_12B** — same shape, 12-byte stride.
- `FUN_10ad4260` (line 1681494) — **ClearElementArray_8B** — same shape, 8-byte stride.
- `FUN_10ad42b0` (line 1681515) — **TreeLowerBoundSearch** — `std::map::lower_bound`-style binary-descent search.
- `FUN_10ad45a0` (line 1681548) — **DestroyVectorBuffer_24B_a** — frees a dynamic array and zeroes vector-control-block triple.
- `FUN_10ad45f0` (line 1681572) — **DestroyVectorBuffer_12B** — same shape, 12-byte stride.
- `FUN_10ad4640` (line 1681596) — **DestroyVectorBuffer_24B_b** — same shape, different reset field offset.
- `FUN_10ad4690` (line 1681620) — **DestroyVectorBuffer_72B** — same shape, 72-byte stride.
- `FUN_10ad46e0` (line 1681644) — **TreeEraseNode** — `std::map`/`std::set::erase` core.
- `FUN_10ad47a0` (line 1681691) — **ReleaseComLikeResourceSet** — conditional teardown calling paired release functions; looks like a COM/refcounted-interface release bundle.

#### GThread lifecycle & lock-guarded diagnostic/event-report family

- `FUN_10ad4a40` (line 1681709) — **FixupChildBackPointer** — patches a sub-object's back-reference field; generic parent-link fixup.
- `FUN_10ad4a80` (line 1681725) — **GetOrCreateManagerSingleton_0xF0** — lazily allocates a 240-byte singleton object.
- `FUN_10ad4ac0` (line 1681745) — **GetOrCreateManagerSingleton_0x1C** — lazily allocates a 28-byte singleton object (reused by wrappers later in Part 4).
- `FUN_10ad4b00` (line 1681765) — **ResetRecordFields3** — frees one buffer member, zeroes three struct fields.
- `FUN_10ad4b30` (line 1681782) — **ClearHashBucketArray** — iterates a hash-bucket pointer array, frees each chained node.
- `FUN_10ad4be0` (line 1681822) — **ConstructEventPayloadRecord** — 8-field record constructor feeding the report functions below.
- `FUN_10ad4c60` (line 1681849) — **EventRecordDestructor** — virtual-style destructor swapping vtable pointers, frees extra buffer.
- `FUN_10ad4da0` (line 1681867) — **ThreadExitCleanupHandler** — lock-guarded thread-teardown routine calling multiple subsystem shutdown functions and `GThread::OnExit`.
- `FUN_10ad4ec0` (line 1681931) — **ReportDiagnosticEvent_110f1668** through `FUN_10ad6b80` (line 1683551) — a family of ~20 near-identical **ReportDiagnosticEvent_<tag>** functions (each builds a lock-guarded tagged event record with a distinct message-tag data pointer and payload arity, dispatches via a virtual sink at `DAT_1123a718`). This is the engine's generic thread-safe logging/diagnostics front-end — not vegetation-specific. Individual tags: `110f1668`, `110f1694`, `110f1870`, `110f1894`, `110f18b8`, `110f18dc`, `110f16c0` (x2 ctor variants), `110f172c`, `110f1780` (conditional), `110f17a4` (conditional), `110f1900` (4 arity variants), `110f1924` (4 arity variants), `110f1948` (2 variants), `110f17c8`.
- `FUN_10ad5110` (line 1682057) — **DispatchToSubsystem_0xFFF** — lock-guarded pass-through with fixed flag `0xfff`.
- `FUN_10ad51c0` (line 1682094) — **DispatchToSubsystem_0** — same shape, fixed flag `0`.
- `FUN_10ad5b60` (line 1682617) — **LockGuardedQuery_10af00e0** — lock-guarded pure query wrapper, no record built.

#### Tail run — lock-guarded pass-through wrappers around FUN_10ae/FUN_10af implementation calls

- `FUN_10ad6ce0` (line 1683628) — **LockGuardedFloatOp_10aeffa0** — lock-guarded float10 wrapper.
- `FUN_10ad6e50` (line 1683664) — **LockGuardedCall_10aefed0** — lock-guarded 2-arg pass-through.
- `FUN_10ad6ed0` (line 1683697) — **LockGuardedCall_10af07a0** — lock-guarded 2-arg pass-through; lazily creates the `DAT_1123a728` singleton.
- `FUN_10ad6fb0` (line 1683750) — **LockGuardedCall_10af0580** — 1-arg pass-through.
- `FUN_10ad7090` (line 1683803) — **LockGuardedCall_10af0890** — lock-guarded 3-arg pass-through.
- `FUN_10ad7140` (line 1683846) — **LockGuardedCall_10af09d0** — lock-guarded pass-through, final function of this sub-range.

**Part 4 verdict:** Contradicts vegetation hypothesis. Genuine CRT internals, a locale/category-name resolver (possibly audio/sound-bank related), generic STL container internals, and a large lock-guarded diagnostics/event-reporting family. No position/scale/rotation triples, LOD distances, density/scatter math, or terrain-height queries anywhere.

---

### Part 5 — Generic Reflection/Property-Tree Runtime (lines 1683889–1687828)

Shared globals recognized: `DAT_1123a718` (lazily-constructed diagnostics/event-dispatch object), `DAT_1123a740` (lazily-constructed "reflection database"/property-type registry built by `FUN_10ad7d70`), `DAT_1123a730` (event/notification queue built by `FUN_10ad7e90`).

#### Diagnostic/telemetry event-dispatch wrappers (generic logging, continued from Part 4)

- `FUN_10ad71e0` (line 1683889) — **LogEvent_2Flags** — "fire diagnostic event" wrapper with 2 packed byte flags.
- `FUN_10ad7330` (line 1683955) — **LogEvent_FlagsPlusPair** — logs a (kind, valueA, valueB) tuple.
- `FUN_10ad74a0` (line 1684032) — **LogEvent_UintParam** — logs one dword param.
- `FUN_10ad8050` (line 1684866) — **LogEvent_WithQueueInit** — also lazily constructs the `DAT_1123a730` event-queue singleton.
- `FUN_10ad81c0` (line 1684943) — **LogPropertyPathEvent** — copies an 11-dword buffer (property-path/id array) into the log record; also builds and validates against `DAT_1123a740`.
- `FUN_10ada8d0` (line 1687261) — **LogSingleValueEvent** — logs one uint.
- `FUN_10adaa10` (line 1687333) — **LogAndCompareVariant** — combined notify+compare helper.
- `FUN_10adaed0` (line 1687596) — **NotifyPropertyChangedGuarded** — enable-checked wrapper around the "changed" notifier.
- `FUN_10adb3a0` (line 1687796) — **GetInterlockedField_0x1e8_Guarded** — enable-checked wrapper around an interlocked field read.

#### Property change notification pair (closest thing to "editor live-property" logic in the whole cluster)

- `FUN_10adaad0` (line 1687376) — **NotifyPropertyChanging** — fires log event with flag=0 (before-change).
- `FUN_10adabb0` (line 1687424) — **NotifyPropertyChanged** — identical, flag=1 (after-change); together a generic pre/post mutation hook (undo/redo or replication) for a reflected int-typed field.
- `FUN_10adac90` (line 1687472) — **SetPropertyWithNotify** — compares old vs new, fires Changing/assign/Changed sequence, lock-guarded.
- `FUN_10adad20` (line 1687508) — **SetPropertyWithNotify_Simple** — same pattern without the outer lock-guard.
- `FUN_10adb040` (line 1687629) — **SetOrResetProperty** — resets to default or delegates to `SetPropertyWithNotify_Simple`.
- `FUN_10adb310` (line 1687757) — **SetOrResetProperty_Guarded** — outer-lock-guarded dispatcher.
- `FUN_10adad40` (line 1687523) — **IsPropertyNonDefault** — type-tag dispatch query — "is this field dirty/differs from default"; plausibly backs property-grid bolding in an editor tool.

#### Container constructors / destructors (POD vectors of various element sizes, children of one big aggregate)

- `FUN_10ad7680` (line 1684154) — **VectorPod_Ctor_0x18** — 24-byte elements, vtable `DAT_110f1990`.
- `FUN_10ad76e0` (line 1684180) — **VectorPod_Dtor_0x18** — destructor counterpart.
- `FUN_10ad7700` (line 1684194) — **VectorPod_Ctor_0xc** — 12-byte elements (plausible Vec3/id-triple), vtable `DAT_110f199c`.
- `FUN_10ad7760` (line 1684220) — **VectorPod_Ctor_0x18_b** — 24-byte elements, vtable `DAT_110f1994`.
- `FUN_10ad77c0` (line 1684245) — **VectorPod_Dtor_0x18_b** — destructor for `DAT_110f1994`.
- `FUN_10ad77e0` (line 1684259) — **VectorPod_Ctor_0x48** — 72-byte elements, vtable `DAT_110f1998`.
- `FUN_10ad7840` (line 1684285) — **VectorPod_Dtor_0x48** — destructor for `DAT_110f1998`.
- `FUN_10ad7860` (line 1684299) — **VectorPod_Dtor_0xc** — destructor for `DAT_110f199c`.
- `FUN_10ad7880` (line 1684313) — **VectorPod_Ctor_0x8** — 8-byte elements (Vec2/int-pair), vtable `DAT_110f19a0`.
- `FUN_10ad78e0` (line 1684339) — **VectorPod_Dtor_0x8** — destructor for `DAT_110f19a0`.
- `FUN_10ad7900`/`FUN_10ad7920`/`FUN_10ad7940`/`FUN_10ad7960`/`FUN_10ad7980` (lines 1684353–1684409) — **ScalarDeletingDtor_Vec0x18/0x18b/0x48/0xc/0x8** — `operator delete`-style thunks wrapping the destructors above.
- `FUN_10ad7aa0`/`FUN_10ad7ad0`/`FUN_10ad7b00`/`FUN_10ad7b30`/`FUN_10ad7b60` (lines 1684494–1684554) — **SubobjectDtor_110f19a4/a8/ac/b0/b4** — delegate to the corresponding vector destructors as members of the big aggregate.
- `FUN_10ad7b90` (line 1684569) — **MapLike_Ctor_0x2000cap** — constructs a map/pool object with capacity 0x2000, vtable `DAT_110f19b8`.
- `FUN_10ad7bc0` (line 1684585) — **MapLike_Dtor** — destructor for the above.
- `FUN_10ad7c10` (line 1684602) — **ScalarDeletingDtor_MapLike** — wraps `FUN_10ad7bc0`.
- `FUN_10ad7d40` (line 1684695) — **SubobjectDtor_110f19bc** — delegates to `FUN_10ad7bc0`.

#### Red-black-tree / node-pool clear helpers

- `FUN_10ad75e0` (line 1684098) — **FixedArrayClear_Stride0x14** — frees array elements (20-byte stride).
- `FUN_10ad7630` (line 1684126) — **FixedArrayClear_Stride0x20** — same pattern, 32-byte stride.
- `FUN_10ad79d0` (line 1684439) — **RBTree_ClearAndFreeNodes** — classic intrusive red-black-tree teardown; `std::map`-alike `clear()`.
- `FUN_10ad7c30` (line 1684616) — **BigAggregate_ResetSubmaps** — "reset whole reflection-registry entry" style function.
- `FUN_10ad7cc0` (line 1684658) — **BigAggregate_ResetSubmaps_Variant** — near-duplicate with different field-clear order.
- `FUN_10ad8440` (line 1685086) — **RBTree_ClearAndFreeNodes_UsingResetA** — same tree-walk teardown, frees payload via `FUN_10ad7c30`.
- `FUN_10ad8500` (line 1685148) — **RBTree_ClearAndFreeNodes_UsingResetB** — frees payload via `FUN_10ad7cc0`.

#### Big aggregate "reflection database" constructors, singletons, and module shutdown

- `FUN_10ad7d70` (line 1684710) — **ReflectionRegistry_Ctor** — builds ~9 typed sub-containers with fixed capacities; constructor for the `DAT_1123a740` singleton — a central type/property registry, not vegetation-specific.
- `FUN_10ad7e90` (line 1684748) — **EventQueue_Ctor** — allocates fixed-size pools + tree sentinel; constructor for `DAT_1123a730` (change/notification queue feeding the logger).
- `FUN_10ad7f20` (line 1684786) — **ScalarDeletingDtor_EventQueue** — delete-path thunk.
- `FUN_10ad7f40` (line 1684800) — **GetOrCreateReflectionRegistry** — lazy-singleton accessor for `DAT_1123a740`.
- `FUN_10ad7f80` (line 1684820) — **GetOrCreateEventQueue** — lazy-singleton accessor for `DAT_1123a730`.
- `FUN_10ad7fc0` (line 1684840) — **ReflectionRegistry_TeardownMembers** — destructs the 8 typed sub-containers in reverse construction order.
- `FUN_10ad85c0` (line 1685210) — **ShutdownReflectionSubsystem** — large module-exit routine tearing down ~15 global singletons. **Proves this whole address range is one cohesive subsystem with its own lifecycle**, independent of the "Vegetation" logger category registered far earlier in the cluster (Part 1).

#### Type-tagged clone/serialize dispatch (COM-style HRESULT returns: 0x80004005=E_FAIL, 0x8007000e=E_OUTOFMEMORY)

- `FUN_10ad88b0` (line 1685358) — **CloneTypedResource_ByKind** — switches on a type id (1-9) to fixed byte sizes; generic "duplicate a typed descriptor" helper.
- `FUN_10ad89c0` (line 1685427) — **CloneFixedSizeResource_0x44** — same pattern for a single fixed 0x44-byte type.
- `FUN_10ad8a20` (line 1685450) — **InitBufferField_OwnedOrShared** — sets a 4-field record to reference external memory or allocate-and-copy.
- `FUN_10ad8c00` (line 1685564) — **CloneType1_Struct0x44** — allocates, memcpy at fixed offset.
- `FUN_10ad8c90` (line 1685590) — **CloneType2_Struct0x84** — allocates, splits memcpy at two offsets.
- `FUN_10ad8d40` (line 1685616) — **CloneType_RawBlockRequest** — allocates with fixed request kind, straight memcpy.
- `FUN_10ad8f70` (line 1685790) — **CloneType_HeaderPlusBody** — splits an 8-byte header from remaining body.
- `FUN_10ad8ff0` (line 1685821) — **CloneType_VariableHeader** — copies a 244-byte scratch header, clones remainder.
- `FUN_10ad9120` (line 1685877) — **DispatchCloneByTag_2Way** — routes to `CloneFixedSizeResource_0x44` or `CloneTypedResource_ByKind` by type-tag mask.
- `FUN_10ad9990` (line 1686427) — **DispatchCloneByTag_5Way** — fuller dispatcher across 5 type-tag values.
- `FUN_10ad99e0` (line 1686463) — **CloneWithSizeCheck** — validates minimum size, forwards to `DispatchCloneByTag_5Way`.
- `FUN_10ad8bc0` (line 1685547) — **AllocIfKind2** — shared helper; allocates only if kind==2.

#### Critical-section-guarded "variant" accessors (typed union / property-value object)

- `FUN_10ad8aa0` (line 1685480) — **VariantDtor** — frees owned buffer if not external, downgrades vtable to base type.
- `FUN_10ad8af0` (line 1685499) — **FreeRaw** — trivial free wrapper.
- `FUN_10ad8b40` (line 1685510) — **AcquireThenRelease** — scoped-lock RAII pair.
- `FUN_10ad8b80` (line 1685522) — **CompareResultNonNegative** — bool wrapper over a comparator.
- `FUN_10ad8bb0` (line 1685536) — **SetVariantVtable** — sets vtable pointer only.
- `FUN_10ad8dc0` (line 1685660) — **GetFirstField** — trivial getter.
- `FUN_10ad8dd0` (line 1685670) — **CompareCurrentValue** — compares via `CompareResultNonNegative`.
- `FUN_10ad8df0` (line 1685684) — **GetFlagLocked** — lock-guarded bool getter.
- `FUN_10ad8e10` / `FUN_10ad8f20` (dup) (lines 1685699 / 1685760) — **GetTypeTagLocked** / **GetTypeTagLocked_Dup** — lock-guarded high-nibble type-tag extractor, byte-identical duplicate function.
- `FUN_10ad8e40` (line 1685714) — **ReleaseLocked** — lock-guarded void release call.
- `FUN_10ad8e60` (line 1685727) — **GetValueNestedLocked** — double lock-guarded value fetch.
- `FUN_10ad8e90` (line 1685745) — **IsNotFlagLocked** — lock-guarded inverted bool.
- `FUN_10ad8f40` (line 1685775) — **InitVariantDefault** — sets vtable, type tag to `0x80000000` sentinel ("unset"), zeroes fields.
- `FUN_10ad9170` (line 1685898) — **GetChildNodeLocked** — lock-guarded getter.
- `FUN_10ad9190` (line 1685913) — **GetCountLocked** — lock-guarded getter.
- `FUN_10ad91b0` (line 1685930) — **ReleaseChildLocked** — lock-guarded void release.
- `FUN_10ad91d0` (line 1685941) — **GetNextLocked** — lock-guarded getter.
- `FUN_10ad91f0` (line 1685956) — **AssignVariant** — nested-lock copy-assign sequence.
- `FUN_10ad9260` (line 1685983) — **ReleaseVariantNested** — double lock-guarded release.
- `FUN_10ad9280` (line 1685998) — **AssignVariantFromPtr** — same as AssignVariant, source is `*param2`.
- `FUN_10ad92d0` (line 1686020) — **HasValueLocked** — lock-guarded check.
- `FUN_10ad9330` (line 1686041) — **NoOpLocked** — pure lock/unlock returning 0 (placeholder/base-case handler).
- `FUN_10ad9350` (line 1686053) — **CopyTagField** — conditional lock-guarded field copy.
- `FUN_10ad93a0` (line 1686074) — **CopyConstructVariant** — copies vtable/type dword and fields.
- `FUN_10ad9c80` (line 1686604) — **CopyConstructTagged** — variant copy-construct that also copies an extra tag dword.
- `FUN_10ad9920` (line 1686400) — **SetGlobalContextAndCompare** — sets global comparison context then diffs.
- `FUN_10ad9b50` (line 1686536) — **BuildVariantFromIndex** — looks up by index, assigns/compares.
- `FUN_10ada050` (line 1686803) — **BuildVariantFromIndex_Default** — trivial wrapper (index, default=1).
- `FUN_10ad9820` (line 1686332) — **RebuildVariantFromSource** — "recompute value from source" routine.
- `FUN_10ad98d0` (line 1686377) — **InitVariantFromValue** — simpler variant init.
- `FUN_10ad9d00` (line 1686641) — **SyncVariantState** — "ensure this node's children exist/are in sync" routine.
- `FUN_10ad9fb0` (line 1686767) — **SyncAllOfType2** — iterates a collection, calls `SyncVariantState` for type-2 entries.
- `FUN_10ad96b0` (line 1686262) — **NavigateVariantChild** — branches on node type to pick a child-slot offset and recurse.
- `FUN_10ad9ce0` (line 1686625) — **HasValueOrDefault** — shortcut/forward to `HasValueLocked`.
- `FUN_10ad9400` (line 1686095) — **ReleaseAllChildrenByType** — switch on type tag, loops releasing every child slot.
- `FUN_10ad95b0` (line 1686201) — **ReleaseChildrenByTypeVariant2** — sibling switch with different release-count pattern.

#### Recursive reflection-tree traversal (property-tree compare / has-value)

- `FUN_10ada390` (line 1686990) — **ReflectionTree_ValidateRecursive** — recursive "is this whole subtree meaningfully populated/valid" check across an arbitrary reflected type tree — matches the `VegetationZoneData`-style reflection classes mentioned in the task context but generic to *any* reflected type, not vegetation-specific.
- `FUN_10ada6e0` (line 1687149) — **ReflectionTree_HasValueRecursive** — related recursive tree-walk that short-circuits to 0 as soon as any node in the chain lacks a value.

#### Hash map primitives (open-chained hashtable keyed by `*key % capacity`)

- `FUN_10ad9a90` (line 1686481) — **HashMap_IncRefOrInsert** — increments refcount on match.
- `FUN_10ad9af0` (line 1686509) — **HashMap_Contains** — returns bool found/not-found.
- `FUN_10ad9c00` (line 1686572) — **HashMap_FindAndInvoke** — visitor-pattern lookup.
- `FUN_10ada090` (line 1686814) — **HashMap_InsertOrGet** — lazily allocates bucket array, inserts or returns existing.
- `FUN_10ada190` (line 1686861) — **HashMap_Erase** — removes a bucket-chain node.
- `FUN_10ada240` (line 1686904) — **HashMap_SetOrInsert** — find-or-insert then locked-assign value.
- `FUN_10ada320` (line 1686954) — **HashMap_DecRefOrErase** — decrements refcount; erases at zero.

#### Misc small helpers

- `FUN_10ad79a0` (line 1684423) — **TeardownStep_ConditionalReflectionRelease** — conditional teardown step with a "static/no-op instance" sentinel (`-4`).
- `FUN_10ad8380` (line 1685040) — **DispatchIfRegistered** — checks a registration flag, lazily builds `DAT_1123a740`, forwards call.
- `FUN_10ad8d90` (line 1685636) — **AddRef** — `*(param1+4) += 1`.
- `FUN_10ad8da0` (line 1685647) — **SetFields3** — sets three adjacent dword fields directly.
- `FUN_10adb0d0` (line 1687669) — **InterlockedReadField_0x1e8** — lazily builds `DAT_1123a740`, atomic-style read of field.
- `FUN_10adb120` (line 1687697) — **DispatchFieldOperationByTag** — larger router dispatching by type-tag mask.

**Part 5 verdict:** Contradicts vegetation hypothesis in isolation. This is the cluster's shared reflection/property-notification infrastructure (typed containers, a variant value type, hashtables, recursive validate/has-value walks, PropertyChanging/Changed hooks) — plausibly the generic machinery a reflected class like `VegetationZoneData` would sit on top of, but reused by many unrelated reflected types.

---

### Part 6 — Asset Streaming, Expression-Tree Evaluator, CString, Hardware Detection (lines 1687829–1691789)

#### Asset-streaming / .bao loader glue (generic sector/asset loading, not vegetation-specific)

- `FUN_10adb410` (line 1687829) — **BuildBaoAssetFilename** — builds `"%08x.bao"`/`"%08x.sbao"` filename from an asset id. `.bao`/`.sbao` = Dunia's generic streamed "Binary Asset Object" container, used for many sector/asset kinds — not vegetation-specific by itself.
- `FUN_10adb510` (line 1687877) — **LoadBaoAssetIntoBuffer** — opens/reads/closes a file handle into an allocated buffer.
- `FUN_10adb620` (line 1687917) — **DispatchLoadBaoOrInline** — branches between file-backed load and already-resident data.
- `FUN_10adb650` (line 1687935) — **LoadAndClearBaoSlot** — dispatches then zeroes a cache-slot struct (cache-eviction-like pattern).
- `FUN_10adb6a0` (line 1687954) — **GuardedBaoAssetOp_A** — exception/lock-guarded wrapper allocating a "streaming context".
- `FUN_10adb860` (line 1688044) — **GuardedBaoAssetOp_B** — near-duplicate with different param arrangement.
- `FUN_10adb9c0` (line 1688119) — **GuardedLoadBaoAssetById** — guarded wrapper around id → resource lookup.
- `FUN_10adba20` (line 1688140) — **DispatchGuardedLoadOrThunk** — trivial branch to guarded load vs generic thunk.

#### Generic recursive node/expression-tree evaluator (property/config resolver, node-type switch 1–0xc)

- `FUN_10adba50` (line 1688155) — **EvaluateNodeTree_BoolAnd** — recursively ANDs child-node evaluation results across a node-type switch. Generic boolean condition-tree walker, not vegetation-tagged.
- `FUN_10adbd20` (line 1688314) — **EvaluateNodeTree_BoolAndVariant** — sibling evaluator with a different traversal stride.
- `FUN_10adbee0` (line 1688426) — **EvaluateNodeTree_TopLevel** — top-level entry, dispatches by bit-flag tag to bool-tree or int-array evaluator.
- `FUN_10adc070` (line 1688499) — **DispatchNodeEval_A** — trivial branch between two evaluator entry points.
- `FUN_10adc0a0` (line 1688514) — **ConstructNodeHandle_A** — ctor pattern for a node/handle wrapper.
- `FUN_10adc0c0` (line 1688526) — **ConstructNodeHandle_B** — same pattern feeding into `GuardedBaoAssetOp_A`.
- `FUN_10adc0f0` (line 1688540) — **ReleaseNodeHandleBuffer** — dtor-like: frees and zeroes the handle struct.
- `FUN_10adc130` (line 1688557) — **EvaluateNodeTree_IntArray** — large evaluator returning an int array over node types 0–0xc. Confirms a generic reflected-value resolver (likely backing config/trigger-condition evaluation), not vegetation math.
- `FUN_10adc650` (line 1688792) — **EvaluateNodeTree_Float** — guarded wrapper returning a float10 scalar from the same node-tag switch.
- `FUN_10adc7e0` (line 1688885) — **GuardedEvaluateNodeTree_IntArray** — lock-guarded wrapper with early-out for an invalid handle.
- `FUN_10adc8c0` (line 1688936) — **MaxUInt** — trivial `max(a,b)` helper.
- `FUN_10adc950` (line 1688949) — **InitFixedBlockPool** — fixed-size block/chunk allocator initializer; pre-warms the pool. Generic memory-pool initializer, no vegetation semantics.
- `FUN_10adcaa0` (line 1689020) — **ConstructReflectedObject** — sets vtable ptr, conditional placement-delete pattern.

#### Exception/critical-section guard wrappers, refcounted "reflection registry" nodes

- `FUN_10adcae0` (line 1689037) — **EnterReflectionRegistryGuard** — lazy-inits a registry object, enters a lock.
- `FUN_10adcb80` (line 1689074) — **ExitReflectionRegistryGuard** — counterpart release/leave.
- `FUN_10adcd10` (line 1689100) — **FormatAndRegisterNamedEntry** — builds `"%s%x%s"` formatted string; debug/registry name-tagging helper (e.g. object naming for a leak tracker), not vegetation.
- `FUN_10add330` (line 1689138) — **RegisterCallbackTable** — one-time registers two function pointers into a global.
- `FUN_10add3d0` (line 1689169) — **GuardedInvokeOrDefaultCallback** — guarded branch between two call targets.
- `FUN_10add470` (line 1689203) — **GuardedLookupAndOp** — guarded handle resolve + operation.
- `FUN_10add520` (line 1689239) — **GuardedBroadcastToList_A** — observer/broadcast pattern over a generic registry, not vegetation instances.
- `FUN_10add670` (line 1689291) — **GuardedBroadcastToList_B** — same shape, different per-node callback.
- `FUN_10add7c0` (line 1689343) — **GuardedBroadcastToOne_A** — targets a single resolved handle.
- `FUN_10add930` (line 1689397) — **GuardedBroadcastToOne_B** — same but different per-node callback.
- `FUN_10addb10` (line 1689451) — **CreateRegistryEntry** — allocates/builds/registers or rolls back on failure. Generic object-registry "create" op.
- `FUN_10addca0` (line 1689506) — **CreateVTableWrapperObject** — allocates an object, selects between two static vtable layouts. Generic interface-adapter constructor.
- `FUN_10adde20` (line 1689573) — **DestroyVTableWrapperObject** — dtor: frees fields, resets vtable.
- `FUN_10adde70` (line 1689592) — **DestroyVTableWrapperObject_DeleteThunk** — scalar-deleting-destructor thunk.
- `FUN_10added0` (line 1689606) — **GuardedRemoveRegistryEntry** — resolves handle, unlinks, frees it.
- `FUN_10addf90` (line 1689645) — **GuardedTeardownRegistry** — drains a pending list, walks and frees entries. Registry-shutdown routine.
- `FUN_10ade070` (line 1689692) — **GuardedRemoveOrRescheduleEntry** — either removes or reschedules an entry based on a sign test.
- `FUN_10ade140` (line 1689734) — **GuardedSweepExpiredEntries** — "sweep and cull expired timers/handles" loop — generic, no distance/LOD semantics.
- `FUN_10ade2c0` (line 1689791) — **AccumulateTimerCounters** — generic multi-channel timer/counter accumulator (could back cooldowns, fade timers, etc.).

#### Generic growable-array / hashmap (0x48-byte element stride) utility

- `FUN_10ade370` (line 1689830) — **FindMapEntryByKey** — bidirectional linear scan for a matching int key, with single-entry lookup cache.
- `FUN_10ade3f0` (line 1689870) — **ByteSwapNodeFields** — endian-swap/normalize step for node-tree structures — confirms those nodes are a serialized/streamed format, still generic.
- `FUN_10ade5b0` (line 1689959) — **GrowRecordArray** — reallocates the record array with a growth ratio (`std::vector`-style grow).
- `FUN_10ade6a0` (line 1690016) — **PushBackRecord** — appends one record, grows when capacity exceeded.
- `FUN_10ade710` (line 1690047) — **MapInsertOrUpdate** — classic map `operator[]`/insert.

#### Lazy-singleton accessors / lock thunks / misc small wrappers

- `FUN_10ade790` (line 1690087) — **GuardedInitStreamingSubsystem** — lazily allocates a streaming buffer and subsystem object.
- `FUN_10ade940` (line 1690179) — **GuardedQueryStreamingHandle** — guarded query wrapper.
- `FUN_10adea90` (line 1690251) — **GetStreamingModeField** — lazy-inits a 500-byte global, atomically reads mode/state enum field.
- `FUN_10adeae0` (line 1690279) — **GetStreamingFlagField** — same lazy-init, reads a different field.
- `FUN_10adeb30` (line 1690311) — **ResetStreamingSubsystem** — tears down/frees the streaming buffer.
- `FUN_10adecf0` (line 1690340) — **DispatchStreamingModeUpdate** — branches on streaming mode to call one of two update functions.
- `FUN_10aded20`/`FUN_10aded40` (lines 1690367/1690389) — **EnterGlobalLock** / **EnterGlobalLock_Dup** — thin wrappers to critical-section enter.
- `FUN_10aded30`/`FUN_10aded50` (lines 1690378/1690400) — **LeaveGlobalLock** / **LeaveGlobalLock_Dup** — thin wrappers to critical-section leave.
- `FUN_10aded60` (line 1690411) — **FreeAndClearPtr** — `if(*p) free(*p); *p=0;` helper.
- `FUN_10aded90` (line 1690425) — **GetStringOrEmptyDefault** — returns a string or shared empty-string constant.

#### CString-style class implementation (Assign/Append/Compare/Convert) — generic, not vegetation

- `FUN_10adeda0` (line 1690441) — **StringAssignN** — core `CString::Assign`-equivalent.
- `FUN_10adee50` (line 1690491) — **WideStringLessThan** — wchar lexicographic compare.
- `FUN_10adeeb0` (line 1690525) — **StringCompareWithNullChecks** — null-safe case-insensitive compare wrapper.
- `FUN_10adeee0` (line 1690544) — **StringFromCharConvert** — codepage/wide conversion helper.
- `FUN_10adef70` (line 1690574) — **StringCopyConstruct** — copy-ctor.
- `FUN_10adefc0` (line 1690599) — **WideStringCompareOrdinal** — tri-state wide-char compare.
- `FUN_10adf010` (line 1690636) — **StringAssignOperator** — self-assignment-safe `operator=`.
- `FUN_10adf050` (line 1690663) — **StringAppendN** — grows buffer and appends bytes.
- `FUN_10adf100` (line 1690709) — **StringAssignCStr** — null-terminated C-string assign wrapper.
- `FUN_10adf140` (line 1690732) — **FormatBaoIdIntoString** — thin wrapper used by `BuildBaoAssetFilename`'s slow path.
- `FUN_10adf160` (line 1690743) — **StringConstructFromCStr** — ctor.
- `FUN_10adf190` (line 1690756) — **StringAppendChar** — appends a single character.
- `FUN_10adf1c0` (line 1690770) — **StrCaseInsensitiveCompare** — ASCII-fold `strcmp`.
- `FUN_10adf210` (line 1690796) — **CopyAndNullTerminate** — memcpy plus conditional null-terminate.
- `FUN_10adf260` (line 1690820) — **AppendRawIfCapacity** — conditional append when capacity allows.
- `FUN_10adf2c0` (line 1690848) — **ParseSignedIntFromString** — hand-rolled `atoi`.
- `FUN_10adf320` (line 1690879) — **VTableDoubleDispatch** — generic interface "get-then-release" pattern.
- `FUN_10adf390` (line 1690896) — **ZeroAlignedBlock32** — hand-unrolled memset-zero of a 32-byte block.
- `FUN_10adf400` (line 1690938) — **InvokeDebugHookIfEnabled** — calls a callback only when a global debug/profiling mode flag is set.
- `FUN_10adf420` (line 1690951) — **LeaveGlobalLock_RawThunk** — thin call to raw leave-critical-section import.

#### CPU/GPU hardware-detection (definitively unrelated to vegetation)

- `FUN_10adf430` (line 1690962) — **DetectCpuVendor** — classic CPUID-vendor-string match against `"GenuineIntel"`, `"AuthenticAMD"`, `"CyrixInstead"`, etc. Pure hardware-capability detection.
- `FUN_10adf650` (line 1691172) — **DecodeCpuidCacheDescriptors** — decodes Intel CPUID leaf-2 cache/TLB descriptor byte table.
- `FUN_10adfbd0` (line 1691488) — **CheckCpuExtendedLeafSupport** — checks whether CPUID extended leaf `0x80000000` reporting is trustworthy.
- `FUN_10adfcf0` (line 1691536) — **GetCpuClflushLineSize** — reads CPUID leaf 1 EBX clflush-size byte.
- `FUN_10adfd50` (line 1691560) — **BuildUncPrefixAndGetComputerName** — machine-name/UNC-path helper, likely for telemetry/log tagging.
- `FUN_10adfd80`/`FUN_10adfd90` (lines 1691576/1691587) — **RawThunk_110000b8** / **RawThunk_110000bc** — 1-line import passthroughs.
- `FUN_10adfda0` (line 1691598) — **QueryDeviceIoControlCapability** — Open/DeviceIoControl/Close sequence — driver/handle capability probe.
- `FUN_10adfe00` (line 1691623) — **RawThunk_11000868_WithField** — passthrough using a struct field as argument.
- `FUN_10adfe10` (line 1691634) — **MapPciDeviceIdToGpuFamilyEnum** — maps hard-coded Intel-integrated-graphics PCI device IDs (`0x276d, 0x2742, 0x2af9-0x2afc, 0x2734, 0x271e, 0x2714`) to a GPU-family enum. Classic "known-bad/known-limited IGP" driver workaround table — strong confirmation this region is hardware-capability detection.
- `FUN_10adfec0` (line 1691673) — **RefreshGpuDeviceIdIfDirty** — re-queries the device id when a dirty flag is set.
- `FUN_10adff60` (line 1691712) — **ResetGpuCapabilityFlags** — clears capability-cache fields.
- `FUN_10adff70` (line 1691724) — **InvokeVTableTripleIndirectCall** — resolves a deeply chained vtable pointer and calls it.
- `FUN_10adff90` (line 1691737) — **AllocOrDefaultBlock** — generic allocator shim (likely DirectX/driver buffer alloc given surrounding GPU-detection context).
- `FUN_10adffc0` (line 1691756) — **RawThunk_1100011c** — 1-arg passthrough call.
- `FUN_10adffd0` (line 1691767) — **AllocOrDefaultBlock_NoSize** — near-duplicate of `AllocOrDefaultBlock` without the size branch.
- `FUN_10adfff0` (line 1691779) — **LeaveGlobalLock_Impl** — passthrough to the actual "leave critical section/release" import that all the guard wrappers in this range ultimately call. True tail of the sweep range.

**Part 6 verdict:** Contradicts vegetation hypothesis. Generic asset-streaming (`.bao`/`.sbao`) loader, a recursive node/property-tree evaluator, a full CString class, a growable hashmap, exception-safe critical-section guard wrappers around a generic object registry, and unambiguous CPU/GPU hardware-capability detection code (CPU-vendor strings, Intel-IGP PCI device IDs). No vegetation terminology, bbox/zone/density/LOD-distance fields, or scatter/placement math anywhere in this span.

---

### Final Summary

- **531 functions** in the `FUN_10ac0000`–`FUN_10adffff` range; **~540 entries labeled** below (near-exhaustive coverage via 6 parallel sweeps with no gaps between sub-ranges).
- **The vegetation-placement/foliage-scattering hypothesis for this cluster is false.** The cluster is a mixed bag of: (1) an AI "Consideration"/criterion scoring framework where "Vegetation" is one of seven sibling named criteria used for stealth/concealment scoring; (2) a 2D local-avoidance/steering subsystem for NPC movement; (3) MSVC CRT/ATL runtime glue; (4) a locale/category-name resolver possibly tied to audio; (5) a generic lock-guarded diagnostics/event-reporting family and a generic reflection/property-tree runtime; (6) generic asset-streaming glue, a node/expression-tree evaluator, a CString class, and CPU/GPU hardware detection.
- **The one genuinely vegetation-relevant code found**: `FUN_10ac5fb0` (**ComputeVegetationCoverageScore**) and its support chain `FUN_10ac5420`/`FUN_10ac56f0`/`FUN_10ac57a0`/`FUN_10ac58e0`/`FUN_10ac51a0`/`FUN_10ac53b0`/`FUN_10ac5090` (lines 1671152–1671787) — these compute how much nearby foliage/canopy conceals a pawn for stealth-detection purposes, referencing "vegetation collision objects" (RTTI slot `DAT_11234f50`) and a "registered zone list" (`DAT_11224e68`). This is a **query against** vegetation, not a placement/scattering system — but the RTTI type and zone-list globals it touches could be useful breadcrumbs for locating the real placement/zone-loading code elsewhere in the DLL.
- **Recommendation**: do not treat `FUN_10ac0000`–`FUN_10adffff` as the vegetation subsystem going forward. If a real vegetation placement/instancing system exists, search elsewhere — possibly via the call graph of `RegisterVegetationZoneProperties`/`FUN_102f3050` (the `VegetationZoneData` reflection registration mentioned in the task brief) or by tracing references to `DAT_11224e68`/`DAT_11234f50`.

---


## Class RTTI Registration Getters (mechanical, from avatar_class_hierarchy.tsv)

Every class's self-registration getter (see header note #1). Format: class name embeds the
real engine class name; parent class shown in the justification. ~1,532 entries.

- `FUN_108d9820` (line 1419012) — **RTTI_GetClassInfo_Action** — class self-registration getter (calls FUN_100016b0("Action", parent-getter)); registers `Action` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_108d7a30` (line 1417087) — **RTTI_GetClassInfo_ActionData** — class self-registration getter (calls FUN_100016b0("ActionData", parent-getter)); registers `ActionData` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_104c9990` (line 830444) — **RTTI_GetClassInfo_AvatarAMPSuit** — class self-registration getter (calls FUN_100016b0("AvatarAMPSuit", parent-getter)); registers `AvatarAMPSuit` as a subclass of `CVehicleBase` in the engine RTTI/class-factory system.
- `FUN_108ef360` (line 1433986) — **RTTI_GetClassInfo_AvatarActionOvertimeComponent** — class self-registration getter (calls FUN_100016b0("AvatarActionOvertimeComponent", parent-getter)); registers `AvatarActionOvertimeComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104cc680` (line 832331) — **RTTI_GetClassInfo_AvatarCharacterSheet** — class self-registration getter (calls FUN_100016b0("AvatarCharacterSheet", parent-getter)); registers `AvatarCharacterSheet` as a subclass of `CCharacterSheet` in the engine RTTI/class-factory system.
- `FUN_104cca10` (line 832507) — **RTTI_GetClassInfo_AvatarCharacterSheet_AMPSuit** — class self-registration getter (calls FUN_100016b0("AvatarCharacterSheet_AMPSuit", parent-getter)); registers `AvatarCharacterSheet_AMPSuit` as a subclass of `AvatarCharacterSheet_Vehicle` in the engine RTTI/class-factory system.
- `FUN_104cc740` (line 832395) — **RTTI_GetClassInfo_AvatarCharacterSheet_Animal** — class self-registration getter (calls FUN_100016b0("AvatarCharacterSheet_Animal", parent-getter)); registers `AvatarCharacterSheet_Animal` as a subclass of `AvatarCharacterSheet_NPC` in the engine RTTI/class-factory system.
- `FUN_104cc800` (line 832459) — **RTTI_GetClassInfo_AvatarCharacterSheet_AnimalMount** — class self-registration getter (calls FUN_100016b0("AvatarCharacterSheet_AnimalMount", parent-getter)); registers `AvatarCharacterSheet_AnimalMount` as a subclass of `AvatarCharacterSheet_Vehicle` in the engine RTTI/class-factory system.
- `FUN_104cc770` (line 832411) — **RTTI_GetClassInfo_AvatarCharacterSheet_Destructable** — class self-registration getter (calls FUN_100016b0("AvatarCharacterSheet_Destructable", parent-getter)); registers `AvatarCharacterSheet_Destructable` as a subclass of `AvatarCharacterSheet` in the engine RTTI/class-factory system.
- `FUN_104cc830` (line 832475) — **RTTI_GetClassInfo_AvatarCharacterSheet_FlyingAnimalMount** — class self-registration getter (calls FUN_100016b0("AvatarCharacterSheet_FlyingAnimalMount", parent-getter)); registers `AvatarCharacterSheet_FlyingAnimalMount` as a subclass of `AvatarCharacterSheet_Vehicle` in the engine RTTI/class-factory system.
- `FUN_104cc710` (line 832379) — **RTTI_GetClassInfo_AvatarCharacterSheet_Humanoid** — class self-registration getter (calls FUN_100016b0("AvatarCharacterSheet_Humanoid", parent-getter)); registers `AvatarCharacterSheet_Humanoid` as a subclass of `AvatarCharacterSheet_NPC` in the engine RTTI/class-factory system.
- `FUN_104cc6e0` (line 832363) — **RTTI_GetClassInfo_AvatarCharacterSheet_NPC** — class self-registration getter (calls FUN_100016b0("AvatarCharacterSheet_NPC", parent-getter)); registers `AvatarCharacterSheet_NPC` as a subclass of `AvatarCharacterSheet` in the engine RTTI/class-factory system.
- `FUN_104cc860` (line 832491) — **RTTI_GetClassInfo_AvatarCharacterSheet_Plant** — class self-registration getter (calls FUN_100016b0("AvatarCharacterSheet_Plant", parent-getter)); registers `AvatarCharacterSheet_Plant` as a subclass of `AvatarCharacterSheet_NPC` in the engine RTTI/class-factory system.
- `FUN_104cc6b0` (line 832347) — **RTTI_GetClassInfo_AvatarCharacterSheet_Player** — class self-registration getter (calls FUN_100016b0("AvatarCharacterSheet_Player", parent-getter)); registers `AvatarCharacterSheet_Player` as a subclass of `AvatarCharacterSheet` in the engine RTTI/class-factory system.
- `FUN_104cc7a0` (line 832427) — **RTTI_GetClassInfo_AvatarCharacterSheet_Repairable** — class self-registration getter (calls FUN_100016b0("AvatarCharacterSheet_Repairable", parent-getter)); registers `AvatarCharacterSheet_Repairable` as a subclass of `AvatarCharacterSheet` in the engine RTTI/class-factory system.
- `FUN_104cc7d0` (line 832443) — **RTTI_GetClassInfo_AvatarCharacterSheet_Vehicle** — class self-registration getter (calls FUN_100016b0("AvatarCharacterSheet_Vehicle", parent-getter)); registers `AvatarCharacterSheet_Vehicle` as a subclass of `AvatarCharacterSheet` in the engine RTTI/class-factory system.
- `FUN_1050e9d0` (line 873239) — **RTTI_GetClassInfo_AvatarDepleteVitalityEvent** — class self-registration getter (calls FUN_100016b0("AvatarDepleteVitalityEvent", parent-getter)); registers `AvatarDepleteVitalityEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_104ca110` (line 830764) — **RTTI_GetClassInfo_AvatarEntityListComponent** — class self-registration getter (calls FUN_100016b0("AvatarEntityListComponent", parent-getter)); registers `AvatarEntityListComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104ca0e0` (line 830748) — **RTTI_GetClassInfo_AvatarFilterComponent** — class self-registration getter (calls FUN_100016b0("AvatarFilterComponent", parent-getter)); registers `AvatarFilterComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104ca260` (line 830828) — **RTTI_GetClassInfo_AvatarGatherComponent** — class self-registration getter (calls FUN_100016b0("AvatarGatherComponent", parent-getter)); registers `AvatarGatherComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_108ef300` (line 1433970) — **RTTI_GetClassInfo_AvatarInteractiveComponent** — class self-registration getter (calls FUN_100016b0("AvatarInteractiveComponent", parent-getter)); registers `AvatarInteractiveComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104ca1d0` (line 830812) — **RTTI_GetClassInfo_AvatarLootComponent** — class self-registration getter (calls FUN_100016b0("AvatarLootComponent", parent-getter)); registers `AvatarLootComponent` as a subclass of `AvatarPickupComponent` in the engine RTTI/class-factory system.
- `FUN_101a7230` (line 293181) — **RTTI_GetClassInfo_AvatarMutliVarsManager** — class self-registration getter (calls FUN_100016b0("AvatarMutliVarsManager", parent-getter)); registers `AvatarMutliVarsManager` as a subclass of `CSingletonEntity` in the engine RTTI/class-factory system.
- `FUN_108ef420` (line 1434002) — **RTTI_GetClassInfo_AvatarPODComponent** — class self-registration getter (calls FUN_100016b0("AvatarPODComponent", parent-getter)); registers `AvatarPODComponent` as a subclass of `CGameObject` in the engine RTTI/class-factory system.
- `FUN_104c9650` (line 830346) — **RTTI_GetClassInfo_AvatarPawn** — class self-registration getter (calls FUN_100016b0("AvatarPawn", parent-getter)); registers `AvatarPawn` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104c9710` (line 830394) — **RTTI_GetClassInfo_AvatarPawn_Humanoid** — class self-registration getter (calls FUN_100016b0("AvatarPawn_Humanoid", parent-getter)); registers `AvatarPawn_Humanoid` as a subclass of `AvatarPawn` in the engine RTTI/class-factory system.
- `FUN_104c96e0` (line 830378) — **RTTI_GetClassInfo_AvatarPawn_Player** — class self-registration getter (calls FUN_100016b0("AvatarPawn_Player", parent-getter)); registers `AvatarPawn_Player` as a subclass of `AvatarPawn` in the engine RTTI/class-factory system.
- `FUN_104ca1a0` (line 830796) — **RTTI_GetClassInfo_AvatarPickupComponent** — class self-registration getter (calls FUN_100016b0("AvatarPickupComponent", parent-getter)); registers `AvatarPickupComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104ca080` (line 830716) — **RTTI_GetClassInfo_AvatarPlayerCheckpointComponent** — class self-registration getter (calls FUN_100016b0("AvatarPlayerCheckpointComponent", parent-getter)); registers `AvatarPlayerCheckpointComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1051c330` (line 881153) — **RTTI_GetClassInfo_AvatarRefillAmmoEvent** — class self-registration getter (calls FUN_100016b0("AvatarRefillAmmoEvent", parent-getter)); registers `AvatarRefillAmmoEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1050e960` (line 873202) — **RTTI_GetClassInfo_AvatarRefillHealthManaEvent** — class self-registration getter (calls FUN_100016b0("AvatarRefillHealthManaEvent", parent-getter)); registers `AvatarRefillHealthManaEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_104ca170` (line 830780) — **RTTI_GetClassInfo_AvatarRelayComponent** — class self-registration getter (calls FUN_100016b0("AvatarRelayComponent", parent-getter)); registers `AvatarRelayComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104ca290` (line 830844) — **RTTI_GetClassInfo_AvatarScannableComponent** — class self-registration getter (calls FUN_100016b0("AvatarScannableComponent", parent-getter)); registers `AvatarScannableComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104f02a0` (line 854540) — **RTTI_GetClassInfo_AvatarShowTutorialEvent** — class self-registration getter (calls FUN_100016b0("AvatarShowTutorialEvent", parent-getter)); registers `AvatarShowTutorialEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_104ca0b0` (line 830732) — **RTTI_GetClassInfo_AvatarTriggerableComponent** — class self-registration getter (calls FUN_100016b0("AvatarTriggerableComponent", parent-getter)); registers `AvatarTriggerableComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104ca2f0` (line 830860) — **RTTI_GetClassInfo_AvatarVisibilityComponent** — class self-registration getter (calls FUN_100016b0("AvatarVisibilityComponent", parent-getter)); registers `AvatarVisibilityComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104ca560` (line 830956) — **RTTI_GetClassInfo_BTZWeapon** — class self-registration getter (calls FUN_100016b0("BTZWeapon", parent-getter)); registers `BTZWeapon` as a subclass of `CFCXWeapon` in the engine RTTI/class-factory system.
- `FUN_10984340` (line 1507297) — **RTTI_GetClassInfo_BrainBtzAnimal** — class self-registration getter (calls FUN_100016b0("BrainBtzAnimal", parent-getter)); registers `BrainBtzAnimal` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_10984540` (line 1507425) — **RTTI_GetClassInfo_BrainDirehorse** — class self-registration getter (calls FUN_100016b0("BrainDirehorse", parent-getter)); registers `BrainDirehorse` as a subclass of `BrainBtzAnimal` in the engine RTTI/class-factory system.
- `FUN_10984420` (line 1507329) — **RTTI_GetClassInfo_BrainHexapede** — class self-registration getter (calls FUN_100016b0("BrainHexapede", parent-getter)); registers `BrainHexapede` as a subclass of `BrainBtzAnimal` in the engine RTTI/class-factory system.
- `FUN_10984480` (line 1507361) — **RTTI_GetClassInfo_BrainStingbat** — class self-registration getter (calls FUN_100016b0("BrainStingbat", parent-getter)); registers `BrainStingbat` as a subclass of `BrainBtzAnimal` in the engine RTTI/class-factory system.
- `FUN_109844b0` (line 1507377) — **RTTI_GetClassInfo_BrainSturmbeest** — class self-registration getter (calls FUN_100016b0("BrainSturmbeest", parent-getter)); registers `BrainSturmbeest` as a subclass of `BrainBtzAnimal` in the engine RTTI/class-factory system.
- `FUN_10984450` (line 1507345) — **RTTI_GetClassInfo_BrainTapirus** — class self-registration getter (calls FUN_100016b0("BrainTapirus", parent-getter)); registers `BrainTapirus` as a subclass of `BrainBtzAnimal` in the engine RTTI/class-factory system.
- `FUN_10984510` (line 1507409) — **RTTI_GetClassInfo_BrainThanator** — class self-registration getter (calls FUN_100016b0("BrainThanator", parent-getter)); registers `BrainThanator` as a subclass of `BrainBtzAnimal` in the engine RTTI/class-factory system.
- `FUN_108e5a20` (line 1427663) — **RTTI_GetClassInfo_BuildSecondaryBase** — class self-registration getter (calls FUN_100016b0("BuildSecondaryBase", parent-getter)); registers `BuildSecondaryBase` as a subclass of `TerritoryManagement` in the engine RTTI/class-factory system.
- `FUN_108d9850` (line 1419028) — **RTTI_GetClassInfo_BuyTroops** — class self-registration getter (calls FUN_100016b0("BuyTroops", parent-getter)); registers `BuyTroops` as a subclass of `Action` in the engine RTTI/class-factory system.
- `FUN_108d9880` (line 1419044) — **RTTI_GetClassInfo_BuyTroopsData** — class self-registration getter (calls FUN_100016b0("BuyTroopsData", parent-getter)); registers `BuyTroopsData` as a subclass of `ActionData` in the engine RTTI/class-factory system.
- `FUN_101a6e30` (line 292883) — **RTTI_GetClassInfo_CAABBPartitionManager** — class self-registration getter (calls FUN_100016b0("CAABBPartitionManager", parent-getter)); registers `CAABBPartitionManager` as a subclass of `CSingletonEntity` in the engine RTTI/class-factory system.
- `FUN_10980620` (line 1502081) — **RTTI_GetClassInfo_CAIBuilding** — class self-registration getter (calls FUN_100016b0("CAIBuilding", parent-getter)); registers `CAIBuilding` as a subclass of `CGameAIObject` in the engine RTTI/class-factory system.
- `FUN_1003dd60` (line 42561) — **RTTI_GetClassInfo_CAIComponent** — class self-registration getter (calls FUN_100016b0("CAIComponent", parent-getter)); registers `CAIComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_109a3ee0` (line 1526982) — **RTTI_GetClassInfo_CAIEvent** — class self-registration getter (calls FUN_100016b0("CAIEvent", parent-getter)); registers `CAIEvent` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_1097f0f0` (line 1501314) — **RTTI_GetClassInfo_CAIInfoManager** — class self-registration getter (calls FUN_100016b0("CAIInfoManager", parent-getter)); registers `CAIInfoManager` as a subclass of `CSingletonEntity` in the engine RTTI/class-factory system.
- `FUN_109805f0` (line 1502065) — **RTTI_GetClassInfo_CAIMountedWeapon** — class self-registration getter (calls FUN_100016b0("CAIMountedWeapon", parent-getter)); registers `CAIMountedWeapon` as a subclass of `CDynamicGameAIObject` in the engine RTTI/class-factory system.
- `FUN_104a18c0` (line 803063) — **RTTI_GetClassInfo_CAIObject** — class self-registration getter (calls FUN_100016b0("CAIObject", parent-getter)); registers `CAIObject` as a subclass of `CAIObjectRoot` in the engine RTTI/class-factory system.
- `FUN_104a1890` (line 803047) — **RTTI_GetClassInfo_CAIObjectRoot** — class self-registration getter (calls FUN_100016b0("CAIObjectRoot", parent-getter)); registers `CAIObjectRoot` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_104f7c70` (line 859181) — **RTTI_GetClassInfo_CAIShootMeEvent** — class self-registration getter (calls FUN_100016b0("CAIShootMeEvent", parent-getter)); registers `CAIShootMeEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_104c9350` (line 830218) — **RTTI_GetClassInfo_CAIShootMeObject** — class self-registration getter (calls FUN_100016b0("CAIShootMeObject", parent-getter)); registers `CAIShootMeObject` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a6800` (line 292443) — **RTTI_GetClassInfo_CAIStateComponent** — class self-registration getter (calls FUN_100016b0("CAIStateComponent", parent-getter)); registers `CAIStateComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104a1830` (line 803015) — **RTTI_GetClassInfo_CAIWorkspaceResource** — class self-registration getter (calls FUN_100016b0("CAIWorkspaceResource", parent-getter)); registers `CAIWorkspaceResource` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_1097dca0` (line 1500841) — **RTTI_GetClassInfo_CAIWorld** — class self-registration getter (calls FUN_100016b0("CAIWorld", parent-getter)); registers `CAIWorld` as a subclass of `CCollective` in the engine RTTI/class-factory system.
- `FUN_10984660` (line 1507521) — **RTTI_GetClassInfo_CAMPSuitAction** — class self-registration getter (calls FUN_100016b0("CAMPSuitAction", parent-getter)); registers `CAMPSuitAction` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_1097f4f0` (line 1501520) — **RTTI_GetClassInfo_CAMPSuitAgent** — class self-registration getter (calls FUN_100016b0("CAMPSuitAgent", parent-getter)); registers `CAMPSuitAgent` as a subclass of `CGameAgent` in the engine RTTI/class-factory system.
- `FUN_104c9db0` (line 830572) — **RTTI_GetClassInfo_CAMPSuitBeautifier** — class self-registration getter (calls FUN_100016b0("CAMPSuitBeautifier", parent-getter)); registers `CAMPSuitBeautifier` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_10550b30` (line 910103) — **RTTI_GetClassInfo_CAMPSuitCanAcceptUserEvent** — class self-registration getter (calls FUN_100016b0("CAMPSuitCanAcceptUserEvent", parent-getter)); registers `CAMPSuitCanAcceptUserEvent` as a subclass of `CBaseEvent` in the engine RTTI/class-factory system.
- `FUN_104c9a50` (line 830460) — **RTTI_GetClassInfo_CAMPSuitNetworkComponent** — class self-registration getter (calls FUN_100016b0("CAMPSuitNetworkComponent", parent-getter)); registers `CAMPSuitNetworkComponent` as a subclass of `CNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_104c9e70` (line 830588) — **RTTI_GetClassInfo_CAMPSuitSoundAndFXComponent** — class self-registration getter (calls FUN_100016b0("CAMPSuitSoundAndFXComponent", parent-getter)); registers `CAMPSuitSoundAndFXComponent` as a subclass of `CCreatureSoundAndFXComponent` in the engine RTTI/class-factory system.
- `FUN_10550c00` (line 910140) — **RTTI_GetClassInfo_CAMPSuitUserAttachedEvent** — class self-registration getter (calls FUN_100016b0("CAMPSuitUserAttachedEvent", parent-getter)); registers `CAMPSuitUserAttachedEvent` as a subclass of `CBaseEvent` in the engine RTTI/class-factory system.
- `FUN_10550cd0` (line 910177) — **RTTI_GetClassInfo_CAMPSuitUserDetachedEvent** — class self-registration getter (calls FUN_100016b0("CAMPSuitUserDetachedEvent", parent-getter)); registers `CAMPSuitUserDetachedEvent` as a subclass of `CBaseEvent` in the engine RTTI/class-factory system.
- `FUN_10142b50` (line 225688) — **RTTI_GetClassInfo_CAcceptConnectionOperation** — class self-registration getter (calls FUN_100016b0("CAcceptConnectionOperation", parent-getter)); registers `CAcceptConnectionOperation` as a subclass of `IOperation` in the engine RTTI/class-factory system.
- `FUN_104a1980` (line 803127) — **RTTI_GetClassInfo_CAction** — class self-registration getter (calls FUN_100016b0("CAction", parent-getter)); registers `CAction` as a subclass of `CTask` in the engine RTTI/class-factory system.
- `FUN_102524b0` (line 409842) — **RTTI_GetClassInfo_CAddSEFactEvent** — class self-registration getter (calls FUN_100016b0("CAddSEFactEvent", parent-getter)); registers `CAddSEFactEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_104a18f0` (line 803079) — **RTTI_GetClassInfo_CAgent** — class self-registration getter (calls FUN_100016b0("CAgent", parent-getter)); registers `CAgent` as a subclass of `CAIObject` in the engine RTTI/class-factory system.
- `FUN_10980650` (line 1502097) — **RTTI_GetClassInfo_CAgentAction** — class self-registration getter (calls FUN_100016b0("CAgentAction", parent-getter)); registers `CAgentAction` as a subclass of `CAction` in the engine RTTI/class-factory system.
- `FUN_10980680` (line 1502113) — **RTTI_GetClassInfo_CAgentDecision** — class self-registration getter (calls FUN_100016b0("CAgentDecision", parent-getter)); registers `CAgentDecision` as a subclass of `CDecision` in the engine RTTI/class-factory system.
- `FUN_10980f50` (line 1502865) — **RTTI_GetClassInfo_CAgentScanner** — class self-registration getter (calls FUN_100016b0("CAgentScanner", parent-getter)); registers `CAgentScanner` as a subclass of `CScanner` in the engine RTTI/class-factory system.
- `FUN_101a6d80` (line 292851) — **RTTI_GetClassInfo_CAlwaysLoaded** — class self-registration getter (calls FUN_100016b0("CAlwaysLoaded", parent-getter)); registers `CAlwaysLoaded` as a subclass of `CSingletonEntity` in the engine RTTI/class-factory system.
- `FUN_104cc220` (line 832175) — **RTTI_GetClassInfo_CAnimal** — class self-registration getter (calls FUN_100016b0("CAnimal", parent-getter)); registers `CAnimal` as a subclass of `CPawnBase` in the engine RTTI/class-factory system.
- `FUN_1097e3d0` (line 1501060) — **RTTI_GetClassInfo_CAnimalAgent** — class self-registration getter (calls FUN_100016b0("CAnimalAgent", parent-getter)); registers `CAnimalAgent` as a subclass of `CBaseAnimalAgent` in the engine RTTI/class-factory system.
- `FUN_104c9bd0` (line 830540) — **RTTI_GetClassInfo_CAnimalMemento** — class self-registration getter (calls FUN_100016b0("CAnimalMemento", parent-getter)); registers `CAnimalMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_10558070` (line 914034) — **RTTI_GetClassInfo_CAnimalNetFunc** — class self-registration getter (calls FUN_100016b0("CAnimalNetFunc", parent-getter)); registers `CAnimalNetFunc` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_104c9a80` (line 830476) — **RTTI_GetClassInfo_CAnimalNetworkComponent** — class self-registration getter (calls FUN_100016b0("CAnimalNetworkComponent", parent-getter)); registers `CAnimalNetworkComponent` as a subclass of `CNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_1097f060` (line 1501266) — **RTTI_GetClassInfo_CAnimalPersonality** — class self-registration getter (calls FUN_100016b0("CAnimalPersonality", parent-getter)); registers `CAnimalPersonality` as a subclass of `CLivingCreature` in the engine RTTI/class-factory system.
- `FUN_104ca6b0` (line 831004) — **RTTI_GetClassInfo_CAnimalSoundAndFXComponent** — class self-registration getter (calls FUN_100016b0("CAnimalSoundAndFXComponent", parent-getter)); registers `CAnimalSoundAndFXComponent` as a subclass of `CCreatureSoundAndFXComponent` in the engine RTTI/class-factory system.
- `FUN_1003dbb0` (line 42417) — **RTTI_GetClassInfo_CAnimationComponent** — class self-registration getter (calls FUN_100016b0("CAnimationComponent", parent-getter)); registers `CAnimationComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101b8a10` (line 306337) — **RTTI_GetClassInfo_CAnimationPackageResource** — class self-registration getter (calls FUN_100016b0("CAnimationPackageResource", parent-getter)); registers `CAnimationPackageResource` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_101b9200` (line 306949) — **RTTI_GetClassInfo_CAnimationResource** — class self-registration getter (calls FUN_100016b0("CAnimationResource", parent-getter)); registers `CAnimationResource` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_100c1d50` (line 138171) — **RTTI_GetClassInfo_CArchiveFile** — class self-registration getter (calls FUN_100016b0("CArchiveFile", parent-getter)); registers `CArchiveFile` as a subclass of `IFile` in the engine RTTI/class-factory system.
- `FUN_104c9f90` (line 830668) — **RTTI_GetClassInfo_CArmedVehicle** — class self-registration getter (calls FUN_100016b0("CArmedVehicle", parent-getter)); registers `CArmedVehicle` as a subclass of `CVehicle` in the engine RTTI/class-factory system.
- `FUN_1097d060` (line 1500071) — **RTTI_GetClassInfo_CArmy** — class self-registration getter (calls FUN_100016b0("CArmy", parent-getter)); registers `CArmy` as a subclass of `CCollective` in the engine RTTI/class-factory system.
- `FUN_101a0650` (line 287394) — **RTTI_GetClassInfo_CAuthorizationService** — class self-registration getter (calls FUN_100016b0("CAuthorizationService", parent-getter)); registers `CAuthorizationService` as a subclass of `IAuthorizationService` in the engine RTTI/class-factory system.
- `FUN_1097fc00` (line 1501762) — **RTTI_GetClassInfo_CAutomaticTurretAgent** — class self-registration getter (calls FUN_100016b0("CAutomaticTurretAgent", parent-getter)); registers `CAutomaticTurretAgent` as a subclass of `TurretAgent` in the engine RTTI/class-factory system.
- `FUN_101a72c0` (line 293229) — **RTTI_GetClassInfo_CAvatarBackgroundStaticGraphicComponent** — class self-registration getter (calls FUN_100016b0("CAvatarBackgroundStaticGraphicComponent", parent-getter)); registers `CAvatarBackgroundStaticGraphicComponent` as a subclass of `CStaticGraphicComponent` in the engine RTTI/class-factory system.
- `FUN_10558110` (line 914050) — **RTTI_GetClassInfo_CAvatarCharacterSheet_PlayerMemento** — class self-registration getter (calls FUN_100016b0("CAvatarCharacterSheet_PlayerMemento", parent-getter)); registers `CAvatarCharacterSheet_PlayerMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1095ac60` (line 1482076) — **RTTI_GetClassInfo_CAvatarFriendInteractiveNotification** — class self-registration getter (calls FUN_100016b0("CAvatarFriendInteractiveNotification", parent-getter)); registers `CAvatarFriendInteractiveNotification` as a subclass of `CAvatarFriendNotification` in the engine RTTI/class-factory system.
- `FUN_1095ac20` (line 1482057) — **RTTI_GetClassInfo_CAvatarFriendNotification** — class self-registration getter (calls FUN_100016b0("CAvatarFriendNotification", parent-getter)); registers `CAvatarFriendNotification` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_109363d0` (line 1467749) — **RTTI_GetClassInfo_CAvatarFriendsNotificationService** — class self-registration getter (calls FUN_100016b0("CAvatarFriendsNotificationService", parent-getter)); registers `CAvatarFriendsNotificationService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_10902210` (line 1443773) — **RTTI_GetClassInfo_CAvatarFriendsUIStrategy** — class self-registration getter (calls FUN_100016b0("CAvatarFriendsUIStrategy", parent-getter)); registers `CAvatarFriendsUIStrategy` as a subclass of `CUIStrategy` in the engine RTTI/class-factory system.
- `FUN_109367b0` (line 1467868) — **RTTI_GetClassInfo_CAvatarInviteFriendsUIStrategy** — class self-registration getter (calls FUN_100016b0("CAvatarInviteFriendsUIStrategy", parent-getter)); registers `CAvatarInviteFriendsUIStrategy` as a subclass of `CAvatarFriendsUIStrategy` in the engine RTTI/class-factory system.
- `FUN_10902240` (line 1443789) — **RTTI_GetClassInfo_CAvatarJoinFriendsUIStrategy** — class self-registration getter (calls FUN_100016b0("CAvatarJoinFriendsUIStrategy", parent-getter)); registers `CAvatarJoinFriendsUIStrategy` as a subclass of `CAvatarFriendsUIStrategy` in the engine RTTI/class-factory system.
- `FUN_108ef5a0` (line 1434034) — **RTTI_GetClassInfo_CAvatarLoadOutUIStrategy** — class self-registration getter (calls FUN_100016b0("CAvatarLoadOutUIStrategy", parent-getter)); registers `CAvatarLoadOutUIStrategy` as a subclass of `CLoadOutUIStrategy` in the engine RTTI/class-factory system.
- `FUN_109367e0` (line 1467884) — **RTTI_GetClassInfo_CAvatarManageFriendsUIStrategy** — class self-registration getter (calls FUN_100016b0("CAvatarManageFriendsUIStrategy", parent-getter)); registers `CAvatarManageFriendsUIStrategy` as a subclass of `CAvatarFriendsUIStrategy` in the engine RTTI/class-factory system.
- `FUN_101a6120` (line 291990) — **RTTI_GetClassInfo_CAvatarMultiVarsNetworkComponent** — class self-registration getter (calls FUN_100016b0("CAvatarMultiVarsNetworkComponent", parent-getter)); registers `CAvatarMultiVarsNetworkComponent` as a subclass of `CNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_104c9680` (line 830362) — **RTTI_GetClassInfo_CAvatarPawnFxComponent** — class self-registration getter (calls FUN_100016b0("CAvatarPawnFxComponent", parent-getter)); registers `CAvatarPawnFxComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104caef0` (line 831465) — **RTTI_GetClassInfo_CAvatarPlayerCommunicationComponent** — class self-registration getter (calls FUN_100016b0("CAvatarPlayerCommunicationComponent", parent-getter)); registers `CAvatarPlayerCommunicationComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104caec0` (line 831449) — **RTTI_GetClassInfo_CAvatarRadioComponent** — class self-registration getter (calls FUN_100016b0("CAvatarRadioComponent", parent-getter)); registers `CAvatarRadioComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_10570f40` (line 927617) — **RTTI_GetClassInfo_CAvatarRelayComponentTriggerEvent** — class self-registration getter (calls FUN_100016b0("CAvatarRelayComponentTriggerEvent", parent-getter)); registers `CAvatarRelayComponentTriggerEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1050f7f0` (line 874014) — **RTTI_GetClassInfo_CAvatarSkillNotificationEvent** — class self-registration getter (calls FUN_100016b0("CAvatarSkillNotificationEvent", parent-getter)); registers `CAvatarSkillNotificationEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1076d110` (line 1203513) — **RTTI_GetClassInfo_CAvatarSkinComponent** — class self-registration getter (calls FUN_100016b0("CAvatarSkinComponent", parent-getter)); registers `CAvatarSkinComponent` as a subclass of `CCustomMaterialComponent` in the engine RTTI/class-factory system.
- `FUN_101a7290` (line 293213) — **RTTI_GetClassInfo_CAvatarTreebranchManager** — class self-registration getter (calls FUN_100016b0("CAvatarTreebranchManager", parent-getter)); registers `CAvatarTreebranchManager` as a subclass of `CSingletonEntity` in the engine RTTI/class-factory system.
- `FUN_101a7260` (line 293197) — **RTTI_GetClassInfo_CAvatarTreebranchPoint** — class self-registration getter (calls FUN_100016b0("CAvatarTreebranchPoint", parent-getter)); registers `CAvatarTreebranchPoint` as a subclass of `COmniEntity` in the engine RTTI/class-factory system.
- `FUN_10578770` (line 931199) — **RTTI_GetClassInfo_CAvatarVisibilityHideEvent** — class self-registration getter (calls FUN_100016b0("CAvatarVisibilityHideEvent", parent-getter)); registers `CAvatarVisibilityHideEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_10578740` (line 931183) — **RTTI_GetClassInfo_CAvatarVisibilityShowEvent** — class self-registration getter (calls FUN_100016b0("CAvatarVisibilityShowEvent", parent-getter)); registers `CAvatarVisibilityShowEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1050fc90` (line 874201) — **RTTI_GetClassInfo_CBTZDamageEvent** — class self-registration getter (calls FUN_100016b0("CBTZDamageEvent", parent-getter)); registers `CBTZDamageEvent` as a subclass of `CBaseEvent` in the engine RTTI/class-factory system.
- `FUN_1003dc10` (line 42449) — **RTTI_GetClassInfo_CBTZDamageStim** — class self-registration getter (calls FUN_100016b0("CBTZDamageStim", parent-getter)); registers `CBTZDamageStim` as a subclass of `CEntityEventStims` in the engine RTTI/class-factory system.
- `FUN_105e0ac0` (line 985472) — **RTTI_GetClassInfo_CBTZFireDamageStim** — class self-registration getter (calls FUN_100016b0("CBTZFireDamageStim", parent-getter)); registers `CBTZFireDamageStim` as a subclass of `CBTZDamageStim` in the engine RTTI/class-factory system.
- `FUN_10705a20` (line 1147067) — **RTTI_GetClassInfo_CBTZGRStateCNHInRound** — class self-registration getter (calls FUN_100016b0("CBTZGRStateCNHInRound", parent-getter)); registers `CBTZGRStateCNHInRound` as a subclass of `CGRStateTeamAdversarialInRound` in the engine RTTI/class-factory system.
- `FUN_10704ff0` (line 1146649) — **RTTI_GetClassInfo_CBTZGRStateFinalBattleInRound** — class self-registration getter (calls FUN_100016b0("CBTZGRStateFinalBattleInRound", parent-getter)); registers `CBTZGRStateFinalBattleInRound` as a subclass of `CGRStateTeamAdversarialInRound` in the engine RTTI/class-factory system.
- `FUN_10704960` (line 1146258) — **RTTI_GetClassInfo_CBTZGRStateHordeInRound** — class self-registration getter (calls FUN_100016b0("CBTZGRStateHordeInRound", parent-getter)); registers `CBTZGRStateHordeInRound` as a subclass of `CGRStateTeamAdversarialInRound` in the engine RTTI/class-factory system.
- `FUN_10705a50` (line 1147083) — **RTTI_GetClassInfo_CBTZGRStateKingOfTheHillInRound** — class self-registration getter (calls FUN_100016b0("CBTZGRStateKingOfTheHillInRound", parent-getter)); registers `CBTZGRStateKingOfTheHillInRound` as a subclass of `CBTZGRStateCNHInRound` in the engine RTTI/class-factory system.
- `FUN_10647680` (line 1039702) — **RTTI_GetClassInfo_CBTZMatchService** — class self-registration getter (calls FUN_100016b0("CBTZMatchService", parent-getter)); registers `CBTZMatchService` as a subclass of `CMatchService` in the engine RTTI/class-factory system.
- `FUN_104ca5f0` (line 830988) — **RTTI_GetClassInfo_CBTZMissileRack** — class self-registration getter (calls FUN_100016b0("CBTZMissileRack", parent-getter)); registers `CBTZMissileRack` as a subclass of `CBTZVehicleWeapon` in the engine RTTI/class-factory system.
- `FUN_10198370` (line 280807) — **RTTI_GetClassInfo_CBTZOffscreenViewportTextureResource** — class self-registration getter (calls FUN_100016b0("CBTZOffscreenViewportTextureResource", parent-getter)); registers `CBTZOffscreenViewportTextureResource` as a subclass of `CTextureResource` in the engine RTTI/class-factory system.
- `FUN_104ca7a0` (line 831084) — **RTTI_GetClassInfo_CBTZPickupAmmo** — class self-registration getter (calls FUN_100016b0("CBTZPickupAmmo", parent-getter)); registers `CBTZPickupAmmo` as a subclass of `CPickup` in the engine RTTI/class-factory system.
- `FUN_104ca6e0` (line 831020) — **RTTI_GetClassInfo_CBTZProjectile** — class self-registration getter (calls FUN_100016b0("CBTZProjectile", parent-getter)); registers `CBTZProjectile` as a subclass of `CGameObject` in the engine RTTI/class-factory system.
- `FUN_104ca710` (line 831036) — **RTTI_GetClassInfo_CBTZProjectileSimple** — class self-registration getter (calls FUN_100016b0("CBTZProjectileSimple", parent-getter)); registers `CBTZProjectileSimple` as a subclass of `CGameObject` in the engine RTTI/class-factory system.
- `FUN_104ca740` (line 831052) — **RTTI_GetClassInfo_CBTZProjectileToxic** — class self-registration getter (calls FUN_100016b0("CBTZProjectileToxic", parent-getter)); registers `CBTZProjectileToxic` as a subclass of `CBTZProjectileSimple` in the engine RTTI/class-factory system.
- `FUN_104ca770` (line 831068) — **RTTI_GetClassInfo_CBTZSlingerProjectile** — class self-registration getter (calls FUN_100016b0("CBTZSlingerProjectile", parent-getter)); registers `CBTZSlingerProjectile` as a subclass of `CGameObject` in the engine RTTI/class-factory system.
- `FUN_104ca590` (line 830972) — **RTTI_GetClassInfo_CBTZVehicleWeapon** — class self-registration getter (calls FUN_100016b0("CBTZVehicleWeapon", parent-getter)); registers `CBTZVehicleWeapon` as a subclass of `BTZWeapon` in the engine RTTI/class-factory system.
- `FUN_1062ecf0` (line 1028925) — **RTTI_GetClassInfo_CBTZWeaponFireGrenadeStrategy** — class self-registration getter (calls FUN_100016b0("CBTZWeaponFireGrenadeStrategy", parent-getter)); registers `CBTZWeaponFireGrenadeStrategy` as a subclass of `CBTZWeaponFireProjectileStrategy` in the engine RTTI/class-factory system.
- `FUN_10581d00` (line 936348) — **RTTI_GetClassInfo_CBTZWeaponFireMeleeStrategy** — class self-registration getter (calls FUN_100016b0("CBTZWeaponFireMeleeStrategy", parent-getter)); registers `CBTZWeaponFireMeleeStrategy` as a subclass of `CWeaponFireMeleeStrategy` in the engine RTTI/class-factory system.
- `FUN_1062ecc0` (line 1028909) — **RTTI_GetClassInfo_CBTZWeaponFireProjectileStrategy** — class self-registration getter (calls FUN_100016b0("CBTZWeaponFireProjectileStrategy", parent-getter)); registers `CBTZWeaponFireProjectileStrategy` as a subclass of `CWeaponFireProjectileStrategy` in the engine RTTI/class-factory system.
- `FUN_1097f490` (line 1501488) — **RTTI_GetClassInfo_CBansheeAgent** — class self-registration getter (calls FUN_100016b0("CBansheeAgent", parent-getter)); registers `CBansheeAgent` as a subclass of `CVehicleAgent` in the engine RTTI/class-factory system.
- `FUN_10980560` (line 1502017) — **RTTI_GetClassInfo_CBargeDelimiter** — class self-registration getter (calls FUN_100016b0("CBargeDelimiter", parent-getter)); registers `CBargeDelimiter` as a subclass of `CGameAIObject` in the engine RTTI/class-factory system.
- `FUN_105930c0` (line 944710) — **RTTI_GetClassInfo_CBarkManagerService** — class self-registration getter (calls FUN_100016b0("CBarkManagerService", parent-getter)); registers `CBarkManagerService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_10697480` (line 1087061) — **RTTI_GetClassInfo_CBarkResourceContainer** — class self-registration getter (calls FUN_100016b0("CBarkResourceContainer", parent-getter)); registers `CBarkResourceContainer` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_1097e3a0` (line 1501044) — **RTTI_GetClassInfo_CBaseAnimalAgent** — class self-registration getter (calls FUN_100016b0("CBaseAnimalAgent", parent-getter)); registers `CBaseAnimalAgent` as a subclass of `CPawnBaseAgent` in the engine RTTI/class-factory system.
- `FUN_100460e0` (line 46339) — **RTTI_GetClassInfo_CBaseEntity** — class self-registration getter (calls FUN_100016b0("CBaseEntity", parent-getter)); registers `CBaseEntity` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_1003dac0` (line 42355) — **RTTI_GetClassInfo_CBaseEvent** — class self-registration getter (calls FUN_100016b0("CBaseEvent", parent-getter)); registers `CBaseEvent` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_104ef7b0` (line 853991) — **RTTI_GetClassInfo_CBaseFact** — class self-registration getter (calls FUN_100016b0("CBaseFact", parent-getter)); registers `CBaseFact` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_10055b90` (line 58107) — **RTTI_GetClassInfo_CBaseGraphicComponent** — class self-registration getter (calls FUN_100016b0("CBaseGraphicComponent", parent-getter)); registers `CBaseGraphicComponent` as a subclass of `CRenderableComponent` in the engine RTTI/class-factory system.
- `FUN_106e6320` (line 1128597) — **RTTI_GetClassInfo_CBaseMission** — class self-registration getter (calls FUN_100016b0("CBaseMission", parent-getter)); registers `CBaseMission` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_104ca800` (line 831116) — **RTTI_GetClassInfo_CBaseTriggerComponent** — class self-registration getter (calls FUN_100016b0("CBaseTriggerComponent", parent-getter)); registers `CBaseTriggerComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a67a0` (line 292411) — **RTTI_GetClassInfo_CBasicRegionEntity** — class self-registration getter (calls FUN_100016b0("CBasicRegionEntity", parent-getter)); registers `CBasicRegionEntity` as a subclass of `CBasicShapeEntity` in the engine RTTI/class-factory system.
- `FUN_101a6ad0` (line 292683) — **RTTI_GetClassInfo_CBasicShapeComponent** — class self-registration getter (calls FUN_100016b0("CBasicShapeComponent", parent-getter)); registers `CBasicShapeComponent` as a subclass of `IShapeComponent` in the engine RTTI/class-factory system.
- `FUN_101a6740` (line 292379) — **RTTI_GetClassInfo_CBasicShapeEntity** — class self-registration getter (calls FUN_100016b0("CBasicShapeEntity", parent-getter)); registers `CBasicShapeEntity` as a subclass of `IShapeEntity` in the engine RTTI/class-factory system.
- `FUN_1076c700` (line 1203268) — **RTTI_GetClassInfo_CBeautifierRepository** — class self-registration getter (calls FUN_100016b0("CBeautifierRepository", parent-getter)); registers `CBeautifierRepository` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_100c2b20` (line 138927) — **RTTI_GetClassInfo_CBinaryResource** — class self-registration getter (calls FUN_100016b0("CBinaryResource", parent-getter)); registers `CBinaryResource` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_101a5920` (line 291430) — **RTTI_GetClassInfo_CBindingComponent** — class self-registration getter (calls FUN_100016b0("CBindingComponent", parent-getter)); registers `CBindingComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_103b5560` (line 643615) — **RTTI_GetClassInfo_CBinkResource** — class self-registration getter (calls FUN_100016b0("CBinkResource", parent-getter)); registers `CBinkResource` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_109806b0` (line 1502129) — **RTTI_GetClassInfo_CBlueprintDecision** — class self-registration getter (calls FUN_100016b0("CBlueprintDecision", parent-getter)); registers `CBlueprintDecision` as a subclass of `CDecision` in the engine RTTI/class-factory system.
- `FUN_10628e00` (line 1025598) — **RTTI_GetClassInfo_CBonusService** — class self-registration getter (calls FUN_100016b0("CBonusService", parent-getter)); registers `CBonusService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_108a5d60` (line 1390336) — **RTTI_GetClassInfo_CBonusServiceMP** — class self-registration getter (calls FUN_100016b0("CBonusServiceMP", parent-getter)); registers `CBonusServiceMP` as a subclass of `CBonusService` in the engine RTTI/class-factory system.
- `FUN_106d3f60` (line 1117624) — **RTTI_GetClassInfo_CBootESRBOnlineWarningOperation** — class self-registration getter (calls FUN_100016b0("CBootESRBOnlineWarningOperation", parent-getter)); registers `CBootESRBOnlineWarningOperation` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d3f30` (line 1117608) — **RTTI_GetClassInfo_CBootFullScreenVideoOperation** — class self-registration getter (calls FUN_100016b0("CBootFullScreenVideoOperation", parent-getter)); registers `CBootFullScreenVideoOperation` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_104a1a40` (line 803191) — **RTTI_GetClassInfo_CBrain** — class self-registration getter (calls FUN_100016b0("CBrain", parent-getter)); registers `CBrain` as a subclass of `CPlan` in the engine RTTI/class-factory system.
- `FUN_10984630` (line 1507505) — **RTTI_GetClassInfo_CBrainAMPSuit** — class self-registration getter (calls FUN_100016b0("CBrainAMPSuit", parent-getter)); registers `CBrainAMPSuit` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_10982990` (line 1505105) — **RTTI_GetClassInfo_CBrainAnimal** — class self-registration getter (calls FUN_100016b0("CBrainAnimal", parent-getter)); registers `CBrainAnimal` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_109829f0` (line 1505137) — **RTTI_GetClassInfo_CBrainAnimalAlert** — class self-registration getter (calls FUN_100016b0("CBrainAnimalAlert", parent-getter)); registers `CBrainAnimalAlert` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_10982a20` (line 1505153) — **RTTI_GetClassInfo_CBrainAnimalAttack** — class self-registration getter (calls FUN_100016b0("CBrainAnimalAttack", parent-getter)); registers `CBrainAnimalAttack` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_109829c0` (line 1505121) — **RTTI_GetClassInfo_CBrainAnimalIdle** — class self-registration getter (calls FUN_100016b0("CBrainAnimalIdle", parent-getter)); registers `CBrainAnimalIdle` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_109810a0` (line 1502977) — **RTTI_GetClassInfo_CBrainBlackboardSelector** — class self-registration getter (calls FUN_100016b0("CBrainBlackboardSelector", parent-getter)); registers `CBrainBlackboardSelector` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_10982ba0` (line 1505281) — **RTTI_GetClassInfo_CBrainBoat** — class self-registration getter (calls FUN_100016b0("CBrainBoat", parent-getter)); registers `CBrainBoat` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_10982a80` (line 1505185) — **RTTI_GetClassInfo_CBrainBuddyBase** — class self-registration getter (calls FUN_100016b0("CBrainBuddyBase", parent-getter)); registers `CBrainBuddyBase` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_10982ae0` (line 1505217) — **RTTI_GetClassInfo_CBrainCopter** — class self-registration getter (calls FUN_100016b0("CBrainCopter", parent-getter)); registers `CBrainCopter` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_10982b70` (line 1505265) — **RTTI_GetClassInfo_CBrainDomino** — class self-registration getter (calls FUN_100016b0("CBrainDomino", parent-getter)); registers `CBrainDomino` as a subclass of `CBrainPawnBase` in the engine RTTI/class-factory system.
- `FUN_10982bd0` (line 1505297) — **RTTI_GetClassInfo_CBrainDrone** — class self-registration getter (calls FUN_100016b0("CBrainDrone", parent-getter)); registers `CBrainDrone` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_109844e0` (line 1507393) — **RTTI_GetClassInfo_CBrainHammerhead** — class self-registration getter (calls FUN_100016b0("CBrainHammerhead", parent-getter)); registers `CBrainHammerhead` as a subclass of `BrainBtzAnimal` in the engine RTTI/class-factory system.
- `FUN_10982b10` (line 1505233) — **RTTI_GetClassInfo_CBrainHybridBanshee** — class self-registration getter (calls FUN_100016b0("CBrainHybridBanshee", parent-getter)); registers `CBrainHybridBanshee` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_10982c90` (line 1505361) — **RTTI_GetClassInfo_CBrainLayeredPatrol** — class self-registration getter (calls FUN_100016b0("CBrainLayeredPatrol", parent-getter)); registers `CBrainLayeredPatrol` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_10982780` (line 1504929) — **RTTI_GetClassInfo_CBrainMerc** — class self-registration getter (calls FUN_100016b0("CBrainMerc", parent-getter)); registers `CBrainMerc` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_10984ae0` (line 1507905) — **RTTI_GetClassInfo_CBrainMercAMPSuit** — class self-registration getter (calls FUN_100016b0("CBrainMercAMPSuit", parent-getter)); registers `CBrainMercAMPSuit` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_109827e0` (line 1504961) — **RTTI_GetClassInfo_CBrainMercAlert** — class self-registration getter (calls FUN_100016b0("CBrainMercAlert", parent-getter)); registers `CBrainMercAlert` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_10982810` (line 1504977) — **RTTI_GetClassInfo_CBrainMercCombat** — class self-registration getter (calls FUN_100016b0("CBrainMercCombat", parent-getter)); registers `CBrainMercCombat` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_109828a0` (line 1505025) — **RTTI_GetClassInfo_CBrainMercDead** — class self-registration getter (calls FUN_100016b0("CBrainMercDead", parent-getter)); registers `CBrainMercDead` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_10984b40` (line 1507937) — **RTTI_GetClassInfo_CBrainMercHitAndRun** — class self-registration getter (calls FUN_100016b0("CBrainMercHitAndRun", parent-getter)); registers `CBrainMercHitAndRun` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_109827b0` (line 1504945) — **RTTI_GetClassInfo_CBrainMercIdle** — class self-registration getter (calls FUN_100016b0("CBrainMercIdle", parent-getter)); registers `CBrainMercIdle` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_10982840` (line 1504993) — **RTTI_GetClassInfo_CBrainMercSocial** — class self-registration getter (calls FUN_100016b0("CBrainMercSocial", parent-getter)); registers `CBrainMercSocial` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_10982870` (line 1505009) — **RTTI_GetClassInfo_CBrainMercSocialBehavior** — class self-registration getter (calls FUN_100016b0("CBrainMercSocialBehavior", parent-getter)); registers `CBrainMercSocialBehavior` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_10982900` (line 1505057) — **RTTI_GetClassInfo_CBrainMercSpecial** — class self-registration getter (calls FUN_100016b0("CBrainMercSpecial", parent-getter)); registers `CBrainMercSpecial` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_10982930` (line 1505073) — **RTTI_GetClassInfo_CBrainMercVehicle** — class self-registration getter (calls FUN_100016b0("CBrainMercVehicle", parent-getter)); registers `CBrainMercVehicle` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_10982720` (line 1504897) — **RTTI_GetClassInfo_CBrainPawn** — class self-registration getter (calls FUN_100016b0("CBrainPawn", parent-getter)); registers `CBrainPawn` as a subclass of `CBrainPawnBase` in the engine RTTI/class-factory system.
- `FUN_109826c0` (line 1504865) — **RTTI_GetClassInfo_CBrainPawnBase** — class self-registration getter (calls FUN_100016b0("CBrainPawnBase", parent-getter)); registers `CBrainPawnBase` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_10982750` (line 1504913) — **RTTI_GetClassInfo_CBrainPlayer** — class self-registration getter (calls FUN_100016b0("CBrainPlayer", parent-getter)); registers `CBrainPlayer` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_10982a50` (line 1505169) — **RTTI_GetClassInfo_CBrainRescueBuddy** — class self-registration getter (calls FUN_100016b0("CBrainRescueBuddy", parent-getter)); registers `CBrainRescueBuddy` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_109826f0` (line 1504881) — **RTTI_GetClassInfo_CBrainSimple** — class self-registration getter (calls FUN_100016b0("CBrainSimple", parent-getter)); registers `CBrainSimple` as a subclass of `CBrainPawnBase` in the engine RTTI/class-factory system.
- `FUN_10982960` (line 1505089) — **RTTI_GetClassInfo_CBrainSmartTerrain** — class self-registration getter (calls FUN_100016b0("CBrainSmartTerrain", parent-getter)); registers `CBrainSmartTerrain` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_10982c00` (line 1505313) — **RTTI_GetClassInfo_CBrainSpecialCharacter** — class self-registration getter (calls FUN_100016b0("CBrainSpecialCharacter", parent-getter)); registers `CBrainSpecialCharacter` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_109828d0` (line 1505041) — **RTTI_GetClassInfo_CBrainStoopidMerc** — class self-registration getter (calls FUN_100016b0("CBrainStoopidMerc", parent-getter)); registers `CBrainStoopidMerc` as a subclass of `CBrainPawn` in the engine RTTI/class-factory system.
- `FUN_10982ab0` (line 1505201) — **RTTI_GetClassInfo_CBrainVehicle** — class self-registration getter (calls FUN_100016b0("CBrainVehicle", parent-getter)); registers `CBrainVehicle` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_10982b40` (line 1505249) — **RTTI_GetClassInfo_CBrainVehicleCombat** — class self-registration getter (calls FUN_100016b0("CBrainVehicleCombat", parent-getter)); registers `CBrainVehicleCombat` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_10984370` (line 1507313) — **RTTI_GetClassInfo_CBrainViperwolf** — class self-registration getter (calls FUN_100016b0("CBrainViperwolf", parent-getter)); registers `CBrainViperwolf` as a subclass of `BrainBtzAnimal` in the engine RTTI/class-factory system.
- `FUN_1021fc40` (line 378033) — **RTTI_GetClassInfo_CBranchPathFollower** — class self-registration getter (calls FUN_100016b0("CBranchPathFollower", parent-getter)); registers `CBranchPathFollower` as a subclass of `CRandomPathFollower` in the engine RTTI/class-factory system.
- `FUN_104cc250` (line 832191) — **RTTI_GetClassInfo_CBtzAnimal** — class self-registration getter (calls FUN_100016b0("CBtzAnimal", parent-getter)); registers `CBtzAnimal` as a subclass of `CAnimal` in the engine RTTI/class-factory system.
- `FUN_109845a0` (line 1507457) — **RTTI_GetClassInfo_CBtzAnimalAction** — class self-registration getter (calls FUN_100016b0("CBtzAnimalAction", parent-getter)); registers `CBtzAnimalAction` as a subclass of `CPawnBaseAction` in the engine RTTI/class-factory system.
- `FUN_1097f2e0` (line 1501344) — **RTTI_GetClassInfo_CBtzAnimalAgent** — class self-registration getter (calls FUN_100016b0("CBtzAnimalAgent", parent-getter)); registers `CBtzAnimalAgent` as a subclass of `CBaseAnimalAgent` in the engine RTTI/class-factory system.
- `FUN_108ef2d0` (line 1433954) — **RTTI_GetClassInfo_CBtzAudioOptionsUIStrategy** — class self-registration getter (calls FUN_100016b0("CBtzAudioOptionsUIStrategy", parent-getter)); registers `CBtzAudioOptionsUIStrategy` as a subclass of `CBtzOptionsBaseUIStrategy` in the engine RTTI/class-factory system.
- `FUN_108ef240` (line 1433922) — **RTTI_GetClassInfo_CBtzDisplayOptionsUIStrategy** — class self-registration getter (calls FUN_100016b0("CBtzDisplayOptionsUIStrategy", parent-getter)); registers `CBtzDisplayOptionsUIStrategy` as a subclass of `CBtzOptionsBaseUIStrategy` in the engine RTTI/class-factory system.
- `FUN_10921ec0` (line 1458150) — **RTTI_GetClassInfo_CBtzGameFile** — class self-registration getter (calls FUN_100016b0("CBtzGameFile", parent-getter)); registers `CBtzGameFile` as a subclass of `CGameFile` in the engine RTTI/class-factory system.
- `FUN_108ef210` (line 1433906) — **RTTI_GetClassInfo_CBtzGameOptionsUIStrategy** — class self-registration getter (calls FUN_100016b0("CBtzGameOptionsUIStrategy", parent-getter)); registers `CBtzGameOptionsUIStrategy` as a subclass of `CBtzOptionsBaseUIStrategy` in the engine RTTI/class-factory system.
- `FUN_101a7200` (line 293165) — **RTTI_GetClassInfo_CBtzHudManager** — class self-registration getter (calls FUN_100016b0("CBtzHudManager", parent-getter)); registers `CBtzHudManager` as a subclass of `CSingletonEntity` in the engine RTTI/class-factory system.
- `FUN_108f3640` (line 1435331) — **RTTI_GetClassInfo_CBtzHudUIStrategy** — class self-registration getter (calls FUN_100016b0("CBtzHudUIStrategy", parent-getter)); registers `CBtzHudUIStrategy` as a subclass of `CUIStrategy` in the engine RTTI/class-factory system.
- `FUN_108f3670` (line 1435347) — **RTTI_GetClassInfo_CBtzHudUIStrategy_Base** — class self-registration getter (calls FUN_100016b0("CBtzHudUIStrategy_Base", parent-getter)); registers `CBtzHudUIStrategy_Base` as a subclass of `CBtzHudUIStrategy` in the engine RTTI/class-factory system.
- `FUN_10943ce0` (line 1471910) — **RTTI_GetClassInfo_CBtzHudUIStrategy_Single** — class self-registration getter (calls FUN_100016b0("CBtzHudUIStrategy_Single", parent-getter)); registers `CBtzHudUIStrategy_Single` as a subclass of `CBtzHudUIStrategy_Base` in the engine RTTI/class-factory system.
- `FUN_10943e60` (line 1471958) — **RTTI_GetClassInfo_CBtzHudUIStrategy_TeamDeathMatch** — class self-registration getter (calls FUN_100016b0("CBtzHudUIStrategy_TeamDeathMatch", parent-getter)); registers `CBtzHudUIStrategy_TeamDeathMatch` as a subclass of `CBtzHudUIStrategy_Single` in the engine RTTI/class-factory system.
- `FUN_104cc280` (line 832207) — **RTTI_GetClassInfo_CBtzHybridAnimal** — class self-registration getter (calls FUN_100016b0("CBtzHybridAnimal", parent-getter)); registers `CBtzHybridAnimal` as a subclass of `CBtzAnimal` in the engine RTTI/class-factory system.
- `FUN_104c9b40` (line 830492) — **RTTI_GetClassInfo_CBtzHybridAnimalNetworkComponent** — class self-registration getter (calls FUN_100016b0("CBtzHybridAnimalNetworkComponent", parent-getter)); registers `CBtzHybridAnimalNetworkComponent` as a subclass of `CAnimalNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_108ef2a0` (line 1433938) — **RTTI_GetClassInfo_CBtzInputOptionsUIStrategy** — class self-registration getter (calls FUN_100016b0("CBtzInputOptionsUIStrategy", parent-getter)); registers `CBtzInputOptionsUIStrategy` as a subclass of `CBtzOptionsBaseUIStrategy` in the engine RTTI/class-factory system.
- `FUN_108ef570` (line 1434018) — **RTTI_GetClassInfo_CBtzLoginOnlineAccountUIStrategy** — class self-registration getter (calls FUN_100016b0("CBtzLoginOnlineAccountUIStrategy", parent-getter)); registers `CBtzLoginOnlineAccountUIStrategy` as a subclass of `CUIStrategy` in the engine RTTI/class-factory system.
- `FUN_108ef0f0` (line 1433874) — **RTTI_GetClassInfo_CBtzMultiLauncherUIStrategy** — class self-registration getter (calls FUN_100016b0("CBtzMultiLauncherUIStrategy", parent-getter)); registers `CBtzMultiLauncherUIStrategy` as a subclass of `CUIStrategy` in the engine RTTI/class-factory system.
- `FUN_108f36a0` (line 1435363) — **RTTI_GetClassInfo_CBtzNotificationUIStrategy** — class self-registration getter (calls FUN_100016b0("CBtzNotificationUIStrategy", parent-getter)); registers `CBtzNotificationUIStrategy` as a subclass of `CBtzHudUIStrategy` in the engine RTTI/class-factory system.
- `FUN_10943e30` (line 1471942) — **RTTI_GetClassInfo_CBtzNotificationUIStrategy_FinalBattle** — class self-registration getter (calls FUN_100016b0("CBtzNotificationUIStrategy_FinalBattle", parent-getter)); registers `CBtzNotificationUIStrategy_FinalBattle` as a subclass of `CBtzNotificationUIStrategy` in the engine RTTI/class-factory system.
- `FUN_108ef180` (line 1433890) — **RTTI_GetClassInfo_CBtzOptionsBaseUIStrategy** — class self-registration getter (calls FUN_100016b0("CBtzOptionsBaseUIStrategy", parent-getter)); registers `CBtzOptionsBaseUIStrategy` as a subclass of `CUIStrategy` in the engine RTTI/class-factory system.
- `FUN_10943e00` (line 1471926) — **RTTI_GetClassInfo_CBtzUiIndicatorStrategy** — class self-registration getter (calls FUN_100016b0("CBtzUiIndicatorStrategy", parent-getter)); registers `CBtzUiIndicatorStrategy` as a subclass of `CUIStrategy` in the engine RTTI/class-factory system.
- `FUN_105a0730` (line 953045) — **RTTI_GetClassInfo_CBuddiesManager** — class self-registration getter (calls FUN_100016b0("CBuddiesManager", parent-getter)); registers `CBuddiesManager` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_104caad0` (line 831241) — **RTTI_GetClassInfo_CBuildingInfoComponent** — class self-registration getter (calls FUN_100016b0("CBuildingInfoComponent", parent-getter)); registers `CBuildingInfoComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104ccb60` (line 832523) — **RTTI_GetClassInfo_CBurnableRegion** — class self-registration getter (calls FUN_100016b0("CBurnableRegion", parent-getter)); registers `CBurnableRegion` as a subclass of `CBasicShapeEntity` in the engine RTTI/class-factory system.
- `FUN_104cbd20` (line 831930) — **RTTI_GetClassInfo_CCameraBoneComponent** — class self-registration getter (calls FUN_100016b0("CCameraBoneComponent", parent-getter)); registers `CCameraBoneComponent` as a subclass of `CCameraComponent` in the engine RTTI/class-factory system.
- `FUN_10248cd0` (line 405340) — **RTTI_GetClassInfo_CCameraComponent** — class self-registration getter (calls FUN_100016b0("CCameraComponent", parent-getter)); registers `CCameraComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104cac80` (line 831337) — **RTTI_GetClassInfo_CCameraFreeComponent** — class self-registration getter (calls FUN_100016b0("CCameraFreeComponent", parent-getter)); registers `CCameraFreeComponent` as a subclass of `CCameraNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_104cad10` (line 831369) — **RTTI_GetClassInfo_CCameraGameComponent** — class self-registration getter (calls FUN_100016b0("CCameraGameComponent", parent-getter)); registers `CCameraGameComponent` as a subclass of `CCameraNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_104cace0` (line 831353) — **RTTI_GetClassInfo_CCameraGhostComponent** — class self-registration getter (calls FUN_100016b0("CCameraGhostComponent", parent-getter)); registers `CCameraGhostComponent` as a subclass of `CCameraFreeComponent` in the engine RTTI/class-factory system.
- `FUN_1053bc90` (line 899695) — **RTTI_GetClassInfo_CCameraMode** — class self-registration getter (calls FUN_100016b0("CCameraMode", parent-getter)); registers `CCameraMode` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_1053bcc0` (line 899711) — **RTTI_GetClassInfo_CCameraModeGameplay** — class self-registration getter (calls FUN_100016b0("CCameraModeGameplay", parent-getter)); registers `CCameraModeGameplay` as a subclass of `CCameraMode` in the engine RTTI/class-factory system.
- `FUN_104cac50` (line 831321) — **RTTI_GetClassInfo_CCameraNetworkComponent** — class self-registration getter (calls FUN_100016b0("CCameraNetworkComponent", parent-getter)); registers `CCameraNetworkComponent` as a subclass of `CCameraComponent` in the engine RTTI/class-factory system.
- `FUN_104cae60` (line 831433) — **RTTI_GetClassInfo_CCameraParamVehicleComponent** — class self-registration getter (calls FUN_100016b0("CCameraParamVehicleComponent", parent-getter)); registers `CCameraParamVehicleComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104cad40` (line 831385) — **RTTI_GetClassInfo_CCameraPawnComponent** — class self-registration getter (calls FUN_100016b0("CCameraPawnComponent", parent-getter)); registers `CCameraPawnComponent` as a subclass of `CCameraGameComponent` in the engine RTTI/class-factory system.
- `FUN_104cae00` (line 831417) — **RTTI_GetClassInfo_CCameraPlanetComponent** — class self-registration getter (calls FUN_100016b0("CCameraPlanetComponent", parent-getter)); registers `CCameraPlanetComponent` as a subclass of `CCameraComponent` in the engine RTTI/class-factory system.
- `FUN_104cbd50` (line 831946) — **RTTI_GetClassInfo_CCameraShakeAndPadRumbleComponent** — class self-registration getter (calls FUN_100016b0("CCameraShakeAndPadRumbleComponent", parent-getter)); registers `CCameraShakeAndPadRumbleComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104cada0` (line 831401) — **RTTI_GetClassInfo_CCameraThirdComponent** — class self-registration getter (calls FUN_100016b0("CCameraThirdComponent", parent-getter)); registers `CCameraThirdComponent` as a subclass of `CCameraNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_104caa30` (line 831209) — **RTTI_GetClassInfo_CCapturePoint** — class self-registration getter (calls FUN_100016b0("CCapturePoint", parent-getter)); registers `CCapturePoint` as a subclass of `CGameObject` in the engine RTTI/class-factory system.
- `FUN_104caa60` (line 831225) — **RTTI_GetClassInfo_CCapturePointNetworkComponent** — class self-registration getter (calls FUN_100016b0("CCapturePointNetworkComponent", parent-getter)); registers `CCapturePointNetworkComponent` as a subclass of `CNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_105f9c90` (line 999300) — **RTTI_GetClassInfo_CChallenge** — class self-registration getter (calls FUN_100016b0("CChallenge", parent-getter)); registers `CChallenge` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_104cb870` (line 831834) — **RTTI_GetClassInfo_CChallengeComponent** — class self-registration getter (calls FUN_100016b0("CChallengeComponent", parent-getter)); registers `CChallengeComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_105f9cc0` (line 999316) — **RTTI_GetClassInfo_CChallengeWeapon** — class self-registration getter (calls FUN_100016b0("CChallengeWeapon", parent-getter)); registers `CChallengeWeapon` as a subclass of `CChallenge` in the engine RTTI/class-factory system.
- `FUN_1003dcd0` (line 42513) — **RTTI_GetClassInfo_CCharacterPhysComponent** — class self-registration getter (calls FUN_100016b0("CCharacterPhysComponent", parent-getter)); registers `CCharacterPhysComponent` as a subclass of `CPhysComponent` in the engine RTTI/class-factory system.
- `FUN_1003dbe0` (line 42433) — **RTTI_GetClassInfo_CCharacterSheet** — class self-registration getter (calls FUN_100016b0("CCharacterSheet", parent-getter)); registers `CCharacterSheet` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1023e490` (line 397821) — **RTTI_GetClassInfo_CChatMessage** — class self-registration getter (calls FUN_100016b0("CChatMessage", parent-getter)); registers `CChatMessage` as a subclass of `CGameMessage` in the engine RTTI/class-factory system.
- `FUN_10611f20` (line 1011753) — **RTTI_GetClassInfo_CCheckScoutEvent** — class self-registration getter (calls FUN_100016b0("CCheckScoutEvent", parent-getter)); registers `CCheckScoutEvent` as a subclass of `CBaseEvent` in the engine RTTI/class-factory system.
- `FUN_101a5f10` (line 291814) — **RTTI_GetClassInfo_CCinematicCameraEntity** — class self-registration getter (calls FUN_100016b0("CCinematicCameraEntity", parent-getter)); registers `CCinematicCameraEntity` as a subclass of `CEntity` in the engine RTTI/class-factory system.
- `FUN_10e9f2e0` (line 2413810) — **RTTI_GetClassInfo_CClientDescriptor** — class self-registration getter (calls FUN_100016b0("CClientDescriptor", parent-getter)); registers `CClientDescriptor` as a subclass of `CNetDescriptor` in the engine RTTI/class-factory system.
- `FUN_10e9f310` (line 2413826) — **RTTI_GetClassInfo_CClientDescriptor_RdV** — class self-registration getter (calls FUN_100016b0("CClientDescriptor_RdV", parent-getter)); registers `CClientDescriptor_RdV` as a subclass of `CClientDescriptor` in the engine RTTI/class-factory system.
- `FUN_10e97230` (line 2407940) — **RTTI_GetClassInfo_CClientInfo** — class self-registration getter (calls FUN_100016b0("CClientInfo", parent-getter)); registers `CClientInfo` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_10e972e0` (line 2407975) — **RTTI_GetClassInfo_CClientInfo_RdV** — class self-registration getter (calls FUN_100016b0("CClientInfo_RdV", parent-getter)); registers `CClientInfo_RdV` as a subclass of `CClientInfo` in the engine RTTI/class-factory system.
- `FUN_104f86c0` (line 859593) — **RTTI_GetClassInfo_CCloseComputerEvent** — class self-registration getter (calls FUN_100016b0("CCloseComputerEvent", parent-getter)); registers `CCloseComputerEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_101a6950` (line 292555) — **RTTI_GetClassInfo_CClusterComponent** — class self-registration getter (calls FUN_100016b0("CClusterComponent", parent-getter)); registers `CClusterComponent` as a subclass of `CRenderableComponent` in the engine RTTI/class-factory system.
- `FUN_101a6a70` (line 292651) — **RTTI_GetClassInfo_CCollectionComponent** — class self-registration getter (calls FUN_100016b0("CCollectionComponent", parent-getter)); registers `CCollectionComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a66b0` (line 292331) — **RTTI_GetClassInfo_CCollectionManager** — class self-registration getter (calls FUN_100016b0("CCollectionManager", parent-getter)); registers `CCollectionManager` as a subclass of `CSingletonEntity` in the engine RTTI/class-factory system.
- `FUN_104a1aa0` (line 803223) — **RTTI_GetClassInfo_CCollective** — class self-registration getter (calls FUN_100016b0("CCollective", parent-getter)); registers `CCollective` as a subclass of `CAIObject` in the engine RTTI/class-factory system.
- `FUN_1005aa30` (line 61721) — **RTTI_GetClassInfo_CCommandCBParam** — class self-registration getter (calls FUN_100016b0("CCommandCBParam", parent-getter)); registers `CCommandCBParam` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_1060dd80` (line 1009528) — **RTTI_GetClassInfo_CCompassObjectives** — class self-registration getter (calls FUN_100016b0("CCompassObjectives", parent-getter)); registers `CCompassObjectives` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_102d38e0` (line 492823) — **RTTI_GetClassInfo_CCompoundPhysChangeStateEvent** — class self-registration getter (calls FUN_100016b0("CCompoundPhysChangeStateEvent", parent-getter)); registers `CCompoundPhysChangeStateEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1021c930` (line 375518) — **RTTI_GetClassInfo_CCompoundPhysComponent** — class self-registration getter (calls FUN_100016b0("CCompoundPhysComponent", parent-getter)); registers `CCompoundPhysComponent` as a subclass of `CPhysComponent` in the engine RTTI/class-factory system.
- `FUN_10306a20` (line 526313) — **RTTI_GetClassInfo_CCompoundPhysComponentBreakableNode** — class self-registration getter (calls FUN_100016b0("CCompoundPhysComponentBreakableNode", parent-getter)); registers `CCompoundPhysComponentBreakableNode` as a subclass of `CCompoundPhysComponentNode` in the engine RTTI/class-factory system.
- `FUN_1030c940` (line 529394) — **RTTI_GetClassInfo_CCompoundPhysComponentListNode** — class self-registration getter (calls FUN_100016b0("CCompoundPhysComponentListNode", parent-getter)); registers `CCompoundPhysComponentListNode` as a subclass of `CCompoundPhysComponentNode` in the engine RTTI/class-factory system.
- `FUN_102d36f0` (line 492679) — **RTTI_GetClassInfo_CCompoundPhysComponentNode** — class self-registration getter (calls FUN_100016b0("CCompoundPhysComponentNode", parent-getter)); registers `CCompoundPhysComponentNode` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_102d3a40` (line 492888) — **RTTI_GetClassInfo_CCompoundPhysComponentSingleBodyNode** — class self-registration getter (calls FUN_100016b0("CCompoundPhysComponentSingleBodyNode", parent-getter)); registers `CCompoundPhysComponentSingleBodyNode` as a subclass of `CCompoundPhysComponentNode` in the engine RTTI/class-factory system.
- `FUN_102d3870` (line 492807) — **RTTI_GetClassInfo_CCompoundPhysDestroyEvent** — class self-registration getter (calls FUN_100016b0("CCompoundPhysDestroyEvent", parent-getter)); registers `CCompoundPhysDestroyEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_102262c0` (line 382334) — **RTTI_GetClassInfo_CCompoundPhysForceStateEvent** — class self-registration getter (calls FUN_100016b0("CCompoundPhysForceStateEvent", parent-getter)); registers `CCompoundPhysForceStateEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_102045a0` (line 360127) — **RTTI_GetClassInfo_CCompoundPhysMemento** — class self-registration getter (calls FUN_100016b0("CCompoundPhysMemento", parent-getter)); registers `CCompoundPhysMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1021c9f0` (line 375582) — **RTTI_GetClassInfo_CCompoundPhysNetworkComponent** — class self-registration getter (calls FUN_100016b0("CCompoundPhysNetworkComponent", parent-getter)); registers `CCompoundPhysNetworkComponent` as a subclass of `CNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_102d3840` (line 492791) — **RTTI_GetClassInfo_CCompoundPhysOnDamageEvent** — class self-registration getter (calls FUN_100016b0("CCompoundPhysOnDamageEvent", parent-getter)); registers `CCompoundPhysOnDamageEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_102d3780` (line 492727) — **RTTI_GetClassInfo_CCompoundPhysOnDamageLastStateEvent** — class self-registration getter (calls FUN_100016b0("CCompoundPhysOnDamageLastStateEvent", parent-getter)); registers `CCompoundPhysOnDamageLastStateEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_102d37e0` (line 492759) — **RTTI_GetClassInfo_CCompoundPhysOnDamageStateChangeEvent** — class self-registration getter (calls FUN_100016b0("CCompoundPhysOnDamageStateChangeEvent", parent-getter)); registers `CCompoundPhysOnDamageStateChangeEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_102d3810` (line 492775) — **RTTI_GetClassInfo_CCompoundPhysOnDestroyEvent** — class self-registration getter (calls FUN_100016b0("CCompoundPhysOnDestroyEvent", parent-getter)); registers `CCompoundPhysOnDestroyEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_102d37b0` (line 492743) — **RTTI_GetClassInfo_CCompoundPhysOnEventLastStateEvent** — class self-registration getter (calls FUN_100016b0("CCompoundPhysOnEventLastStateEvent", parent-getter)); registers `CCompoundPhysOnEventLastStateEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_102d3750` (line 492711) — **RTTI_GetClassInfo_CCompoundPhysOnPartBreakOffEvent** — class self-registration getter (calls FUN_100016b0("CCompoundPhysOnPartBreakOffEvent", parent-getter)); registers `CCompoundPhysOnPartBreakOffEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_10286190` (line 442042) — **RTTI_GetClassInfo_CCompoundPhysOnPostStateChangeEvent** — class self-registration getter (calls FUN_100016b0("CCompoundPhysOnPostStateChangeEvent", parent-getter)); registers `CCompoundPhysOnPostStateChangeEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_102d3720` (line 492695) — **RTTI_GetClassInfo_CCompoundPhysOnStateChangeEvent** — class self-registration getter (calls FUN_100016b0("CCompoundPhysOnStateChangeEvent", parent-getter)); registers `CCompoundPhysOnStateChangeEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1014bcf0` (line 232822) — **RTTI_GetClassInfo_CConnectMessage** — class self-registration getter (calls FUN_100016b0("CConnectMessage", parent-getter)); registers `CConnectMessage` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_10e8cdc0` (line 2399378) — **RTTI_GetClassInfo_CConnectOperation** — class self-registration getter (calls FUN_100016b0("CConnectOperation", parent-getter)); registers `CConnectOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10138280` (line 217697) — **RTTI_GetClassInfo_CConnectionMsg** — class self-registration getter (calls FUN_100016b0("CConnectionMsg", parent-getter)); registers `CConnectionMsg` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_10138300` (line 217726) — **RTTI_GetClassInfo_CConnectionMsgConnectResponse** — class self-registration getter (calls FUN_100016b0("CConnectionMsgConnectResponse", parent-getter)); registers `CConnectionMsgConnectResponse` as a subclass of `CConnectionMsg` in the engine RTTI/class-factory system.
- `FUN_10138370` (line 217763) — **RTTI_GetClassInfo_CConnectionMsgDisconnect** — class self-registration getter (calls FUN_100016b0("CConnectionMsgDisconnect", parent-getter)); registers `CConnectionMsgDisconnect` as a subclass of `CConnectionMsg` in the engine RTTI/class-factory system.
- `FUN_10980590` (line 1502033) — **RTTI_GetClassInfo_CConvoyMission** — class self-registration getter (calls FUN_100016b0("CConvoyMission", parent-getter)); registers `CConvoyMission` as a subclass of `CGameAIObject` in the engine RTTI/class-factory system.
- `FUN_101a5890` (line 291382) — **RTTI_GetClassInfo_CCorpseComponent** — class self-registration getter (calls FUN_100016b0("CCorpseComponent", parent-getter)); registers `CCorpseComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1023e6f0` (line 397853) — **RTTI_GetClassInfo_CCountDownMessage** — class self-registration getter (calls FUN_100016b0("CCountDownMessage", parent-getter)); registers `CCountDownMessage` as a subclass of `CGameMessage` in the engine RTTI/class-factory system.
- `FUN_106483d0` (line 1039815) — **RTTI_GetClassInfo_CCounterThresholdCrossedEvent** — class self-registration getter (calls FUN_100016b0("CCounterThresholdCrossedEvent", parent-getter)); registers `CCounterThresholdCrossedEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1003dd00` (line 42529) — **RTTI_GetClassInfo_CCountersComponent** — class self-registration getter (calls FUN_100016b0("CCountersComponent", parent-getter)); registers `CCountersComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104cb070` (line 831545) — **RTTI_GetClassInfo_CCountersComponentGO** — class self-registration getter (calls FUN_100016b0("CCountersComponentGO", parent-getter)); registers `CCountersComponentGO` as a subclass of `CCountersComponent` in the engine RTTI/class-factory system.
- `FUN_108c21c0` (line 1405566) — **RTTI_GetClassInfo_CCreateConnectionMessage** — class self-registration getter (calls FUN_100016b0("CCreateConnectionMessage", parent-getter)); registers `CCreateConnectionMessage` as a subclass of `CConnectMessage` in the engine RTTI/class-factory system.
- `FUN_10136870` (line 216394) — **RTTI_GetClassInfo_CCreateNetObjectOperation** — class self-registration getter (calls FUN_100016b0("CCreateNetObjectOperation", parent-getter)); registers `CCreateNetObjectOperation` as a subclass of `CNetObjectOperation` in the engine RTTI/class-factory system.
- `FUN_1052eb00` (line 891206) — **RTTI_GetClassInfo_CCreatureShakeAndRumbleEvent** — class self-registration getter (calls FUN_100016b0("CCreatureShakeAndRumbleEvent", parent-getter)); registers `CCreatureShakeAndRumbleEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_104c95c0` (line 830314) — **RTTI_GetClassInfo_CCreatureSoundAndFXComponent** — class self-registration getter (calls FUN_100016b0("CCreatureSoundAndFXComponent", parent-getter)); registers `CCreatureSoundAndFXComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a6620` (line 292283) — **RTTI_GetClassInfo_CCurve** — class self-registration getter (calls FUN_100016b0("CCurve", parent-getter)); registers `CCurve` as a subclass of `CBaseEntity` in the engine RTTI/class-factory system.
- `FUN_10198430` (line 280870) — **RTTI_GetClassInfo_CCustomMaterialComponent** — class self-registration getter (calls FUN_100016b0("CCustomMaterialComponent", parent-getter)); registers `CCustomMaterialComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_106476e0` (line 1039734) — **RTTI_GetClassInfo_CDMSpawnPointService** — class self-registration getter (calls FUN_100016b0("CDMSpawnPointService", parent-getter)); registers `CDMSpawnPointService` as a subclass of `CSpawnPointService` in the engine RTTI/class-factory system.
- `FUN_101a6c50` (line 292811) — **RTTI_GetClassInfo_CDataBaseItemManager** — class self-registration getter (calls FUN_100016b0("CDataBaseItemManager", parent-getter)); registers `CDataBaseItemManager` as a subclass of `CSingletonEntity` in the engine RTTI/class-factory system.
- `FUN_101a5b00` (line 291590) — **RTTI_GetClassInfo_CDayCycleScale** — class self-registration getter (calls FUN_100016b0("CDayCycleScale", parent-getter)); registers `CDayCycleScale` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_106e97b0` (line 1130301) — **RTTI_GetClassInfo_CDeathMessage** — class self-registration getter (calls FUN_100016b0("CDeathMessage", parent-getter)); registers `CDeathMessage` as a subclass of `CGameMessage` in the engine RTTI/class-factory system.
- `FUN_104a19b0` (line 803143) — **RTTI_GetClassInfo_CDecision** — class self-registration getter (calls FUN_100016b0("CDecision", parent-getter)); registers `CDecision` as a subclass of `CTask` in the engine RTTI/class-factory system.
- `FUN_101dead0` (line 334826) — **RTTI_GetClassInfo_CDependenciesService** — class self-registration getter (calls FUN_100016b0("CDependenciesService", parent-getter)); registers `CDependenciesService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1012e400` (line 209163) — **RTTI_GetClassInfo_CDeserializeNetDataVisitor** — class self-registration getter (calls FUN_100016b0("CDeserializeNetDataVisitor", parent-getter)); registers `CDeserializeNetDataVisitor` as a subclass of `CNetDataVisitor` in the engine RTTI/class-factory system.
- `FUN_1021d520` (line 376193) — **RTTI_GetClassInfo_CDestroyEvent** — class self-registration getter (calls FUN_100016b0("CDestroyEvent", parent-getter)); registers `CDestroyEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1025a530` (line 414775) — **RTTI_GetClassInfo_CDialogEvent** — class self-registration getter (calls FUN_100016b0("CDialogEvent", parent-getter)); registers `CDialogEvent` as a subclass of `CSoundEvent` in the engine RTTI/class-factory system.
- `FUN_10611be0` (line 1011596) — **RTTI_GetClassInfo_CDiamondPickedEvent** — class self-registration getter (calls FUN_100016b0("CDiamondPickedEvent", parent-getter)); registers `CDiamondPickedEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1097f400` (line 1501440) — **RTTI_GetClassInfo_CDirehorseAgent** — class self-registration getter (calls FUN_100016b0("CDirehorseAgent", parent-getter)); registers `CDirehorseAgent` as a subclass of `CBtzAnimalAgent` in the engine RTTI/class-factory system.
- `FUN_105ab3c0` (line 958547) — **RTTI_GetClassInfo_CDisableNavMeshVolumeEvent** — class self-registration getter (calls FUN_100016b0("CDisableNavMeshVolumeEvent", parent-getter)); registers `CDisableNavMeshVolumeEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_10138250` (line 217681) — **RTTI_GetClassInfo_CDisconnectBanned** — class self-registration getter (calls FUN_100016b0("CDisconnectBanned", parent-getter)); registers `CDisconnectBanned` as a subclass of `CDisconnectMessage` in the engine RTTI/class-factory system.
- `FUN_10138220` (line 217665) — **RTTI_GetClassInfo_CDisconnectMessage** — class self-registration getter (calls FUN_100016b0("CDisconnectMessage", parent-getter)); registers `CDisconnectMessage` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_10142ef0` (line 225928) — **RTTI_GetClassInfo_CDisconnectionOperation** — class self-registration getter (calls FUN_100016b0("CDisconnectionOperation", parent-getter)); registers `CDisconnectionOperation` as a subclass of `IOperation` in the engine RTTI/class-factory system.
- `FUN_104a1a70` (line 803207) — **RTTI_GetClassInfo_CDispatcher** — class self-registration getter (calls FUN_100016b0("CDispatcher", parent-getter)); registers `CDispatcher` as a subclass of `CAgent` in the engine RTTI/class-factory system.
- `FUN_1097de00` (line 1500958) — **RTTI_GetClassInfo_CDispatcherConvoy** — class self-registration getter (calls FUN_100016b0("CDispatcherConvoy", parent-getter)); registers `CDispatcherConvoy` as a subclass of `CDispatcher` in the engine RTTI/class-factory system.
- `FUN_1097dd10` (line 1500878) — **RTTI_GetClassInfo_CDispatcherSocial** — class self-registration getter (calls FUN_100016b0("CDispatcherSocial", parent-getter)); registers `CDispatcherSocial` as a subclass of `CDispatcher` in the engine RTTI/class-factory system.
- `FUN_1097dc70` (line 1500825) — **RTTI_GetClassInfo_CDispatcherSquadLieutenant** — class self-registration getter (calls FUN_100016b0("CDispatcherSquadLieutenant", parent-getter)); registers `CDispatcherSquadLieutenant` as a subclass of `CDispatcher` in the engine RTTI/class-factory system.
- `FUN_1097dd70` (line 1500910) — **RTTI_GetClassInfo_CDispatcherVehicle** — class self-registration getter (calls FUN_100016b0("CDispatcherVehicle", parent-getter)); registers `CDispatcherVehicle` as a subclass of `CDispatcher` in the engine RTTI/class-factory system.
- `FUN_104cbe10` (line 832010) — **RTTI_GetClassInfo_CDlcService** — class self-registration getter (calls FUN_100016b0("CDlcService", parent-getter)); registers `CDlcService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_105558b0` (line 912697) — **RTTI_GetClassInfo_CDodgeEvent** — class self-registration getter (calls FUN_100016b0("CDodgeEvent", parent-getter)); registers `CDodgeEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1029c380` (line 455803) — **RTTI_GetClassInfo_CDominoBoxInstance** — class self-registration getter (calls FUN_100016b0("CDominoBoxInstance", parent-getter)); registers `CDominoBoxInstance` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_10226090` (line 382214) — **RTTI_GetClassInfo_CDominoBoxResource** — class self-registration getter (calls FUN_100016b0("CDominoBoxResource", parent-getter)); registers `CDominoBoxResource` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_1029ad20` (line 454881) — **RTTI_GetClassInfo_CDominoCallbackEvent** — class self-registration getter (calls FUN_100016b0("CDominoCallbackEvent", parent-getter)); registers `CDominoCallbackEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_101a6150` (line 292006) — **RTTI_GetClassInfo_CDominoComponent** — class self-registration getter (calls FUN_100016b0("CDominoComponent", parent-getter)); registers `CDominoComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_10261300` (line 418561) — **RTTI_GetClassInfo_CDominoEvent** — class self-registration getter (calls FUN_100016b0("CDominoEvent", parent-getter)); registers `CDominoEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_101a72f0` (line 293245) — **RTTI_GetClassInfo_CDominoManager** — class self-registration getter (calls FUN_100016b0("CDominoManager", parent-getter)); registers `CDominoManager` as a subclass of `CSingletonEntity` in the engine RTTI/class-factory system.
- `FUN_101a0680` (line 287410) — **RTTI_GetClassInfo_CDominoService** — class self-registration getter (calls FUN_100016b0("CDominoService", parent-getter)); registers `CDominoService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_106d7c80` (line 1120112) — **RTTI_GetClassInfo_CDominoWorldSynchFlagOp** — class self-registration getter (calls FUN_100016b0("CDominoWorldSynchFlagOp", parent-getter)); registers `CDominoWorldSynchFlagOp` as a subclass of `CFCXLoadWorldSynchOp` in the engine RTTI/class-factory system.
- `FUN_104cb680` (line 831786) — **RTTI_GetClassInfo_CDoor** — class self-registration getter (calls FUN_100016b0("CDoor", parent-getter)); registers `CDoor` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a6860` (line 292475) — **RTTI_GetClassInfo_CDoubleFusionComponent** — class self-registration getter (calls FUN_100016b0("CDoubleFusionComponent", parent-getter)); registers `CDoubleFusionComponent` as a subclass of `COnlineAdComponent` in the engine RTTI/class-factory system.
- `FUN_1097fbd0` (line 1501746) — **RTTI_GetClassInfo_CDroneBombAgent** — class self-registration getter (calls FUN_100016b0("CDroneBombAgent", parent-getter)); registers `CDroneBombAgent` as a subclass of `TurretAgent` in the engine RTTI/class-factory system.
- `FUN_104cc2b0` (line 832223) — **RTTI_GetClassInfo_CDynLoadComponent** — class self-registration getter (calls FUN_100016b0("CDynLoadComponent", parent-getter)); registers `CDynLoadComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a5980` (line 291462) — **RTTI_GetClassInfo_CDynamicDeploadComponent** — class self-registration getter (calls FUN_100016b0("CDynamicDeploadComponent", parent-getter)); registers `CDynamicDeploadComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_109803e0` (line 1501889) — **RTTI_GetClassInfo_CDynamicGameAIObject** — class self-registration getter (calls FUN_100016b0("CDynamicGameAIObject", parent-getter)); registers `CDynamicGameAIObject` as a subclass of `CGameAIObject` in the engine RTTI/class-factory system.
- `FUN_101a6bc0` (line 292763) — **RTTI_GetClassInfo_CDynamicLightComponent** — class self-registration getter (calls FUN_100016b0("CDynamicLightComponent", parent-getter)); registers `CDynamicLightComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104c93e0` (line 830234) — **RTTI_GetClassInfo_CEconomyComponent** — class self-registration getter (calls FUN_100016b0("CEconomyComponent", parent-getter)); registers `CEconomyComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101b89e0` (line 306321) — **RTTI_GetClassInfo_CEditableEventComponent** — class self-registration getter (calls FUN_100016b0("CEditableEventComponent", parent-getter)); registers `CEditableEventComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_105ab430` (line 958584) — **RTTI_GetClassInfo_CEnableNavMeshVolumeEvent** — class self-registration getter (calls FUN_100016b0("CEnableNavMeshVolumeEvent", parent-getter)); registers `CEnableNavMeshVolumeEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_100461b0` (line 46408) — **RTTI_GetClassInfo_CEntity** — class self-registration getter (calls FUN_100016b0("CEntity", parent-getter)); registers `CEntity` as a subclass of `CBaseEntity` in the engine RTTI/class-factory system.
- `FUN_1003cd50` (line 41615) — **RTTI_GetClassInfo_CEntityComponent** — class self-registration getter (calls FUN_100016b0("CEntityComponent", parent-getter)); registers `CEntityComponent` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_10229d60` (line 383816) — **RTTI_GetClassInfo_CEntityDieEvent** — class self-registration getter (calls FUN_100016b0("CEntityDieEvent", parent-getter)); registers `CEntityDieEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1003daf0` (line 42371) — **RTTI_GetClassInfo_CEntityEvent** — class self-registration getter (calls FUN_100016b0("CEntityEvent", parent-getter)); registers `CEntityEvent` as a subclass of `CBaseEvent` in the engine RTTI/class-factory system.
- `FUN_10738af0` (line 1174136) — **RTTI_GetClassInfo_CEntityEventAddContainer** — class self-registration getter (calls FUN_100016b0("CEntityEventAddContainer", parent-getter)); registers `CEntityEventAddContainer` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_10738a80` (line 1174099) — **RTTI_GetClassInfo_CEntityEventCanContain** — class self-registration getter (calls FUN_100016b0("CEntityEventCanContain", parent-getter)); registers `CEntityEventCanContain` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_104efa10` (line 854155) — **RTTI_GetClassInfo_CEntityEventIsUsable** — class self-registration getter (calls FUN_100016b0("CEntityEventIsUsable", parent-getter)); registers `CEntityEventIsUsable` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_104efa80` (line 854192) — **RTTI_GetClassInfo_CEntityEventOnUsed** — class self-registration getter (calls FUN_100016b0("CEntityEventOnUsed", parent-getter)); registers `CEntityEventOnUsed` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1051c250` (line 881121) — **RTTI_GetClassInfo_CEntityEventOnUsing** — class self-registration getter (calls FUN_100016b0("CEntityEventOnUsing", parent-getter)); registers `CEntityEventOnUsing` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_107ec2a0` (line 1280192) — **RTTI_GetClassInfo_CEntityEventProjectileBindState** — class self-registration getter (calls FUN_100016b0("CEntityEventProjectileBindState", parent-getter)); registers `CEntityEventProjectileBindState` as a subclass of `CBaseEvent` in the engine RTTI/class-factory system.
- `FUN_1003db20` (line 42387) — **RTTI_GetClassInfo_CEntityEventStims** — class self-registration getter (calls FUN_100016b0("CEntityEventStims", parent-getter)); registers `CEntityEventStims` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1018d230` (line 274681) — **RTTI_GetClassInfo_CEntityNetDescriptor** — class self-registration getter (calls FUN_100016b0("CEntityNetDescriptor", parent-getter)); registers `CEntityNetDescriptor` as a subclass of `CNetDescriptor` in the engine RTTI/class-factory system.
- `FUN_1053bda0` (line 899748) — **RTTI_GetClassInfo_CEntityReviveEvent** — class self-registration getter (calls FUN_100016b0("CEntityReviveEvent", parent-getter)); registers `CEntityReviveEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_106d8470` (line 1120382) — **RTTI_GetClassInfo_CEntitySystemService** — class self-registration getter (calls FUN_100016b0("CEntitySystemService", parent-getter)); registers `CEntitySystemService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_104efaf0` (line 854229) — **RTTI_GetClassInfo_CEntityUsableStateEvent** — class self-registration getter (calls FUN_100016b0("CEntityUsableStateEvent", parent-getter)); registers `CEntityUsableStateEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_104cab00` (line 831257) — **RTTI_GetClassInfo_CEntranceInfoComponent** — class self-registration getter (calls FUN_100016b0("CEntranceInfoComponent", parent-getter)); registers `CEntranceInfoComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a5c00` (line 291670) — **RTTI_GetClassInfo_CEnvironmentAdaptiveBloom** — class self-registration getter (calls FUN_100016b0("CEnvironmentAdaptiveBloom", parent-getter)); registers `CEnvironmentAdaptiveBloom` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_101a5ca0` (line 291718) — **RTTI_GetClassInfo_CEnvironmentAtmosphericScattering** — class self-registration getter (calls FUN_100016b0("CEnvironmentAtmosphericScattering", parent-getter)); registers `CEnvironmentAtmosphericScattering` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_101a5b90` (line 291638) — **RTTI_GetClassInfo_CEnvironmentCloud** — class self-registration getter (calls FUN_100016b0("CEnvironmentCloud", parent-getter)); registers `CEnvironmentCloud` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_101a5aa0` (line 291558) — **RTTI_GetClassInfo_CEnvironmentCorpHighlight** — class self-registration getter (calls FUN_100016b0("CEnvironmentCorpHighlight", parent-getter)); registers `CEnvironmentCorpHighlight` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_101a5c30` (line 291686) — **RTTI_GetClassInfo_CEnvironmentDepthOfField** — class self-registration getter (calls FUN_100016b0("CEnvironmentDepthOfField", parent-getter)); registers `CEnvironmentDepthOfField` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_101a59e0` (line 291494) — **RTTI_GetClassInfo_CEnvironmentFog** — class self-registration getter (calls FUN_100016b0("CEnvironmentFog", parent-getter)); registers `CEnvironmentFog` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_101a5c70` (line 291702) — **RTTI_GetClassInfo_CEnvironmentGlow** — class self-registration getter (calls FUN_100016b0("CEnvironmentGlow", parent-getter)); registers `CEnvironmentGlow` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_101a59b0` (line 291478) — **RTTI_GetClassInfo_CEnvironmentLighting** — class self-registration getter (calls FUN_100016b0("CEnvironmentLighting", parent-getter)); registers `CEnvironmentLighting` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_101a5b30` (line 291606) — **RTTI_GetClassInfo_CEnvironmentPlanets** — class self-registration getter (calls FUN_100016b0("CEnvironmentPlanets", parent-getter)); registers `CEnvironmentPlanets` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_101a5a10` (line 291510) — **RTTI_GetClassInfo_CEnvironmentSky** — class self-registration getter (calls FUN_100016b0("CEnvironmentSky", parent-getter)); registers `CEnvironmentSky` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_101a5a70` (line 291542) — **RTTI_GetClassInfo_CEnvironmentSun** — class self-registration getter (calls FUN_100016b0("CEnvironmentSun", parent-getter)); registers `CEnvironmentSun` as a subclass of `CEnvironmentWithDependencies` in the engine RTTI/class-factory system.
- `FUN_101a5b60` (line 291622) — **RTTI_GetClassInfo_CEnvironmentTransition** — class self-registration getter (calls FUN_100016b0("CEnvironmentTransition", parent-getter)); registers `CEnvironmentTransition` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_101a5ad0` (line 291574) — **RTTI_GetClassInfo_CEnvironmentWeather** — class self-registration getter (calls FUN_100016b0("CEnvironmentWeather", parent-getter)); registers `CEnvironmentWeather` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_101a5bc0` (line 291654) — **RTTI_GetClassInfo_CEnvironmentWind** — class self-registration getter (calls FUN_100016b0("CEnvironmentWind", parent-getter)); registers `CEnvironmentWind` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_101a5a40` (line 291526) — **RTTI_GetClassInfo_CEnvironmentWithDependencies** — class self-registration getter (calls FUN_100016b0("CEnvironmentWithDependencies", parent-getter)); registers `CEnvironmentWithDependencies` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_104c9ba0` (line 830524) — **RTTI_GetClassInfo_CEquipmentBase** — class self-registration getter (calls FUN_100016b0("CEquipmentBase", parent-getter)); registers `CEquipmentBase` as a subclass of `CGameObject` in the engine RTTI/class-factory system.
- `FUN_104ca4d0` (line 830908) — **RTTI_GetClassInfo_CEquipmentUseStrategy** — class self-registration getter (calls FUN_100016b0("CEquipmentUseStrategy", parent-getter)); registers `CEquipmentUseStrategy` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_109e6140` (line 1562932) — **RTTI_GetClassInfo_CEventAMPSuitCommandAcquireUser** — class self-registration getter (calls FUN_100016b0("CEventAMPSuitCommandAcquireUser", parent-getter)); registers `CEventAMPSuitCommandAcquireUser` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109a4280` (line 1527292) — **RTTI_GetClassInfo_CEventBuddyReportTargetUpdate** — class self-registration getter (calls FUN_100016b0("CEventBuddyReportTargetUpdate", parent-getter)); registers `CEventBuddyReportTargetUpdate` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109d3f40` (line 1554847) — **RTTI_GetClassInfo_CEventCommonCommandExecuteSTP** — class self-registration getter (calls FUN_100016b0("CEventCommonCommandExecuteSTP", parent-getter)); registers `CEventCommonCommandExecuteSTP` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109a42f0` (line 1527329) — **RTTI_GetClassInfo_CEventCommonReportDestinationReached** — class self-registration getter (calls FUN_100016b0("CEventCommonReportDestinationReached", parent-getter)); registers `CEventCommonReportDestinationReached` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109ca680` (line 1548936) — **RTTI_GetClassInfo_CEventCommonReportUnreachableDestination** — class self-registration getter (calls FUN_100016b0("CEventCommonReportUnreachableDestination", parent-getter)); registers `CEventCommonReportUnreachableDestination` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_101a68c0` (line 292507) — **RTTI_GetClassInfo_CEventComponent** — class self-registration getter (calls FUN_100016b0("CEventComponent", parent-getter)); registers `CEventComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_109d3fd0` (line 1554895) — **RTTI_GetClassInfo_CEventDriveCommandCombatTarget** — class self-registration getter (calls FUN_100016b0("CEventDriveCommandCombatTarget", parent-getter)); registers `CEventDriveCommandCombatTarget` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109d3fa0` (line 1554879) — **RTTI_GetClassInfo_CEventDriveCommandConvoyCargo** — class self-registration getter (calls FUN_100016b0("CEventDriveCommandConvoyCargo", parent-getter)); registers `CEventDriveCommandConvoyCargo` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109d3f70` (line 1554863) — **RTTI_GetClassInfo_CEventDriveCommandConvoyLeader** — class self-registration getter (calls FUN_100016b0("CEventDriveCommandConvoyLeader", parent-getter)); registers `CEventDriveCommandConvoyLeader` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109d4090` (line 1554959) — **RTTI_GetClassInfo_CEventDriveCommandGhostPatrol** — class self-registration getter (calls FUN_100016b0("CEventDriveCommandGhostPatrol", parent-getter)); registers `CEventDriveCommandGhostPatrol` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109d4060` (line 1554943) — **RTTI_GetClassInfo_CEventDriveCommandReinforce** — class self-registration getter (calls FUN_100016b0("CEventDriveCommandReinforce", parent-getter)); registers `CEventDriveCommandReinforce` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109d4000` (line 1554911) — **RTTI_GetClassInfo_CEventDriveCommandSearchTarget** — class self-registration getter (calls FUN_100016b0("CEventDriveCommandSearchTarget", parent-getter)); registers `CEventDriveCommandSearchTarget` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109d4030` (line 1554927) — **RTTI_GetClassInfo_CEventDriveCommandSearchThreat** — class self-registration getter (calls FUN_100016b0("CEventDriveCommandSearchThreat", parent-getter)); registers `CEventDriveCommandSearchThreat` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109d0e40` (line 1553044) — **RTTI_GetClassInfo_CEventDriveReportConvoyNoUser** — class self-registration getter (calls FUN_100016b0("CEventDriveReportConvoyNoUser", parent-getter)); registers `CEventDriveReportConvoyNoUser` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109d0e70` (line 1553060) — **RTTI_GetClassInfo_CEventDriveReportConvoyTarget** — class self-registration getter (calls FUN_100016b0("CEventDriveReportConvoyTarget", parent-getter)); registers `CEventDriveReportConvoyTarget` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109d0e10` (line 1553028) — **RTTI_GetClassInfo_CEventDriveReportConvoyThreat** — class self-registration getter (calls FUN_100016b0("CEventDriveReportConvoyThreat", parent-getter)); registers `CEventDriveReportConvoyThreat` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109ca770` (line 1549016) — **RTTI_GetClassInfo_CEventDriveReportGunnerScanPos** — class self-registration getter (calls FUN_100016b0("CEventDriveReportGunnerScanPos", parent-getter)); registers `CEventDriveReportGunnerScanPos` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109ca6e0` (line 1548968) — **RTTI_GetClassInfo_CEventDriveReportLostOccupant** — class self-registration getter (calls FUN_100016b0("CEventDriveReportLostOccupant", parent-getter)); registers `CEventDriveReportLostOccupant` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109ca710` (line 1548984) — **RTTI_GetClassInfo_CEventDriveReportLostReservation** — class self-registration getter (calls FUN_100016b0("CEventDriveReportLostReservation", parent-getter)); registers `CEventDriveReportLostReservation` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109ca740` (line 1549000) — **RTTI_GetClassInfo_CEventDriveReportNewBestTarget** — class self-registration getter (calls FUN_100016b0("CEventDriveReportNewBestTarget", parent-getter)); registers `CEventDriveReportNewBestTarget` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109ca6b0` (line 1548952) — **RTTI_GetClassInfo_CEventDriveReportNewOccupant** — class self-registration getter (calls FUN_100016b0("CEventDriveReportNewOccupant", parent-getter)); registers `CEventDriveReportNewOccupant` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109a4320` (line 1527345) — **RTTI_GetClassInfo_CEventDriveReportReleasedVehicleUser** — class self-registration getter (calls FUN_100016b0("CEventDriveReportReleasedVehicleUser", parent-getter)); registers `CEventDriveReportReleasedVehicleUser` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109a4350` (line 1527361) — **RTTI_GetClassInfo_CEventDriveReportSlaveRequest** — class self-registration getter (calls FUN_100016b0("CEventDriveReportSlaveRequest", parent-getter)); registers `CEventDriveReportSlaveRequest` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6ba0` (line 1539632) — **RTTI_GetClassInfo_CEventMercCommandBark** — class self-registration getter (calls FUN_100016b0("CEventMercCommandBark", parent-getter)); registers `CEventMercCommandBark` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b69b0` (line 1539510) — **RTTI_GetClassInfo_CEventMercCommandCombatTarget** — class self-registration getter (calls FUN_100016b0("CEventMercCommandCombatTarget", parent-getter)); registers `CEventMercCommandCombatTarget` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6cc0` (line 1539728) — **RTTI_GetClassInfo_CEventMercCommandLaunchGrenadeInBuilding** — class self-registration getter (calls FUN_100016b0("CEventMercCommandLaunchGrenadeInBuilding", parent-getter)); registers `CEventMercCommandLaunchGrenadeInBuilding` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6cf0` (line 1539744) — **RTTI_GetClassInfo_CEventMercCommandPlayerInAIvsAIZone** — class self-registration getter (calls FUN_100016b0("CEventMercCommandPlayerInAIvsAIZone", parent-getter)); registers `CEventMercCommandPlayerInAIvsAIZone` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6a90` (line 1539563) — **RTTI_GetClassInfo_CEventMercCommandProjectileSeen** — class self-registration getter (calls FUN_100016b0("CEventMercCommandProjectileSeen", parent-getter)); registers `CEventMercCommandProjectileSeen` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6b40` (line 1539600) — **RTTI_GetClassInfo_CEventMercCommandSetArmyMemberRole** — class self-registration getter (calls FUN_100016b0("CEventMercCommandSetArmyMemberRole", parent-getter)); registers `CEventMercCommandSetArmyMemberRole` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6b70` (line 1539616) — **RTTI_GetClassInfo_CEventMercCommandSetArmyMemberRoleAction** — class self-registration getter (calls FUN_100016b0("CEventMercCommandSetArmyMemberRoleAction", parent-getter)); registers `CEventMercCommandSetArmyMemberRoleAction` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6c60` (line 1539696) — **RTTI_GetClassInfo_CEventMercCommandSetBestTarget** — class self-registration getter (calls FUN_100016b0("CEventMercCommandSetBestTarget", parent-getter)); registers `CEventMercCommandSetBestTarget` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6c90` (line 1539712) — **RTTI_GetClassInfo_CEventMercCommandSetGunnerScanPos** — class self-registration getter (calls FUN_100016b0("CEventMercCommandSetGunnerScanPos", parent-getter)); registers `CEventMercCommandSetGunnerScanPos` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6db0` (line 1539808) — **RTTI_GetClassInfo_CEventMercCommandSetLeaderTarget** — class self-registration getter (calls FUN_100016b0("CEventMercCommandSetLeaderTarget", parent-getter)); registers `CEventMercCommandSetLeaderTarget` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6de0` (line 1539824) — **RTTI_GetClassInfo_CEventMercCommandSetRallyPoint** — class self-registration getter (calls FUN_100016b0("CEventMercCommandSetRallyPoint", parent-getter)); registers `CEventMercCommandSetRallyPoint` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6d50` (line 1539776) — **RTTI_GetClassInfo_CEventMercCommandSetSquadAction** — class self-registration getter (calls FUN_100016b0("CEventMercCommandSetSquadAction", parent-getter)); registers `CEventMercCommandSetSquadAction` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6d80` (line 1539792) — **RTTI_GetClassInfo_CEventMercCommandSetSquadRole** — class self-registration getter (calls FUN_100016b0("CEventMercCommandSetSquadRole", parent-getter)); registers `CEventMercCommandSetSquadRole` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6e10` (line 1539840) — **RTTI_GetClassInfo_CEventMercCommandSocial** — class self-registration getter (calls FUN_100016b0("CEventMercCommandSocial", parent-getter)); registers `CEventMercCommandSocial` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6e40` (line 1539856) — **RTTI_GetClassInfo_CEventMercCommandStandOffFormation** — class self-registration getter (calls FUN_100016b0("CEventMercCommandStandOffFormation", parent-getter)); registers `CEventMercCommandStandOffFormation` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b69e0` (line 1539526) — **RTTI_GetClassInfo_CEventMercCommandThreatened** — class self-registration getter (calls FUN_100016b0("CEventMercCommandThreatened", parent-getter)); registers `CEventMercCommandThreatened` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6bd0` (line 1539648) — **RTTI_GetClassInfo_CEventMercCommandTrespassCombat** — class self-registration getter (calls FUN_100016b0("CEventMercCommandTrespassCombat", parent-getter)); registers `CEventMercCommandTrespassCombat` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6f70` (line 1539908) — **RTTI_GetClassInfo_CEventMercCommandUseAMPSuit** — class self-registration getter (calls FUN_100016b0("CEventMercCommandUseAMPSuit", parent-getter)); registers `CEventMercCommandUseAMPSuit` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6c00` (line 1539664) — **RTTI_GetClassInfo_CEventMercCommandUseVehicle** — class self-registration getter (calls FUN_100016b0("CEventMercCommandUseVehicle", parent-getter)); registers `CEventMercCommandUseVehicle` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6c30` (line 1539680) — **RTTI_GetClassInfo_CEventMercCommandUseVehicleSeat** — class self-registration getter (calls FUN_100016b0("CEventMercCommandUseVehicleSeat", parent-getter)); registers `CEventMercCommandUseVehicleSeat` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b6d20` (line 1539760) — **RTTI_GetClassInfo_CEventMercCommandVehicleStateUpdate** — class self-registration getter (calls FUN_100016b0("CEventMercCommandVehicleStateUpdate", parent-getter)); registers `CEventMercCommandVehicleStateUpdate` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109a40d0` (line 1527148) — **RTTI_GetClassInfo_CEventMercReportBarkRequest** — class self-registration getter (calls FUN_100016b0("CEventMercReportBarkRequest", parent-getter)); registers `CEventMercReportBarkRequest` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109ca650` (line 1548920) — **RTTI_GetClassInfo_CEventMercReportDied** — class self-registration getter (calls FUN_100016b0("CEventMercReportDied", parent-getter)); registers `CEventMercReportDied` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109a4220` (line 1527260) — **RTTI_GetClassInfo_CEventMercReportFinishedAttack** — class self-registration getter (calls FUN_100016b0("CEventMercReportFinishedAttack", parent-getter)); registers `CEventMercReportFinishedAttack` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109a4190` (line 1527212) — **RTTI_GetClassInfo_CEventMercReportMacheteKillEvent** — class self-registration getter (calls FUN_100016b0("CEventMercReportMacheteKillEvent", parent-getter)); registers `CEventMercReportMacheteKillEvent` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109a4160` (line 1527196) — **RTTI_GetClassInfo_CEventMercReportNeedVehicle** — class self-registration getter (calls FUN_100016b0("CEventMercReportNeedVehicle", parent-getter)); registers `CEventMercReportNeedVehicle` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109a40a0` (line 1527132) — **RTTI_GetClassInfo_CEventMercReportProjectile** — class self-registration getter (calls FUN_100016b0("CEventMercReportProjectile", parent-getter)); registers `CEventMercReportProjectile` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109a4380` (line 1527377) — **RTTI_GetClassInfo_CEventMercReportReadyForAMPSuit** — class self-registration getter (calls FUN_100016b0("CEventMercReportReadyForAMPSuit", parent-getter)); registers `CEventMercReportReadyForAMPSuit` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109a4100` (line 1527164) — **RTTI_GetClassInfo_CEventMercReportReadyForVehicle** — class self-registration getter (calls FUN_100016b0("CEventMercReportReadyForVehicle", parent-getter)); registers `CEventMercReportReadyForVehicle` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109ca620` (line 1548904) — **RTTI_GetClassInfo_CEventMercReportRenewReservation** — class self-registration getter (calls FUN_100016b0("CEventMercReportRenewReservation", parent-getter)); registers `CEventMercReportRenewReservation` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109a41f0` (line 1527244) — **RTTI_GetClassInfo_CEventMercReportSetRallyPoint** — class self-registration getter (calls FUN_100016b0("CEventMercReportSetRallyPoint", parent-getter)); registers `CEventMercReportSetRallyPoint` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109a4250` (line 1527276) — **RTTI_GetClassInfo_CEventMercReportShotAtDuringWager** — class self-registration getter (calls FUN_100016b0("CEventMercReportShotAtDuringWager", parent-getter)); registers `CEventMercReportShotAtDuringWager` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109a41c0` (line 1527228) — **RTTI_GetClassInfo_CEventMercReportSuspiciousBuilding** — class self-registration getter (calls FUN_100016b0("CEventMercReportSuspiciousBuilding", parent-getter)); registers `CEventMercReportSuspiciousBuilding` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109a4070` (line 1527116) — **RTTI_GetClassInfo_CEventMercReportThreat** — class self-registration getter (calls FUN_100016b0("CEventMercReportThreat", parent-getter)); registers `CEventMercReportThreat` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109a4130` (line 1527180) — **RTTI_GetClassInfo_CEventMercReportVehicleSTPRequest** — class self-registration getter (calls FUN_100016b0("CEventMercReportVehicleSTPRequest", parent-getter)); registers `CEventMercReportVehicleSTPRequest` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b3920` (line 1537743) — **RTTI_GetClassInfo_CEventSocialReportSeePlayerBumpedMe** — class self-registration getter (calls FUN_100016b0("CEventSocialReportSeePlayerBumpedMe", parent-getter)); registers `CEventSocialReportSeePlayerBumpedMe` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_109b3950` (line 1537759) — **RTTI_GetClassInfo_CEventSocialReportShotFired** — class self-registration getter (calls FUN_100016b0("CEventSocialReportShotFired", parent-getter)); registers `CEventSocialReportShotFired` as a subclass of `CAIEvent` in the engine RTTI/class-factory system.
- `FUN_104cbd80` (line 831962) — **RTTI_GetClassInfo_CExplosive** — class self-registration getter (calls FUN_100016b0("CExplosive", parent-getter)); registers `CExplosive` as a subclass of `CGameObject` in the engine RTTI/class-factory system.
- `FUN_105fab20` (line 999938) — **RTTI_GetClassInfo_CExplosiveEvent** — class self-registration getter (calls FUN_100016b0("CExplosiveEvent", parent-getter)); registers `CExplosiveEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_105cc9f0` (line 974249) — **RTTI_GetClassInfo_CExplosiveKillEvent** — class self-registration getter (calls FUN_100016b0("CExplosiveKillEvent", parent-getter)); registers `CExplosiveKillEvent` as a subclass of `CBaseEvent` in the engine RTTI/class-factory system.
- `FUN_106476b0` (line 1039718) — **RTTI_GetClassInfo_CFCXAIBehaviorService** — class self-registration getter (calls FUN_100016b0("CFCXAIBehaviorService", parent-getter)); registers `CFCXAIBehaviorService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_104caf80` (line 831481) — **RTTI_GetClassInfo_CFCXAIComponent** — class self-registration getter (calls FUN_100016b0("CFCXAIComponent", parent-getter)); registers `CFCXAIComponent` as a subclass of `CAIComponent` in the engine RTTI/class-factory system.
- `FUN_106d2390` (line 1117168) — **RTTI_GetClassInfo_CFCXActivatePresenceOperation** — class self-registration getter (calls FUN_100016b0("CFCXActivatePresenceOperation", parent-getter)); registers `CFCXActivatePresenceOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_105930f0` (line 944726) — **RTTI_GetClassInfo_CFCXBarkManagerService** — class self-registration getter (calls FUN_100016b0("CFCXBarkManagerService", parent-getter)); registers `CFCXBarkManagerService` as a subclass of `CBarkManagerService` in the engine RTTI/class-factory system.
- `FUN_106474a0` (line 1039622) — **RTTI_GetClassInfo_CFCXBenchmarkService** — class self-registration getter (calls FUN_100016b0("CFCXBenchmarkService", parent-getter)); registers `CFCXBenchmarkService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_10647830` (line 1039782) — **RTTI_GetClassInfo_CFCXClassService** — class self-registration getter (calls FUN_100016b0("CFCXClassService", parent-getter)); registers `CFCXClassService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_106d2480` (line 1117184) — **RTTI_GetClassInfo_CFCXClearMessageBoxManager** — class self-registration getter (calls FUN_100016b0("CFCXClearMessageBoxManager", parent-getter)); registers `CFCXClearMessageBoxManager` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_104cb0a0` (line 831561) — **RTTI_GetClassInfo_CFCXCountersComponent** — class self-registration getter (calls FUN_100016b0("CFCXCountersComponent", parent-getter)); registers `CFCXCountersComponent` as a subclass of `CCountersComponentGO` in the engine RTTI/class-factory system.
- `FUN_104cb0d0` (line 831577) — **RTTI_GetClassInfo_CFCXCountersComponentAI** — class self-registration getter (calls FUN_100016b0("CFCXCountersComponentAI", parent-getter)); registers `CFCXCountersComponentAI` as a subclass of `CFCXCountersComponent` in the engine RTTI/class-factory system.
- `FUN_104cb100` (line 831593) — **RTTI_GetClassInfo_CFCXCountersComponentAIBuddy** — class self-registration getter (calls FUN_100016b0("CFCXCountersComponentAIBuddy", parent-getter)); registers `CFCXCountersComponentAIBuddy` as a subclass of `CFCXCountersComponentAI` in the engine RTTI/class-factory system.
- `FUN_104cb260` (line 831642) — **RTTI_GetClassInfo_CFCXCountersComponentPlayer** — class self-registration getter (calls FUN_100016b0("CFCXCountersComponentPlayer", parent-getter)); registers `CFCXCountersComponentPlayer` as a subclass of `CFCXCountersComponent` in the engine RTTI/class-factory system.
- `FUN_104cb290` (line 831658) — **RTTI_GetClassInfo_CFCXCountersComponentPlayerMP** — class self-registration getter (calls FUN_100016b0("CFCXCountersComponentPlayerMP", parent-getter)); registers `CFCXCountersComponentPlayerMP` as a subclass of `CFCXCountersComponentPlayer` in the engine RTTI/class-factory system.
- `FUN_104cb2c0` (line 831674) — **RTTI_GetClassInfo_CFCXCountersComponentPlayerSP** — class self-registration getter (calls FUN_100016b0("CFCXCountersComponentPlayerSP", parent-getter)); registers `CFCXCountersComponentPlayerSP` as a subclass of `CFCXCountersComponentPlayer` in the engine RTTI/class-factory system.
- `FUN_1057fe70` (line 935511) — **RTTI_GetClassInfo_CFCXCountersService** — class self-registration getter (calls FUN_100016b0("CFCXCountersService", parent-getter)); registers `CFCXCountersService` as a subclass of `ICountersService` in the engine RTTI/class-factory system.
- `FUN_1005a3b0` (line 61421) — **RTTI_GetClassInfo_CFCXCreateGameModeOperation** — class self-registration getter (calls FUN_100016b0("CFCXCreateGameModeOperation", parent-getter)); registers `CFCXCreateGameModeOperation` as a subclass of `CGameOperationContainer` in the engine RTTI/class-factory system.
- `FUN_106dade0` (line 1121563) — **RTTI_GetClassInfo_CFCXCreateSessionOperation** — class self-registration getter (calls FUN_100016b0("CFCXCreateSessionOperation", parent-getter)); registers `CFCXCreateSessionOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d9de0` (line 1121162) — **RTTI_GetClassInfo_CFCXDeleteGameModeOperation** — class self-registration getter (calls FUN_100016b0("CFCXDeleteGameModeOperation", parent-getter)); registers `CFCXDeleteGameModeOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d2300` (line 1117136) — **RTTI_GetClassInfo_CFCXDeleteSessionOperation** — class self-registration getter (calls FUN_100016b0("CFCXDeleteSessionOperation", parent-getter)); registers `CFCXDeleteSessionOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106df080` (line 1123723) — **RTTI_GetClassInfo_CFCXGOSetUpdateFlags** — class self-registration getter (calls FUN_100016b0("CFCXGOSetUpdateFlags", parent-getter)); registers `CFCXGOSetUpdateFlags` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_107146c0` (line 1155700) — **RTTI_GetClassInfo_CFCXGRStateAdversarialLobby** — class self-registration getter (calls FUN_100016b0("CFCXGRStateAdversarialLobby", parent-getter)); registers `CFCXGRStateAdversarialLobby` as a subclass of `CGRStateAdversarialLobby` in the engine RTTI/class-factory system.
- `FUN_10709c80` (line 1150256) — **RTTI_GetClassInfo_CFCXGRStateBenchmark** — class self-registration getter (calls FUN_100016b0("CFCXGRStateBenchmark", parent-getter)); registers `CFCXGRStateBenchmark` as a subclass of `CGRState` in the engine RTTI/class-factory system.
- `FUN_10709c50` (line 1150240) — **RTTI_GetClassInfo_CFCXGRStateBenchmarkWaitForLoad** — class self-registration getter (calls FUN_100016b0("CFCXGRStateBenchmarkWaitForLoad", parent-getter)); registers `CFCXGRStateBenchmarkWaitForLoad` as a subclass of `CGRStateLoad` in the engine RTTI/class-factory system.
- `FUN_10706de0` (line 1148069) — **RTTI_GetClassInfo_CFCXGRStateCTFInRound** — class self-registration getter (calls FUN_100016b0("CFCXGRStateCTFInRound", parent-getter)); registers `CFCXGRStateCTFInRound` as a subclass of `CGRStateTeamAdversarialInRound` in the engine RTTI/class-factory system.
- `FUN_10714660` (line 1155668) — **RTTI_GetClassInfo_CFCXGRStateDeathMatchInRound** — class self-registration getter (calls FUN_100016b0("CFCXGRStateDeathMatchInRound", parent-getter)); registers `CFCXGRStateDeathMatchInRound` as a subclass of `CGRStateAdversarialInRound` in the engine RTTI/class-factory system.
- `FUN_104ca950` (line 831180) — **RTTI_GetClassInfo_CFCXGRStateMultiMenu** — class self-registration getter (calls FUN_100016b0("CFCXGRStateMultiMenu", parent-getter)); registers `CFCXGRStateMultiMenu` as a subclass of `CGRState` in the engine RTTI/class-factory system.
- `FUN_10705040` (line 1146665) — **RTTI_GetClassInfo_CFCXGRStatePostRound** — class self-registration getter (calls FUN_100016b0("CFCXGRStatePostRound", parent-getter)); registers `CFCXGRStatePostRound` as a subclass of `CGRStatePostRound` in the engine RTTI/class-factory system.
- `FUN_10704a20` (line 1146322) — **RTTI_GetClassInfo_CFCXGRStatePreRound** — class self-registration getter (calls FUN_100016b0("CFCXGRStatePreRound", parent-getter)); registers `CFCXGRStatePreRound` as a subclass of `CGRStatePreRound` in the engine RTTI/class-factory system.
- `FUN_10711760` (line 1153824) — **RTTI_GetClassInfo_CFCXGRStateSingleInGame** — class self-registration getter (calls FUN_100016b0("CFCXGRStateSingleInGame", parent-getter)); registers `CFCXGRStateSingleInGame` as a subclass of `CGRStateSingle` in the engine RTTI/class-factory system.
- `FUN_106cee70` (line 1116144) — **RTTI_GetClassInfo_CFCXGRStateSinglePreGame** — class self-registration getter (calls FUN_100016b0("CFCXGRStateSinglePreGame", parent-getter)); registers `CFCXGRStateSinglePreGame` as a subclass of `CGRStateLoad` in the engine RTTI/class-factory system.
- `FUN_107049c0` (line 1146290) — **RTTI_GetClassInfo_CFCXGRStateTeamAdversarialLobby** — class self-registration getter (calls FUN_100016b0("CFCXGRStateTeamAdversarialLobby", parent-getter)); registers `CFCXGRStateTeamAdversarialLobby` as a subclass of `CGRStateTeamAdversarialLobby` in the engine RTTI/class-factory system.
- `FUN_10707520` (line 1148398) — **RTTI_GetClassInfo_CFCXGRStateTeamDeathMatchInRound** — class self-registration getter (calls FUN_100016b0("CFCXGRStateTeamDeathMatchInRound", parent-getter)); registers `CFCXGRStateTeamDeathMatchInRound` as a subclass of `CGRStateTeamAdversarialInRound` in the engine RTTI/class-factory system.
- `FUN_10713430` (line 1154823) — **RTTI_GetClassInfo_CFCXGRStateVIPInRound** — class self-registration getter (calls FUN_100016b0("CFCXGRStateVIPInRound", parent-getter)); registers `CFCXGRStateVIPInRound` as a subclass of `CGRStateTeamAdversarialInRound` in the engine RTTI/class-factory system.
- `FUN_105d2b20` (line 978075) — **RTTI_GetClassInfo_CFCXGameMessageService** — class self-registration getter (calls FUN_100016b0("CFCXGameMessageService", parent-getter)); registers `CFCXGameMessageService` as a subclass of `CGameMessageService` in the engine RTTI/class-factory system.
- `FUN_106d9d00` (line 1121130) — **RTTI_GetClassInfo_CFCXGameModeChange** — class self-registration getter (calls FUN_100016b0("CFCXGameModeChange", parent-getter)); registers `CFCXGameModeChange` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d2240` (line 1117072) — **RTTI_GetClassInfo_CFCXGameModeInitNetworkOperation** — class self-registration getter (calls FUN_100016b0("CFCXGameModeInitNetworkOperation", parent-getter)); registers `CFCXGameModeInitNetworkOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d2270` (line 1117088) — **RTTI_GetClassInfo_CFCXGameModeShutdownNetworkOperation** — class self-registration getter (calls FUN_100016b0("CFCXGameModeShutdownNetworkOperation", parent-getter)); registers `CFCXGameModeShutdownNetworkOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_1005a320` (line 61373) — **RTTI_GetClassInfo_CFCXGameOperation** — class self-registration getter (calls FUN_100016b0("CFCXGameOperation", parent-getter)); registers `CFCXGameOperation` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_10647560` (line 1039670) — **RTTI_GetClassInfo_CFCXGameSoundService** — class self-registration getter (calls FUN_100016b0("CFCXGameSoundService", parent-getter)); registers `CFCXGameSoundService` as a subclass of `CGameSoundService` in the engine RTTI/class-factory system.
- `FUN_1005a560` (line 61533) — **RTTI_GetClassInfo_CFCXGameStartOperation** — class self-registration getter (calls FUN_100016b0("CFCXGameStartOperation", parent-getter)); registers `CFCXGameStartOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_1063c530` (line 1035912) — **RTTI_GetClassInfo_CFCXGameplayManager** — class self-registration getter (calls FUN_100016b0("CFCXGameplayManager", parent-getter)); registers `CFCXGameplayManager` as a subclass of `CGameplayManager` in the engine RTTI/class-factory system.
- `FUN_1005a4a0` (line 61469) — **RTTI_GetClassInfo_CFCXInitializeTerminalsOperation** — class self-registration getter (calls FUN_100016b0("CFCXInitializeTerminalsOperation", parent-getter)); registers `CFCXInitializeTerminalsOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d2360` (line 1117152) — **RTTI_GetClassInfo_CFCXJoinSessionOperation** — class self-registration getter (calls FUN_100016b0("CFCXJoinSessionOperation", parent-getter)); registers `CFCXJoinSessionOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d3da0` (line 1117560) — **RTTI_GetClassInfo_CFCXLoadGameOperation** — class self-registration getter (calls FUN_100016b0("CFCXLoadGameOperation", parent-getter)); registers `CFCXLoadGameOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d1cc0` (line 1116926) — **RTTI_GetClassInfo_CFCXLoadGameStartOperation** — class self-registration getter (calls FUN_100016b0("CFCXLoadGameStartOperation", parent-getter)); registers `CFCXLoadGameStartOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106eaee0` (line 1131059) — **RTTI_GetClassInfo_CFCXLoadOutItemsTransaction** — class self-registration getter (calls FUN_100016b0("CFCXLoadOutItemsTransaction", parent-getter)); registers `CFCXLoadOutItemsTransaction` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_10647500` (line 1039638) — **RTTI_GetClassInfo_CFCXLoadOutService** — class self-registration getter (calls FUN_100016b0("CFCXLoadOutService", parent-getter)); registers `CFCXLoadOutService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_106d7c10` (line 1120096) — **RTTI_GetClassInfo_CFCXLoadWorldOp** — class self-registration getter (calls FUN_100016b0("CFCXLoadWorldOp", parent-getter)); registers `CFCXLoadWorldOp` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_1005a440` (line 61437) — **RTTI_GetClassInfo_CFCXLoadWorldOperation** — class self-registration getter (calls FUN_100016b0("CFCXLoadWorldOperation", parent-getter)); registers `CFCXLoadWorldOperation` as a subclass of `CGameOperationContainer` in the engine RTTI/class-factory system.
- `FUN_10628d10` (line 1025518) — **RTTI_GetClassInfo_CFCXLoadWorldSynchOp** — class self-registration getter (calls FUN_100016b0("CFCXLoadWorldSynchOp", parent-getter)); registers `CFCXLoadWorldSynchOp` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_1005a350` (line 61389) — **RTTI_GetClassInfo_CFCXLoginOperation** — class self-registration getter (calls FUN_100016b0("CFCXLoginOperation", parent-getter)); registers `CFCXLoginOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_1057fea0` (line 935527) — **RTTI_GetClassInfo_CFCXMissionManager** — class self-registration getter (calls FUN_100016b0("CFCXMissionManager", parent-getter)); registers `CFCXMissionManager` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_106d22d0` (line 1117120) — **RTTI_GetClassInfo_CFCXNetEngineShutdownOperation** — class self-registration getter (calls FUN_100016b0("CFCXNetEngineShutdownOperation", parent-getter)); registers `CFCXNetEngineShutdownOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d22a0` (line 1117104) — **RTTI_GetClassInfo_CFCXNetEngineStartupOperation** — class self-registration getter (calls FUN_100016b0("CFCXNetEngineStartupOperation", parent-getter)); registers `CFCXNetEngineStartupOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d7d50` (line 1120128) — **RTTI_GetClassInfo_CFCXOnLoadWorldOp** — class self-registration getter (calls FUN_100016b0("CFCXOnLoadWorldOp", parent-getter)); registers `CFCXOnLoadWorldOp` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d7e30` (line 1120160) — **RTTI_GetClassInfo_CFCXOnPostLoadWorldOp** — class self-registration getter (calls FUN_100016b0("CFCXOnPostLoadWorldOp", parent-getter)); registers `CFCXOnPostLoadWorldOp` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d7ba0` (line 1120080) — **RTTI_GetClassInfo_CFCXOnPreLoadWorldOp** — class self-registration getter (calls FUN_100016b0("CFCXOnPreLoadWorldOp", parent-getter)); registers `CFCXOnPreLoadWorldOp` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106fb070` (line 1141240) — **RTTI_GetClassInfo_CFCXOnlineConversionHelper** — class self-registration getter (calls FUN_100016b0("CFCXOnlineConversionHelper", parent-getter)); registers `CFCXOnlineConversionHelper` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_10509ac0` (line 869885) — **RTTI_GetClassInfo_CFCXPlayer** — class self-registration getter (calls FUN_100016b0("CFCXPlayer", parent-getter)); registers `CFCXPlayer` as a subclass of `CPlayer` in the engine RTTI/class-factory system.
- `FUN_10509a90` (line 869869) — **RTTI_GetClassInfo_CFCXPlayerService** — class self-registration getter (calls FUN_100016b0("CFCXPlayerService", parent-getter)); registers `CFCXPlayerService` as a subclass of `CPlayerService` in the engine RTTI/class-factory system.
- `FUN_106d9d70` (line 1121146) — **RTTI_GetClassInfo_CFCXPostGameModeChange** — class self-registration getter (calls FUN_100016b0("CFCXPostGameModeChange", parent-getter)); registers `CFCXPostGameModeChange` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d7dc0` (line 1120144) — **RTTI_GetClassInfo_CFCXPostLoadWorldOp** — class self-registration getter (calls FUN_100016b0("CFCXPostLoadWorldOp", parent-getter)); registers `CFCXPostLoadWorldOp` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d4150` (line 1117688) — **RTTI_GetClassInfo_CFCXPostMetaPodTeleportOperation** — class self-registration getter (calls FUN_100016b0("CFCXPostMetaPodTeleportOperation", parent-getter)); registers `CFCXPostMetaPodTeleportOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_1053bc60` (line 899679) — **RTTI_GetClassInfo_CFCXPostReviveOperation** — class self-registration getter (calls FUN_100016b0("CFCXPostReviveOperation", parent-getter)); registers `CFCXPostReviveOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_10685cc0` (line 1077852) — **RTTI_GetClassInfo_CFCXPostSoundOperation** — class self-registration getter (calls FUN_100016b0("CFCXPostSoundOperation", parent-getter)); registers `CFCXPostSoundOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d7b30` (line 1120064) — **RTTI_GetClassInfo_CFCXPreLoadWorldOp** — class self-registration getter (calls FUN_100016b0("CFCXPreLoadWorldOp", parent-getter)); registers `CFCXPreLoadWorldOp` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_10685c90` (line 1077836) — **RTTI_GetClassInfo_CFCXPreSoundOperation** — class self-registration getter (calls FUN_100016b0("CFCXPreSoundOperation", parent-getter)); registers `CFCXPreSoundOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_1005a4d0` (line 61485) — **RTTI_GetClassInfo_CFCXPrepareLoadingScreenOperation** — class self-registration getter (calls FUN_100016b0("CFCXPrepareLoadingScreenOperation", parent-getter)); registers `CFCXPrepareLoadingScreenOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_1005a590` (line 61549) — **RTTI_GetClassInfo_CFCXPrepareRendererOperation** — class self-registration getter (calls FUN_100016b0("CFCXPrepareRendererOperation", parent-getter)); registers `CFCXPrepareRendererOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d3cf0` (line 1117544) — **RTTI_GetClassInfo_CFCXPrepareUnloadWorldOperation** — class self-registration getter (calls FUN_100016b0("CFCXPrepareUnloadWorldOperation", parent-getter)); registers `CFCXPrepareUnloadWorldOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_10647800` (line 1039766) — **RTTI_GetClassInfo_CFCXRankService** — class self-registration getter (calls FUN_100016b0("CFCXRankService", parent-getter)); registers `CFCXRankService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_10628da0` (line 1025566) — **RTTI_GetClassInfo_CFCXRemoveEntityFromListOperation** — class self-registration getter (calls FUN_100016b0("CFCXRemoveEntityFromListOperation", parent-getter)); registers `CFCXRemoveEntityFromListOperation` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_1005a530` (line 61517) — **RTTI_GetClassInfo_CFCXRunBatchFileOperation** — class self-registration getter (calls FUN_100016b0("CFCXRunBatchFileOperation", parent-getter)); registers `CFCXRunBatchFileOperation` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d3e50` (line 1117576) — **RTTI_GetClassInfo_CFCXSetGameBooting** — class self-registration getter (calls FUN_100016b0("CFCXSetGameBooting", parent-getter)); registers `CFCXSetGameBooting` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_104cbcc0` (line 831914) — **RTTI_GetClassInfo_CFCXSingleGameFilesService** — class self-registration getter (calls FUN_100016b0("CFCXSingleGameFilesService", parent-getter)); registers `CFCXSingleGameFilesService` as a subclass of `CGameFilesService` in the engine RTTI/class-factory system.
- `FUN_10628d70` (line 1025550) — **RTTI_GetClassInfo_CFCXSkipFramesOperation** — class self-registration getter (calls FUN_100016b0("CFCXSkipFramesOperation", parent-getter)); registers `CFCXSkipFramesOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106df0f0` (line 1123739) — **RTTI_GetClassInfo_CFCXStartEditor** — class self-registration getter (calls FUN_100016b0("CFCXStartEditor", parent-getter)); registers `CFCXStartEditor` as a subclass of `CGameOperationContainer` in the engine RTTI/class-factory system.
- `FUN_106dadb0` (line 1121547) — **RTTI_GetClassInfo_CFCXStartNetworkOperation** — class self-registration getter (calls FUN_100016b0("CFCXStartNetworkOperation", parent-getter)); registers `CFCXStartNetworkOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106df120` (line 1123755) — **RTTI_GetClassInfo_CFCXStopEditor** — class self-registration getter (calls FUN_100016b0("CFCXStopEditor", parent-getter)); registers `CFCXStopEditor` as a subclass of `CGameOperationContainer` in the engine RTTI/class-factory system.
- `FUN_10628d40` (line 1025534) — **RTTI_GetClassInfo_CFCXTeleportEntityOperation** — class self-registration getter (calls FUN_100016b0("CFCXTeleportEntityOperation", parent-getter)); registers `CFCXTeleportEntityOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_1005a500` (line 61501) — **RTTI_GetClassInfo_CFCXUnloadLoadingScreenOperation** — class self-registration getter (calls FUN_100016b0("CFCXUnloadLoadingScreenOperation", parent-getter)); registers `CFCXUnloadLoadingScreenOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_1005a470` (line 61453) — **RTTI_GetClassInfo_CFCXUnloadWorldOperation** — class self-registration getter (calls FUN_100016b0("CFCXUnloadWorldOperation", parent-getter)); registers `CFCXUnloadWorldOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d3ec0` (line 1117592) — **RTTI_GetClassInfo_CFCXUnsetGameBooting** — class self-registration getter (calls FUN_100016b0("CFCXUnsetGameBooting", parent-getter)); registers `CFCXUnsetGameBooting` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_104ca530` (line 830940) — **RTTI_GetClassInfo_CFCXWeapon** — class self-registration getter (calls FUN_100016b0("CFCXWeapon", parent-getter)); registers `CFCXWeapon` as a subclass of `CWeapon` in the engine RTTI/class-factory system.
- `FUN_105cc6b0` (line 974127) — **RTTI_GetClassInfo_CFCXWeaponsService** — class self-registration getter (calls FUN_100016b0("CFCXWeaponsService", parent-getter)); registers `CFCXWeaponsService` as a subclass of `CWeaponsService` in the engine RTTI/class-factory system.
- `FUN_106d7f20` (line 1120176) — **RTTI_GetClassInfo_CFCXWorldReadyOperation** — class self-registration getter (calls FUN_100016b0("CFCXWorldReadyOperation", parent-getter)); registers `CFCXWorldReadyOperation` as a subclass of `CFCXGameOperation` in the engine RTTI/class-factory system.
- `FUN_103178a0` (line 537965) — **RTTI_GetClassInfo_CFaceActorResource** — class self-registration getter (calls FUN_100016b0("CFaceActorResource", parent-getter)); registers `CFaceActorResource` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_10317870` (line 537949) — **RTTI_GetClassInfo_CFaceAnimResource** — class self-registration getter (calls FUN_100016b0("CFaceAnimResource", parent-getter)); registers `CFaceAnimResource` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_109d51d0` (line 1555743) — **RTTI_GetClassInfo_CFcxAIEventDesertChange** — class self-registration getter (calls FUN_100016b0("CFcxAIEventDesertChange", parent-getter)); registers `CFcxAIEventDesertChange` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_101a68f0` (line 292523) — **RTTI_GetClassInfo_CFileDescriptorComponent** — class self-registration getter (calls FUN_100016b0("CFileDescriptorComponent", parent-getter)); registers `CFileDescriptorComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a6920` (line 292539) — **RTTI_GetClassInfo_CFileDescriptorRuntimeComponent** — class self-registration getter (calls FUN_100016b0("CFileDescriptorRuntimeComponent", parent-getter)); registers `CFileDescriptorRuntimeComponent` as a subclass of `CFileDescriptorComponent` in the engine RTTI/class-factory system.
- `FUN_104cb3e0` (line 831706) — **RTTI_GetClassInfo_CFireComponent** — class self-registration getter (calls FUN_100016b0("CFireComponent", parent-getter)); registers `CFireComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104cb410` (line 831722) — **RTTI_GetClassInfo_CFireObjectComponent** — class self-registration getter (calls FUN_100016b0("CFireObjectComponent", parent-getter)); registers `CFireObjectComponent` as a subclass of `CFireComponent` in the engine RTTI/class-factory system.
- `FUN_104cb4d0` (line 831738) — **RTTI_GetClassInfo_CFireRegionComponent** — class self-registration getter (calls FUN_100016b0("CFireRegionComponent", parent-getter)); registers `CFireRegionComponent` as a subclass of `CFireComponent` in the engine RTTI/class-factory system.
- `FUN_105e46e0` (line 987451) — **RTTI_GetClassInfo_CFireStartedEvent** — class self-registration getter (calls FUN_100016b0("CFireStartedEvent", parent-getter)); registers `CFireStartedEvent` as a subclass of `CBaseEvent` in the engine RTTI/class-factory system.
- `FUN_104cb500` (line 831754) — **RTTI_GetClassInfo_CFireStickyStreamComponent** — class self-registration getter (calls FUN_100016b0("CFireStickyStreamComponent", parent-getter)); registers `CFireStickyStreamComponent` as a subclass of `CFireComponent` in the engine RTTI/class-factory system.
- `FUN_104c9560` (line 830298) — **RTTI_GetClassInfo_CFlag** — class self-registration getter (calls FUN_100016b0("CFlag", parent-getter)); registers `CFlag` as a subclass of `CGameObject` in the engine RTTI/class-factory system.
- `FUN_1050cd20` (line 871980) — **RTTI_GetClassInfo_CFlagMemento** — class self-registration getter (calls FUN_100016b0("CFlagMemento", parent-getter)); registers `CFlagMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_104ca8c0` (line 831148) — **RTTI_GetClassInfo_CFlagStation** — class self-registration getter (calls FUN_100016b0("CFlagStation", parent-getter)); registers `CFlagStation` as a subclass of `CGameObject` in the engine RTTI/class-factory system.
- `FUN_104ca8f0` (line 831164) — **RTTI_GetClassInfo_CFlagStationNetworkComponent** — class self-registration getter (calls FUN_100016b0("CFlagStationNetworkComponent", parent-getter)); registers `CFlagStationNetworkComponent` as a subclass of `CNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_1097f090` (line 1501282) — **RTTI_GetClassInfo_CFlyingAnimalPersonality** — class self-registration getter (calls FUN_100016b0("CFlyingAnimalPersonality", parent-getter)); registers `CFlyingAnimalPersonality` as a subclass of `CLivingCreature` in the engine RTTI/class-factory system.
- `FUN_10644b10` (line 1038881) — **RTTI_GetClassInfo_CFrankensteinComponent** — class self-registration getter (calls FUN_100016b0("CFrankensteinComponent", parent-getter)); registers `CFrankensteinComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_10317840` (line 537933) — **RTTI_GetClassInfo_CFrankensteinPoseResource** — class self-registration getter (calls FUN_100016b0("CFrankensteinPoseResource", parent-getter)); registers `CFrankensteinPoseResource` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_108a5d90` (line 1390352) — **RTTI_GetClassInfo_CFriendListService** — class self-registration getter (calls FUN_100016b0("CFriendListService", parent-getter)); registers `CFriendListService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1063bf50` (line 1035674) — **RTTI_GetClassInfo_CFullScreenVideoOperation** — class self-registration getter (calls FUN_100016b0("CFullScreenVideoOperation", parent-getter)); registers `CFullScreenVideoOperation` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_100c8d20` (line 143871) — **RTTI_GetClassInfo_CGOExternalState** — class self-registration getter (calls FUN_100016b0("CGOExternalState", parent-getter)); registers `CGOExternalState` as a subclass of `CGOState` in the engine RTTI/class-factory system.
- `FUN_100c8cf0` (line 143855) — **RTTI_GetClassInfo_CGOState** — class self-registration getter (calls FUN_100016b0("CGOState", parent-getter)); registers `CGOState` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_1062fac0` (line 1029518) — **RTTI_GetClassInfo_CGOStateEvent** — class self-registration getter (calls FUN_100016b0("CGOStateEvent", parent-getter)); registers `CGOStateEvent` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_10641690` (line 1037908) — **RTTI_GetClassInfo_CGOStateEventEquipment** — class self-registration getter (calls FUN_100016b0("CGOStateEventEquipment", parent-getter)); registers `CGOStateEventEquipment` as a subclass of `CGOStateEvent` in the engine RTTI/class-factory system.
- `FUN_1084efb0` (line 1342401) — **RTTI_GetClassInfo_CGRAmmoPilesRespawn** — class self-registration getter (calls FUN_100016b0("CGRAmmoPilesRespawn", parent-getter)); registers `CGRAmmoPilesRespawn` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_107e5b40` (line 1275926) — **RTTI_GetClassInfo_CGRAmmoPilesSpawnProjectiles** — class self-registration getter (calls FUN_100016b0("CGRAmmoPilesSpawnProjectiles", parent-getter)); registers `CGRAmmoPilesSpawnProjectiles` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_105cf840` (line 976206) — **RTTI_GetClassInfo_CGRCanBackstab** — class self-registration getter (calls FUN_100016b0("CGRCanBackstab", parent-getter)); registers `CGRCanBackstab` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_106ceed0` (line 1116176) — **RTTI_GetClassInfo_CGRCanRemoveInventoryEntities** — class self-registration getter (calls FUN_100016b0("CGRCanRemoveInventoryEntities", parent-getter)); registers `CGRCanRemoveInventoryEntities` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1082faf0` (line 1321732) — **RTTI_GetClassInfo_CGRCanStab** — class self-registration getter (calls FUN_100016b0("CGRCanStab", parent-getter)); registers `CGRCanStab` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10741e00` (line 1179251) — **RTTI_GetClassInfo_CGRDropInventoryWhenRagdoll** — class self-registration getter (calls FUN_100016b0("CGRDropInventoryWhenRagdoll", parent-getter)); registers `CGRDropInventoryWhenRagdoll` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1005aaa0` (line 61756) — **RTTI_GetClassInfo_CGREvent** — class self-registration getter (calls FUN_100016b0("CGREvent", parent-getter)); registers `CGREvent` as a subclass of `CCommandCBParam` in the engine RTTI/class-factory system.
- `FUN_1023ada0` (line 395392) — **RTTI_GetClassInfo_CGREventEndGameStatsReceived** — class self-registration getter (calls FUN_100016b0("CGREventEndGameStatsReceived", parent-getter)); registers `CGREventEndGameStatsReceived` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_10509990` (line 869781) — **RTTI_GetClassInfo_CGREventFlagPickedUp** — class self-registration getter (calls FUN_100016b0("CGREventFlagPickedUp", parent-getter)); registers `CGREventFlagPickedUp` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1059e680` (line 951670) — **RTTI_GetClassInfo_CGREventFlagScore** — class self-registration getter (calls FUN_100016b0("CGREventFlagScore", parent-getter)); registers `CGREventFlagScore` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1059e610` (line 951634) — **RTTI_GetClassInfo_CGREventFlagStolen** — class self-registration getter (calls FUN_100016b0("CGREventFlagStolen", parent-getter)); registers `CGREventFlagStolen` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_105099c0` (line 869797) — **RTTI_GetClassInfo_CGREventFlagTimedOut** — class self-registration getter (calls FUN_100016b0("CGREventFlagTimedOut", parent-getter)); registers `CGREventFlagTimedOut` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1052a790` (line 888852) — **RTTI_GetClassInfo_CGREventOnAnimalKill** — class self-registration getter (calls FUN_100016b0("CGREventOnAnimalKill", parent-getter)); registers `CGREventOnAnimalKill` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_106435b0` (line 1038239) — **RTTI_GetClassInfo_CGREventOnDropFlag** — class self-registration getter (calls FUN_100016b0("CGREventOnDropFlag", parent-getter)); registers `CGREventOnDropFlag` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1076a120` (line 1201534) — **RTTI_GetClassInfo_CGREventOnEntityReady** — class self-registration getter (calls FUN_100016b0("CGREventOnEntityReady", parent-getter)); registers `CGREventOnEntityReady` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1056b7b0` (line 924419) — **RTTI_GetClassInfo_CGREventOnExtractionTrigger** — class self-registration getter (calls FUN_100016b0("CGREventOnExtractionTrigger", parent-getter)); registers `CGREventOnExtractionTrigger` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1056c030` (line 924743) — **RTTI_GetClassInfo_CGREventOnExtractionTriggerNotFirstTime** — class self-registration getter (calls FUN_100016b0("CGREventOnExtractionTriggerNotFirstTime", parent-getter)); registers `CGREventOnExtractionTriggerNotFirstTime` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1051e5e0` (line 881897) — **RTTI_GetClassInfo_CGREventOnKill** — class self-registration getter (calls FUN_100016b0("CGREventOnKill", parent-getter)); registers `CGREventOnKill` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_105d29b0` (line 977990) — **RTTI_GetClassInfo_CGREventOnOutOfWorld** — class self-registration getter (calls FUN_100016b0("CGREventOnOutOfWorld", parent-getter)); registers `CGREventOnOutOfWorld` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1071fcc0` (line 1161945) — **RTTI_GetClassInfo_CGREventOnPawnDied** — class self-registration getter (calls FUN_100016b0("CGREventOnPawnDied", parent-getter)); registers `CGREventOnPawnDied` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_107252f0` (line 1164942) — **RTTI_GetClassInfo_CGREventOnPawnDown** — class self-registration getter (calls FUN_100016b0("CGREventOnPawnDown", parent-getter)); registers `CGREventOnPawnDown` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1005ab00` (line 61788) — **RTTI_GetClassInfo_CGREventOnPawnReady** — class self-registration getter (calls FUN_100016b0("CGREventOnPawnReady", parent-getter)); registers `CGREventOnPawnReady` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_105a33f0` (line 953922) — **RTTI_GetClassInfo_CGREventOnPlayerEnterCaptureCircle** — class self-registration getter (calls FUN_100016b0("CGREventOnPlayerEnterCaptureCircle", parent-getter)); registers `CGREventOnPlayerEnterCaptureCircle` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_105a3420` (line 953938) — **RTTI_GetClassInfo_CGREventOnPlayerExitCaptureCircle** — class self-registration getter (calls FUN_100016b0("CGREventOnPlayerExitCaptureCircle", parent-getter)); registers `CGREventOnPlayerExitCaptureCircle` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_105a5000` (line 954866) — **RTTI_GetClassInfo_CGREventOnPointCaptured** — class self-registration getter (calls FUN_100016b0("CGREventOnPointCaptured", parent-getter)); registers `CGREventOnPointCaptured` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_10850390` (line 1343185) — **RTTI_GetClassInfo_CGREventOnQuitMatch** — class self-registration getter (calls FUN_100016b0("CGREventOnQuitMatch", parent-getter)); registers `CGREventOnQuitMatch` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1052c670` (line 890033) — **RTTI_GetClassInfo_CGREventOnRepairableDamageImpact** — class self-registration getter (calls FUN_100016b0("CGREventOnRepairableDamageImpact", parent-getter)); registers `CGREventOnRepairableDamageImpact` as a subclass of `CGREventOnRepairableObject` in the engine RTTI/class-factory system.
- `FUN_1052c350` (line 889823) — **RTTI_GetClassInfo_CGREventOnRepairableObject** — class self-registration getter (calls FUN_100016b0("CGREventOnRepairableObject", parent-getter)); registers `CGREventOnRepairableObject` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1052c460` (line 889911) — **RTTI_GetClassInfo_CGREventOnRepairableObjectDamaged** — class self-registration getter (calls FUN_100016b0("CGREventOnRepairableObjectDamaged", parent-getter)); registers `CGREventOnRepairableObjectDamaged` as a subclass of `CGREventOnRepairableObject` in the engine RTTI/class-factory system.
- `FUN_1052c430` (line 889895) — **RTTI_GetClassInfo_CGREventOnRepairableObjectDestroyed** — class self-registration getter (calls FUN_100016b0("CGREventOnRepairableObjectDestroyed", parent-getter)); registers `CGREventOnRepairableObjectDestroyed` as a subclass of `CGREventOnRepairableObject` in the engine RTTI/class-factory system.
- `FUN_1052c4e0` (line 889948) — **RTTI_GetClassInfo_CGREventOnRepairableObjectFixed** — class self-registration getter (calls FUN_100016b0("CGREventOnRepairableObjectFixed", parent-getter)); registers `CGREventOnRepairableObjectFixed` as a subclass of `CGREventOnRepairableObject` in the engine RTTI/class-factory system.
- `FUN_1052c3c0` (line 889859) — **RTTI_GetClassInfo_CGREventOnRepairableObjectRepaired** — class self-registration getter (calls FUN_100016b0("CGREventOnRepairableObjectRepaired", parent-getter)); registers `CGREventOnRepairableObjectRepaired` as a subclass of `CGREventOnRepairableObject` in the engine RTTI/class-factory system.
- `FUN_10725320` (line 1164958) — **RTTI_GetClassInfo_CGREventOnRequestChangeTeamCaptain** — class self-registration getter (calls FUN_100016b0("CGREventOnRequestChangeTeamCaptain", parent-getter)); registers `CGREventOnRequestChangeTeamCaptain` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_106f00a0` (line 1134740) — **RTTI_GetClassInfo_CGREventOnRequestEndMatch** — class self-registration getter (calls FUN_100016b0("CGREventOnRequestEndMatch", parent-getter)); registers `CGREventOnRequestEndMatch` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_106f0100` (line 1134772) — **RTTI_GetClassInfo_CGREventOnRequestExtendMatch** — class self-registration getter (calls FUN_100016b0("CGREventOnRequestExtendMatch", parent-getter)); registers `CGREventOnRequestExtendMatch` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_106f00d0` (line 1134756) — **RTTI_GetClassInfo_CGREventOnRequestRestartMatch** — class self-registration getter (calls FUN_100016b0("CGREventOnRequestRestartMatch", parent-getter)); registers `CGREventOnRequestRestartMatch` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_106f0130` (line 1134788) — **RTTI_GetClassInfo_CGREventOnRequestSkipMap** — class self-registration getter (calls FUN_100016b0("CGREventOnRequestSkipMap", parent-getter)); registers `CGREventOnRequestSkipMap` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1084c5c0` (line 1340480) — **RTTI_GetClassInfo_CGREventOnRequestStartMatch** — class self-registration getter (calls FUN_100016b0("CGREventOnRequestStartMatch", parent-getter)); registers `CGREventOnRequestStartMatch` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1075f3f0` (line 1195629) — **RTTI_GetClassInfo_CGREventOnRequestTeamChange** — class self-registration getter (calls FUN_100016b0("CGREventOnRequestTeamChange", parent-getter)); registers `CGREventOnRequestTeamChange` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1071b9a0` (line 1160080) — **RTTI_GetClassInfo_CGREventOnRevive** — class self-registration getter (calls FUN_100016b0("CGREventOnRevive", parent-getter)); registers `CGREventOnRevive` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_107151f0` (line 1156112) — **RTTI_GetClassInfo_CGREventOnSpawnPlayer** — class self-registration getter (calls FUN_100016b0("CGREventOnSpawnPlayer", parent-getter)); registers `CGREventOnSpawnPlayer` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_10643580` (line 1038223) — **RTTI_GetClassInfo_CGREventOnTryDropFlag** — class self-registration getter (calls FUN_100016b0("CGREventOnTryDropFlag", parent-getter)); registers `CGREventOnTryDropFlag` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_10635b90` (line 1032804) — **RTTI_GetClassInfo_CGREventRequestDisplayLoadOut** — class self-registration getter (calls FUN_100016b0("CGREventRequestDisplayLoadOut", parent-getter)); registers `CGREventRequestDisplayLoadOut` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_108503c0` (line 1343201) — **RTTI_GetClassInfo_CGREventRequestDisplayPauseMulti** — class self-registration getter (calls FUN_100016b0("CGREventRequestDisplayPauseMulti", parent-getter)); registers `CGREventRequestDisplayPauseMulti` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_10635bf0` (line 1032820) — **RTTI_GetClassInfo_CGREventRequestHideLoadOut** — class self-registration getter (calls FUN_100016b0("CGREventRequestHideLoadOut", parent-getter)); registers `CGREventRequestHideLoadOut` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1071fd50` (line 1161993) — **RTTI_GetClassInfo_CGREventSkillRingMode** — class self-registration getter (calls FUN_100016b0("CGREventSkillRingMode", parent-getter)); registers `CGREventSkillRingMode` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1005aad0` (line 61772) — **RTTI_GetClassInfo_CGRGenericEvent** — class self-registration getter (calls FUN_100016b0("CGRGenericEvent", parent-getter)); registers `CGRGenericEvent` as a subclass of `CGREvent` in the engine RTTI/class-factory system.
- `FUN_1071e200` (line 1161114) — **RTTI_GetClassInfo_CGRQueryCanCallVote** — class self-registration getter (calls FUN_100016b0("CGRQueryCanCallVote", parent-getter)); registers `CGRQueryCanCallVote` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1071e260` (line 1161146) — **RTTI_GetClassInfo_CGRQueryCanCapturePoint** — class self-registration getter (calls FUN_100016b0("CGRQueryCanCapturePoint", parent-getter)); registers `CGRQueryCanCapturePoint` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10855940` (line 1346668) — **RTTI_GetClassInfo_CGRQueryCanChangeTeam** — class self-registration getter (calls FUN_100016b0("CGRQueryCanChangeTeam", parent-getter)); registers `CGRQueryCanChangeTeam` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1059e730` (line 951728) — **RTTI_GetClassInfo_CGRQueryCanDepositFlag** — class self-registration getter (calls FUN_100016b0("CGRQueryCanDepositFlag", parent-getter)); registers `CGRQueryCanDepositFlag` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1062fe20` (line 1029693) — **RTTI_GetClassInfo_CGRQueryCanDoDamage** — class self-registration getter (calls FUN_100016b0("CGRQueryCanDoDamage", parent-getter)); registers `CGRQueryCanDoDamage` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_106c25d0` (line 1108934) — **RTTI_GetClassInfo_CGRQueryCanJamEquipment** — class self-registration getter (calls FUN_100016b0("CGRQueryCanJamEquipment", parent-getter)); registers `CGRQueryCanJamEquipment` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_105cf810` (line 976190) — **RTTI_GetClassInfo_CGRQueryCanModifyHealth** — class self-registration getter (calls FUN_100016b0("CGRQueryCanModifyHealth", parent-getter)); registers `CGRQueryCanModifyHealth` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_105099f0` (line 869813) — **RTTI_GetClassInfo_CGRQueryCanPickUpFlag** — class self-registration getter (calls FUN_100016b0("CGRQueryCanPickUpFlag", parent-getter)); registers `CGRQueryCanPickUpFlag` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10717b70` (line 1157338) — **RTTI_GetClassInfo_CGRQueryCanPlayerRequestDisplayLoadOut** — class self-registration getter (calls FUN_100016b0("CGRQueryCanPlayerRequestDisplayLoadOut", parent-getter)); registers `CGRQueryCanPlayerRequestDisplayLoadOut` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10717ba0` (line 1157354) — **RTTI_GetClassInfo_CGRQueryCanPlayerRequestHideLoadOut** — class self-registration getter (calls FUN_100016b0("CGRQueryCanPlayerRequestHideLoadOut", parent-getter)); registers `CGRQueryCanPlayerRequestHideLoadOut` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_108161a0` (line 1306010) — **RTTI_GetClassInfo_CGRQueryCanRevive** — class self-registration getter (calls FUN_100016b0("CGRQueryCanRevive", parent-getter)); registers `CGRQueryCanRevive` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1059e6b0` (line 951686) — **RTTI_GetClassInfo_CGRQueryCanTakeFlag** — class self-registration getter (calls FUN_100016b0("CGRQueryCanTakeFlag", parent-getter)); registers `CGRQueryCanTakeFlag` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1076a150` (line 1201550) — **RTTI_GetClassInfo_CGRQueryCanVoiceChat** — class self-registration getter (calls FUN_100016b0("CGRQueryCanVoiceChat", parent-getter)); registers `CGRQueryCanVoiceChat` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10723310` (line 1164022) — **RTTI_GetClassInfo_CGRQueryDisplayAccountErrors** — class self-registration getter (calls FUN_100016b0("CGRQueryDisplayAccountErrors", parent-getter)); registers `CGRQueryDisplayAccountErrors` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_106cef00` (line 1116192) — **RTTI_GetClassInfo_CGRQueryDisplayConfirmDestructiveAction** — class self-registration getter (calls FUN_100016b0("CGRQueryDisplayConfirmDestructiveAction", parent-getter)); registers `CGRQueryDisplayConfirmDestructiveAction` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10723340` (line 1164038) — **RTTI_GetClassInfo_CGRQueryDisplayEthernetLinkError** — class self-registration getter (calls FUN_100016b0("CGRQueryDisplayEthernetLinkError", parent-getter)); registers `CGRQueryDisplayEthernetLinkError` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1071fd20` (line 1161977) — **RTTI_GetClassInfo_CGRQueryFlagTimer** — class self-registration getter (calls FUN_100016b0("CGRQueryFlagTimer", parent-getter)); registers `CGRQueryFlagTimer` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10704fc0` (line 1146633) — **RTTI_GetClassInfo_CGRQueryGetBases** — class self-registration getter (calls FUN_100016b0("CGRQueryGetBases", parent-getter)); registers `CGRQueryGetBases` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10705e20` (line 1147267) — **RTTI_GetClassInfo_CGRQueryGetCapturePoints** — class self-registration getter (calls FUN_100016b0("CGRQueryGetCapturePoints", parent-getter)); registers `CGRQueryGetCapturePoints` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10706db0` (line 1148053) — **RTTI_GetClassInfo_CGRQueryGetFlagStations** — class self-registration getter (calls FUN_100016b0("CGRQueryGetFlagStations", parent-getter)); registers `CGRQueryGetFlagStations` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10723940` (line 1164257) — **RTTI_GetClassInfo_CGRQueryGetMenuContext** — class self-registration getter (calls FUN_100016b0("CGRQueryGetMenuContext", parent-getter)); registers `CGRQueryGetMenuContext` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1084dc20` (line 1341610) — **RTTI_GetClassInfo_CGRQueryGetPickupPiles** — class self-registration getter (calls FUN_100016b0("CGRQueryGetPickupPiles", parent-getter)); registers `CGRQueryGetPickupPiles` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10850420` (line 1343233) — **RTTI_GetClassInfo_CGRQueryGetPlayerRespawnTime** — class self-registration getter (calls FUN_100016b0("CGRQueryGetPlayerRespawnTime", parent-getter)); registers `CGRQueryGetPlayerRespawnTime` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_101e1ce0` (line 337024) — **RTTI_GetClassInfo_CGRQueryGetStateTimeLeft** — class self-registration getter (calls FUN_100016b0("CGRQueryGetStateTimeLeft", parent-getter)); registers `CGRQueryGetStateTimeLeft` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1071e230` (line 1161130) — **RTTI_GetClassInfo_CGRQueryGetTeamScore** — class self-registration getter (calls FUN_100016b0("CGRQueryGetTeamScore", parent-getter)); registers `CGRQueryGetTeamScore` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_108503f0` (line 1343217) — **RTTI_GetClassInfo_CGRQueryGetWaveRespawnTime** — class self-registration getter (calls FUN_100016b0("CGRQueryGetWaveRespawnTime", parent-getter)); registers `CGRQueryGetWaveRespawnTime` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1071fcf0` (line 1161961) — **RTTI_GetClassInfo_CGRQueryHasFlag** — class self-registration getter (calls FUN_100016b0("CGRQueryHasFlag", parent-getter)); registers `CGRQueryHasFlag` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10509a60` (line 869853) — **RTTI_GetClassInfo_CGRQueryHasFlagTimedOut** — class self-registration getter (calls FUN_100016b0("CGRQueryHasFlagTimedOut", parent-getter)); registers `CGRQueryHasFlagTimedOut` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_106eae50` (line 1131027) — **RTTI_GetClassInfo_CGRQueryIsDefaultEquipmentCategory** — class self-registration getter (calls FUN_100016b0("CGRQueryIsDefaultEquipmentCategory", parent-getter)); registers `CGRQueryIsDefaultEquipmentCategory` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1051bb70` (line 880856) — **RTTI_GetClassInfo_CGRQueryIsDodgeBlocked** — class self-registration getter (calls FUN_100016b0("CGRQueryIsDodgeBlocked", parent-getter)); registers `CGRQueryIsDodgeBlocked` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10001aa0` (line 690) — **RTTI_GetClassInfo_CGRQueryIsGameInLobby** — class self-registration getter (calls FUN_100016b0("CGRQueryIsGameInLobby", parent-getter)); registers `CGRQueryIsGameInLobby` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_107098a0` (line 1150143) — **RTTI_GetClassInfo_CGRQueryIsGameInMainMenu** — class self-registration getter (calls FUN_100016b0("CGRQueryIsGameInMainMenu", parent-getter)); registers `CGRQueryIsGameInMainMenu` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1084c5f0` (line 1340496) — **RTTI_GetClassInfo_CGRQueryIsGameInPostRound** — class self-registration getter (calls FUN_100016b0("CGRQueryIsGameInPostRound", parent-getter)); registers `CGRQueryIsGameInPostRound` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_106f0210` (line 1134850) — **RTTI_GetClassInfo_CGRQueryIsGameInPreRound** — class self-registration getter (calls FUN_100016b0("CGRQueryIsGameInPreRound", parent-getter)); registers `CGRQueryIsGameInPreRound` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_100428a0` (line 44355) — **RTTI_GetClassInfo_CGRQueryIsGameInProgress** — class self-registration getter (calls FUN_100016b0("CGRQueryIsGameInProgress", parent-getter)); registers `CGRQueryIsGameInProgress` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1071b120` (line 1159805) — **RTTI_GetClassInfo_CGRQueryIsInteractivePopupAllowed** — class self-registration getter (calls FUN_100016b0("CGRQueryIsInteractivePopupAllowed", parent-getter)); registers `CGRQueryIsInteractivePopupAllowed` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10704a80` (line 1146354) — **RTTI_GetClassInfo_CGRQueryIsLoadOutDisplayed** — class self-registration getter (calls FUN_100016b0("CGRQueryIsLoadOutDisplayed", parent-getter)); registers `CGRQueryIsLoadOutDisplayed` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_105d29e0` (line 978006) — **RTTI_GetClassInfo_CGRQueryIsReviveEnabled** — class self-registration getter (calls FUN_100016b0("CGRQueryIsReviveEnabled", parent-getter)); registers `CGRQueryIsReviveEnabled` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10719d10` (line 1159054) — **RTTI_GetClassInfo_CGRQueryIsSuicide** — class self-registration getter (calls FUN_100016b0("CGRQueryIsSuicide", parent-getter)); registers `CGRQueryIsSuicide` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_106f0240` (line 1134866) — **RTTI_GetClassInfo_CGRQueryIsTeamBasedMode** — class self-registration getter (calls FUN_100016b0("CGRQueryIsTeamBasedMode", parent-getter)); registers `CGRQueryIsTeamBasedMode` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_104efba0` (line 854266) — **RTTI_GetClassInfo_CGRQueryIsVehicleAccessBlocked** — class self-registration getter (calls FUN_100016b0("CGRQueryIsVehicleAccessBlocked", parent-getter)); registers `CGRQueryIsVehicleAccessBlocked` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10725350` (line 1164974) — **RTTI_GetClassInfo_CGRQueryIsWaitingForRevive** — class self-registration getter (calls FUN_100016b0("CGRQueryIsWaitingForRevive", parent-getter)); registers `CGRQueryIsWaitingForRevive` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1076a180` (line 1201566) — **RTTI_GetClassInfo_CGRQueryIsWorldNeeded** — class self-registration getter (calls FUN_100016b0("CGRQueryIsWorldNeeded", parent-getter)); registers `CGRQueryIsWorldNeeded` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1060df50` (line 1009583) — **RTTI_GetClassInfo_CGRQueryIsaVIPPlayer** — class self-registration getter (calls FUN_100016b0("CGRQueryIsaVIPPlayer", parent-getter)); registers `CGRQueryIsaVIPPlayer` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_107842e0` (line 1219048) — **RTTI_GetClassInfo_CGRQueryJoinAsSpectator** — class self-registration getter (calls FUN_100016b0("CGRQueryJoinAsSpectator", parent-getter)); registers `CGRQueryJoinAsSpectator` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10001a60` (line 671) — **RTTI_GetClassInfo_CGRQueryParams** — class self-registration getter (calls FUN_100016b0("CGRQueryParams", parent-getter)); registers `CGRQueryParams` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_106ceea0` (line 1116160) — **RTTI_GetClassInfo_CGRQuerySystemPresence** — class self-registration getter (calls FUN_100016b0("CGRQuerySystemPresence", parent-getter)); registers `CGRQuerySystemPresence` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_10644ae0` (line 1038865) — **RTTI_GetClassInfo_CGRQueryWaitForRevive** — class self-registration getter (calls FUN_100016b0("CGRQueryWaitForRevive", parent-getter)); registers `CGRQueryWaitForRevive` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_1005a950` (line 61653) — **RTTI_GetClassInfo_CGRState** — class self-registration getter (calls FUN_100016b0("CGRState", parent-getter)); registers `CGRState` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_107048d0` (line 1146210) — **RTTI_GetClassInfo_CGRStateAdversarial** — class self-registration getter (calls FUN_100016b0("CGRStateAdversarial", parent-getter)); registers `CGRStateAdversarial` as a subclass of `CGRState` in the engine RTTI/class-factory system.
- `FUN_10714630` (line 1155652) — **RTTI_GetClassInfo_CGRStateAdversarialInRound** — class self-registration getter (calls FUN_100016b0("CGRStateAdversarialInRound", parent-getter)); registers `CGRStateAdversarialInRound` as a subclass of `CGRStateAdversarial` in the engine RTTI/class-factory system.
- `FUN_10714690` (line 1155684) — **RTTI_GetClassInfo_CGRStateAdversarialLobby** — class self-registration getter (calls FUN_100016b0("CGRStateAdversarialLobby", parent-getter)); registers `CGRStateAdversarialLobby` as a subclass of `CGRState` in the engine RTTI/class-factory system.
- `FUN_101e11d0` (line 336441) — **RTTI_GetClassInfo_CGRStateIdle** — class self-registration getter (calls FUN_100016b0("CGRStateIdle", parent-getter)); registers `CGRStateIdle` as a subclass of `CGRState` in the engine RTTI/class-factory system.
- `FUN_1005aa70` (line 61740) — **RTTI_GetClassInfo_CGRStateLoad** — class self-registration getter (calls FUN_100016b0("CGRStateLoad", parent-getter)); registers `CGRStateLoad` as a subclass of `CGRState` in the engine RTTI/class-factory system.
- `FUN_107047c0` (line 1146149) — **RTTI_GetClassInfo_CGRStateLoadPlayer** — class self-registration getter (calls FUN_100016b0("CGRStateLoadPlayer", parent-getter)); registers `CGRStateLoadPlayer` as a subclass of `CGRStateLoad` in the engine RTTI/class-factory system.
- `FUN_107047f0` (line 1146165) — **RTTI_GetClassInfo_CGRStateLoadWorld** — class self-registration getter (calls FUN_100016b0("CGRStateLoadWorld", parent-getter)); registers `CGRStateLoadWorld` as a subclass of `CGRStateLoad` in the engine RTTI/class-factory system.
- `FUN_10704a50` (line 1146338) — **RTTI_GetClassInfo_CGRStatePostRound** — class self-registration getter (calls FUN_100016b0("CGRStatePostRound", parent-getter)); registers `CGRStatePostRound` as a subclass of `CGRState` in the engine RTTI/class-factory system.
- `FUN_107049f0` (line 1146306) — **RTTI_GetClassInfo_CGRStatePreRound** — class self-registration getter (calls FUN_100016b0("CGRStatePreRound", parent-getter)); registers `CGRStatePreRound` as a subclass of `CGRState` in the engine RTTI/class-factory system.
- `FUN_10711730` (line 1153808) — **RTTI_GetClassInfo_CGRStateSingle** — class self-registration getter (calls FUN_100016b0("CGRStateSingle", parent-getter)); registers `CGRStateSingle` as a subclass of `CGRState` in the engine RTTI/class-factory system.
- `FUN_10704900` (line 1146226) — **RTTI_GetClassInfo_CGRStateTeamAdversarial** — class self-registration getter (calls FUN_100016b0("CGRStateTeamAdversarial", parent-getter)); registers `CGRStateTeamAdversarial` as a subclass of `CGRStateAdversarial` in the engine RTTI/class-factory system.
- `FUN_10704930` (line 1146242) — **RTTI_GetClassInfo_CGRStateTeamAdversarialInRound** — class self-registration getter (calls FUN_100016b0("CGRStateTeamAdversarialInRound", parent-getter)); registers `CGRStateTeamAdversarialInRound` as a subclass of `CGRStateTeamAdversarial` in the engine RTTI/class-factory system.
- `FUN_10704990` (line 1146274) — **RTTI_GetClassInfo_CGRStateTeamAdversarialLobby** — class self-registration getter (calls FUN_100016b0("CGRStateTeamAdversarialLobby", parent-getter)); registers `CGRStateTeamAdversarialLobby` as a subclass of `CGRState` in the engine RTTI/class-factory system.
- `FUN_10704820` (line 1146181) — **RTTI_GetClassInfo_CGRStateUnload** — class self-registration getter (calls FUN_100016b0("CGRStateUnload", parent-getter)); registers `CGRStateUnload` as a subclass of `CGRState` in the engine RTTI/class-factory system.
- `FUN_10711790` (line 1153840) — **RTTI_GetClassInfo_CGRUsePawnEquipmentFromArchetype** — class self-registration getter (calls FUN_100016b0("CGRUsePawnEquipmentFromArchetype", parent-getter)); registers `CGRUsePawnEquipmentFromArchetype` as a subclass of `CGRQueryParams` in the engine RTTI/class-factory system.
- `FUN_104cbdb0` (line 831978) — **RTTI_GetClassInfo_CGadget** — class self-registration getter (calls FUN_100016b0("CGadget", parent-getter)); registers `CGadget` as a subclass of `CEquipmentBase` in the engine RTTI/class-factory system.
- `FUN_107882f0` (line 1222034) — **RTTI_GetClassInfo_CGadgetMemento** — class self-registration getter (calls FUN_100016b0("CGadgetMemento", parent-getter)); registers `CGadgetMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_108925a0` (line 1379241) — **RTTI_GetClassInfo_CGadgetProjectileMemento** — class self-registration getter (calls FUN_100016b0("CGadgetProjectileMemento", parent-getter)); registers `CGadgetProjectileMemento` as a subclass of `CGadgetMemento` in the engine RTTI/class-factory system.
- `FUN_1097dda0` (line 1500926) — **RTTI_GetClassInfo_CGameAIObject** — class self-registration getter (calls FUN_100016b0("CGameAIObject", parent-getter)); registers `CGameAIObject` as a subclass of `CAIObject` in the engine RTTI/class-factory system.
- `FUN_1097ca60` (line 1499967) — **RTTI_GetClassInfo_CGameAgent** — class self-registration getter (calls FUN_100016b0("CGameAgent", parent-getter)); registers `CGameAgent` as a subclass of `CAgent` in the engine RTTI/class-factory system.
- `FUN_10712f70` (line 1154574) — **RTTI_GetClassInfo_CGameDataValueBase** — class self-registration getter (calls FUN_100016b0("CGameDataValueBase", parent-getter)); registers `CGameDataValueBase` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_10629230` (line 1025674) — **RTTI_GetClassInfo_CGameElementEntity** — class self-registration getter (calls FUN_100016b0("CGameElementEntity", parent-getter)); registers `CGameElementEntity` as a subclass of `COmniMapEntity` in the engine RTTI/class-factory system.
- `FUN_108bb030` (line 1403608) — **RTTI_GetClassInfo_CGameFile** — class self-registration getter (calls FUN_100016b0("CGameFile", parent-getter)); registers `CGameFile` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_104cbc90` (line 831898) — **RTTI_GetClassInfo_CGameFilesService** — class self-registration getter (calls FUN_100016b0("CGameFilesService", parent-getter)); registers `CGameFilesService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_10237d40` (line 393681) — **RTTI_GetClassInfo_CGameMessage** — class self-registration getter (calls FUN_100016b0("CGameMessage", parent-getter)); registers `CGameMessage` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1075bb60` (line 1192901) — **RTTI_GetClassInfo_CGameMessageBox** — class self-registration getter (calls FUN_100016b0("CGameMessageBox", parent-getter)); registers `CGameMessageBox` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_1075bba0` (line 1192920) — **RTTI_GetClassInfo_CGameMessageBoxEvent** — class self-registration getter (calls FUN_100016b0("CGameMessageBoxEvent", parent-getter)); registers `CGameMessageBoxEvent` as a subclass of `CGameMessageBox` in the engine RTTI/class-factory system.
- `FUN_1076c600` (line 1203252) — **RTTI_GetClassInfo_CGameMessageBoxQuickMatchStatus** — class self-registration getter (calls FUN_100016b0("CGameMessageBoxQuickMatchStatus", parent-getter)); registers `CGameMessageBoxQuickMatchStatus` as a subclass of `CGameMessageBoxSpinner` in the engine RTTI/class-factory system.
- `FUN_1075bbd0` (line 1192936) — **RTTI_GetClassInfo_CGameMessageBoxSpinner** — class self-registration getter (calls FUN_100016b0("CGameMessageBoxSpinner", parent-getter)); registers `CGameMessageBoxSpinner` as a subclass of `CGameMessageBox` in the engine RTTI/class-factory system.
- `FUN_10719fb0` (line 1159164) — **RTTI_GetClassInfo_CGameMessageLocalHud** — class self-registration getter (calls FUN_100016b0("CGameMessageLocalHud", parent-getter)); registers `CGameMessageLocalHud` as a subclass of `CGameMessage` in the engine RTTI/class-factory system.
- `FUN_1023e420` (line 397805) — **RTTI_GetClassInfo_CGameMessageMultiText** — class self-registration getter (calls FUN_100016b0("CGameMessageMultiText", parent-getter)); registers `CGameMessageMultiText` as a subclass of `CGameMessage` in the engine RTTI/class-factory system.
- `FUN_10216090` (line 371289) — **RTTI_GetClassInfo_CGameMessageParser** — class self-registration getter (calls FUN_100016b0("CGameMessageParser", parent-getter)); registers `CGameMessageParser` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_102160d0` (line 371308) — **RTTI_GetClassInfo_CGameMessageParser_Generic** — class self-registration getter (calls FUN_100016b0("CGameMessageParser_Generic", parent-getter)); registers `CGameMessageParser_Generic` as a subclass of `CGameMessageParser` in the engine RTTI/class-factory system.
- `FUN_101a05f0` (line 287362) — **RTTI_GetClassInfo_CGameMessageService** — class self-registration getter (calls FUN_100016b0("CGameMessageService", parent-getter)); registers `CGameMessageService` as a subclass of `IGameMessageService` in the engine RTTI/class-factory system.
- `FUN_1023e260` (line 397702) — **RTTI_GetClassInfo_CGameMessageText** — class self-registration getter (calls FUN_100016b0("CGameMessageText", parent-getter)); registers `CGameMessageText` as a subclass of `CGameMessage` in the engine RTTI/class-factory system.
- `FUN_106e6350` (line 1128613) — **RTTI_GetClassInfo_CGameMission** — class self-registration getter (calls FUN_100016b0("CGameMission", parent-getter)); registers `CGameMission` as a subclass of `CBaseMission` in the engine RTTI/class-factory system.
- `FUN_1005a8e0` (line 61635) — **RTTI_GetClassInfo_CGameMode** — class self-registration getter (calls FUN_100016b0("CGameMode", parent-getter)); registers `CGameMode` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_1076a1b0` (line 1201582) — **RTTI_GetClassInfo_CGameModeEntity** — class self-registration getter (calls FUN_100016b0("CGameModeEntity", parent-getter)); registers `CGameModeEntity` as a subclass of `COmniEntity` in the engine RTTI/class-factory system.
- `FUN_106e98b0` (line 1130347) — **RTTI_GetClassInfo_CGameModeMessageFinalBattle** — class self-registration getter (calls FUN_100016b0("CGameModeMessageFinalBattle", parent-getter)); registers `CGameModeMessageFinalBattle` as a subclass of `CGameModeMessageWinner` in the engine RTTI/class-factory system.
- `FUN_106e9820` (line 1130317) — **RTTI_GetClassInfo_CGameModeMessageWinner** — class self-registration getter (calls FUN_100016b0("CGameModeMessageWinner", parent-getter)); registers `CGameModeMessageWinner` as a subclass of `CGameMessage` in the engine RTTI/class-factory system.
- `FUN_101dea70` (line 334794) — **RTTI_GetClassInfo_CGameModeServiceEvent** — class self-registration getter (calls FUN_100016b0("CGameModeServiceEvent", parent-getter)); registers `CGameModeServiceEvent` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_101deaa0` (line 334810) — **RTTI_GetClassInfo_CGameModeServiceNetEngineEvent** — class self-registration getter (calls FUN_100016b0("CGameModeServiceNetEngineEvent", parent-getter)); registers `CGameModeServiceNetEngineEvent` as a subclass of `CGameModeServiceEvent` in the engine RTTI/class-factory system.
- `FUN_1064cbf0` (line 1042208) — **RTTI_GetClassInfo_CGameModeTeamDeathMatch** — class self-registration getter (calls FUN_100016b0("CGameModeTeamDeathMatch", parent-getter)); registers `CGameModeTeamDeathMatch` as a subclass of `CGameMode` in the engine RTTI/class-factory system.
- `FUN_10055bf0` (line 58139) — **RTTI_GetClassInfo_CGameObject** — class self-registration getter (calls FUN_100016b0("CGameObject", parent-getter)); registers `CGameObject` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1003cbf0` (line 41500) — **RTTI_GetClassInfo_CGameOperation** — class self-registration getter (calls FUN_100016b0("CGameOperation", parent-getter)); registers `CGameOperation` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_1003cb80` (line 41466) — **RTTI_GetClassInfo_CGameOperationBuilder** — class self-registration getter (calls FUN_100016b0("CGameOperationBuilder", parent-getter)); registers `CGameOperationBuilder` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_1005a380` (line 61405) — **RTTI_GetClassInfo_CGameOperationContainer** — class self-registration getter (calls FUN_100016b0("CGameOperationContainer", parent-getter)); registers `CGameOperationContainer` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_107337d0` (line 1171201) — **RTTI_GetClassInfo_CGameOperationSimpleBuilder** — class self-registration getter (calls FUN_100016b0("CGameOperationSimpleBuilder", parent-getter)); registers `CGameOperationSimpleBuilder` as a subclass of `CGameOperationBuilder` in the engine RTTI/class-factory system.
- `FUN_1023e290` (line 397718) — **RTTI_GetClassInfo_CGamePlayMessageText** — class self-registration getter (calls FUN_100016b0("CGamePlayMessageText", parent-getter)); registers `CGamePlayMessageText` as a subclass of `CGameMessageText` in the engine RTTI/class-factory system.
- `FUN_1005a990` (line 61671) — **RTTI_GetClassInfo_CGameRules** — class self-registration getter (calls FUN_100016b0("CGameRules", parent-getter)); registers `CGameRules` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_1023fb70` (line 398619) — **RTTI_GetClassInfo_CGameSetting** — class self-registration getter (calls FUN_100016b0("CGameSetting", parent-getter)); registers `CGameSetting` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_1023fbb0` (line 398638) — **RTTI_GetClassInfo_CGameSettingsContainer** — class self-registration getter (calls FUN_100016b0("CGameSettingsContainer", parent-getter)); registers `CGameSettingsContainer` as a subclass of `CGameSetting` in the engine RTTI/class-factory system.
- `FUN_101a0560` (line 287314) — **RTTI_GetClassInfo_CGameSettingsService** — class self-registration getter (calls FUN_100016b0("CGameSettingsService", parent-getter)); registers `CGameSettingsService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_10237d70` (line 393697) — **RTTI_GetClassInfo_CGameSoundMessage** — class self-registration getter (calls FUN_100016b0("CGameSoundMessage", parent-getter)); registers `CGameSoundMessage` as a subclass of `CGameMessage` in the engine RTTI/class-factory system.
- `FUN_10237de0` (line 393713) — **RTTI_GetClassInfo_CGameSoundSequenceMessage** — class self-registration getter (calls FUN_100016b0("CGameSoundSequenceMessage", parent-getter)); registers `CGameSoundSequenceMessage` as a subclass of `CGameMessage` in the engine RTTI/class-factory system.
- `FUN_10198400` (line 280854) — **RTTI_GetClassInfo_CGameSoundService** — class self-registration getter (calls FUN_100016b0("CGameSoundService", parent-getter)); registers `CGameSoundService` as a subclass of `IGameSoundService` in the engine RTTI/class-factory system.
- `FUN_106db880` (line 1122046) — **RTTI_GetClassInfo_CGameStatsService** — class self-registration getter (calls FUN_100016b0("CGameStatsService", parent-getter)); registers `CGameStatsService` as a subclass of `IGameStatsService` in the engine RTTI/class-factory system.
- `FUN_10581cd0` (line 936332) — **RTTI_GetClassInfo_CGameplayManager** — class self-registration getter (calls FUN_100016b0("CGameplayManager", parent-getter)); registers `CGameplayManager` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_101c9e50` (line 319894) — **RTTI_GetClassInfo_CGeometryResource** — class self-registration getter (calls FUN_100016b0("CGeometryResource", parent-getter)); registers `CGeometryResource` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_101a61b0` (line 292038) — **RTTI_GetClassInfo_CGhostComponent** — class self-registration getter (calls FUN_100016b0("CGhostComponent", parent-getter)); registers `CGhostComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a7430` (line 293349) — **RTTI_GetClassInfo_CGhostEntity** — class self-registration getter (calls FUN_100016b0("CGhostEntity", parent-getter)); registers `CGhostEntity` as a subclass of `COmniMapEntity` in the engine RTTI/class-factory system.
- `FUN_101a60f0` (line 291974) — **RTTI_GetClassInfo_CGodRayComponent** — class self-registration getter (calls FUN_100016b0("CGodRayComponent", parent-getter)); registers `CGodRayComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a6980` (line 292571) — **RTTI_GetClassInfo_CGraphicClusterComponent** — class self-registration getter (calls FUN_100016b0("CGraphicClusterComponent", parent-getter)); registers `CGraphicClusterComponent` as a subclass of `CClusterComponent` in the engine RTTI/class-factory system.
- `FUN_10055bc0` (line 58123) — **RTTI_GetClassInfo_CGraphicComponent** — class self-registration getter (calls FUN_100016b0("CGraphicComponent", parent-getter)); registers `CGraphicComponent` as a subclass of `CBaseGraphicComponent` in the engine RTTI/class-factory system.
- `FUN_10055b30` (line 58075) — **RTTI_GetClassInfo_CGraphicKitComponent** — class self-registration getter (calls FUN_100016b0("CGraphicKitComponent", parent-getter)); registers `CGraphicKitComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a6000` (line 291894) — **RTTI_GetClassInfo_CGrassDisplacementComponent** — class self-registration getter (calls FUN_100016b0("CGrassDisplacementComponent", parent-getter)); registers `CGrassDisplacementComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_105bfec0` (line 968593) — **RTTI_GetClassInfo_CHMRCoverEvent** — class self-registration getter (calls FUN_100016b0("CHMRCoverEvent", parent-getter)); registers `CHMRCoverEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1097f4c0` (line 1501504) — **RTTI_GetClassInfo_CHellfireWaspAgent** — class self-registration getter (calls FUN_100016b0("CHellfireWaspAgent", parent-getter)); registers `CHellfireWaspAgent` as a subclass of `CBtzAnimalAgent` in the engine RTTI/class-factory system.
- `FUN_1097f340` (line 1501376) — **RTTI_GetClassInfo_CHexapedeAgent** — class self-registration getter (calls FUN_100016b0("CHexapedeAgent", parent-getter)); registers `CHexapedeAgent` as a subclass of `CBtzAnimalAgent` in the engine RTTI/class-factory system.
- `FUN_10719d80` (line 1159070) — **RTTI_GetClassInfo_CHordeSpawnPointService** — class self-registration getter (calls FUN_100016b0("CHordeSpawnPointService", parent-getter)); registers `CHordeSpawnPointService` as a subclass of `CSpawnPointService` in the engine RTTI/class-factory system.
- `FUN_104ca050` (line 830700) — **RTTI_GetClassInfo_CHordeSpawnerComponent** — class self-registration getter (calls FUN_100016b0("CHordeSpawnerComponent", parent-getter)); registers `CHordeSpawnerComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_10610100` (line 1010775) — **RTTI_GetClassInfo_CHudComponent** — class self-registration getter (calls FUN_100016b0("CHudComponent", parent-getter)); registers `CHudComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1097f030` (line 1501250) — **RTTI_GetClassInfo_CHumanPersonality** — class self-registration getter (calls FUN_100016b0("CHumanPersonality", parent-getter)); registers `CHumanPersonality` as a subclass of `CLivingCreature` in the engine RTTI/class-factory system.
- `FUN_109a1ec0` (line 1525711) — **RTTI_GetClassInfo_CIEDPlacedEvent** — class self-registration getter (calls FUN_100016b0("CIEDPlacedEvent", parent-getter)); registers `CIEDPlacedEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1058a3f0` (line 939955) — **RTTI_GetClassInfo_CIgniteProjectile** — class self-registration getter (calls FUN_100016b0("CIgniteProjectile", parent-getter)); registers `CIgniteProjectile` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_104cb620` (line 831770) — **RTTI_GetClassInfo_CIgnitorComponent** — class self-registration getter (calls FUN_100016b0("CIgnitorComponent", parent-getter)); registers `CIgnitorComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_105ec450` (line 991418) — **RTTI_GetClassInfo_CIgnitorMemento** — class self-registration getter (calls FUN_100016b0("CIgnitorMemento", parent-getter)); registers `CIgnitorMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_10e8cd90` (line 2399362) — **RTTI_GetClassInfo_CInitializeNatOperation** — class self-registration getter (calls FUN_100016b0("CInitializeNatOperation", parent-getter)); registers `CInitializeNatOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_100b2710` (line 126567) — **RTTI_GetClassInfo_CInputDriver** — class self-registration getter (calls FUN_100016b0("CInputDriver", parent-getter)); registers `CInputDriver` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_100d8140` (line 153428) — **RTTI_GetClassInfo_CInputDriverGamepad** — class self-registration getter (calls FUN_100016b0("CInputDriverGamepad", parent-getter)); registers `CInputDriverGamepad` as a subclass of `CInputDriver` in the engine RTTI/class-factory system.
- `FUN_100b2750` (line 126586) — **RTTI_GetClassInfo_CInputDriverKeyboard** — class self-registration getter (calls FUN_100016b0("CInputDriverKeyboard", parent-getter)); registers `CInputDriverKeyboard` as a subclass of `CInputDriver` in the engine RTTI/class-factory system.
- `FUN_100d6e60` (line 152761) — **RTTI_GetClassInfo_CInputDriverMouse** — class self-registration getter (calls FUN_100016b0("CInputDriverMouse", parent-getter)); registers `CInputDriverMouse` as a subclass of `CInputDriver` in the engine RTTI/class-factory system.
- `FUN_105cc590` (line 974028) — **RTTI_GetClassInfo_CInventoryItem** — class self-registration getter (calls FUN_100016b0("CInventoryItem", parent-getter)); registers `CInventoryItem` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_105cf8e0` (line 976250) — **RTTI_GetClassInfo_CInventoryItemAmmoPouch** — class self-registration getter (calls FUN_100016b0("CInventoryItemAmmoPouch", parent-getter)); registers `CInventoryItemAmmoPouch` as a subclass of `CInventoryItem` in the engine RTTI/class-factory system.
- `FUN_105cc5c0` (line 974044) — **RTTI_GetClassInfo_CInventoryItemEquipment** — class self-registration getter (calls FUN_100016b0("CInventoryItemEquipment", parent-getter)); registers `CInventoryItemEquipment` as a subclass of `CInventoryItem` in the engine RTTI/class-factory system.
- `FUN_10741e60` (line 1179267) — **RTTI_GetClassInfo_CInventoryItemEquippedGadget** — class self-registration getter (calls FUN_100016b0("CInventoryItemEquippedGadget", parent-getter)); registers `CInventoryItemEquippedGadget` as a subclass of `CInventoryItemGadget` in the engine RTTI/class-factory system.
- `FUN_10741cd0` (line 1179159) — **RTTI_GetClassInfo_CInventoryItemGadget** — class self-registration getter (calls FUN_100016b0("CInventoryItemGadget", parent-getter)); registers `CInventoryItemGadget` as a subclass of `CInventoryItemEquipment` in the engine RTTI/class-factory system.
- `FUN_105cc5f0` (line 974060) — **RTTI_GetClassInfo_CInventoryItemWeapon** — class self-registration getter (calls FUN_100016b0("CInventoryItemWeapon", parent-getter)); registers `CInventoryItemWeapon` as a subclass of `CInventoryItemEquipment` in the engine RTTI/class-factory system.
- `FUN_106ef800` (line 1134442) — **RTTI_GetClassInfo_CKickBanService** — class self-registration getter (calls FUN_100016b0("CKickBanService", parent-getter)); registers `CKickBanService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1051c2c0` (line 881137) — **RTTI_GetClassInfo_CLadder** — class self-registration getter (calls FUN_100016b0("CLadder", parent-getter)); registers `CLadder` as a subclass of `CGameObject` in the engine RTTI/class-factory system.
- `FUN_10879e00` (line 1366594) — **RTTI_GetClassInfo_CLadderMemento** — class self-registration getter (calls FUN_100016b0("CLadderMemento", parent-getter)); registers `CLadderMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1076d230` (line 1203593) — **RTTI_GetClassInfo_CLadderNetworkComponent** — class self-registration getter (calls FUN_100016b0("CLadderNetworkComponent", parent-getter)); registers `CLadderNetworkComponent` as a subclass of `CNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_108162e0` (line 1306116) — **RTTI_GetClassInfo_CLadderPawnMemento** — class self-registration getter (calls FUN_100016b0("CLadderPawnMemento", parent-getter)); registers `CLadderPawnMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_10204db0` (line 360650) — **RTTI_GetClassInfo_CLandmarkFarCategory** — class self-registration getter (calls FUN_100016b0("CLandmarkFarCategory", parent-getter)); registers `CLandmarkFarCategory` as a subclass of `CSectorSpawnCategory` in the engine RTTI/class-factory system.
- `FUN_10204d80` (line 360634) — **RTTI_GetClassInfo_CLandmarkNearCategory** — class self-registration getter (calls FUN_100016b0("CLandmarkNearCategory", parent-getter)); registers `CLandmarkNearCategory` as a subclass of `CSectorSpawnCategory` in the engine RTTI/class-factory system.
- `FUN_102acb40` (line 466270) — **RTTI_GetClassInfo_CLayerResource** — class self-registration getter (calls FUN_100016b0("CLayerResource", parent-getter)); registers `CLayerResource` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_102612d0` (line 418545) — **RTTI_GetClassInfo_CLightEvent** — class self-registration getter (calls FUN_100016b0("CLightEvent", parent-getter)); registers `CLightEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1021fbe0` (line 378001) — **RTTI_GetClassInfo_CLinearPathFollower** — class self-registration getter (calls FUN_100016b0("CLinearPathFollower", parent-getter)); registers `CLinearPathFollower` as a subclass of `CPathFollower` in the engine RTTI/class-factory system.
- `FUN_1097efd0` (line 1501218) — **RTTI_GetClassInfo_CLivingCreature** — class self-registration getter (calls FUN_100016b0("CLivingCreature", parent-getter)); registers `CLivingCreature` as a subclass of `CPersonality` in the engine RTTI/class-factory system.
- `FUN_106d3c40` (line 1117528) — **RTTI_GetClassInfo_CLoadFlashMovies** — class self-registration getter (calls FUN_100016b0("CLoadFlashMovies", parent-getter)); registers `CLoadFlashMovies` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_106ead60` (line 1130959) — **RTTI_GetClassInfo_CLoadOutEquipAmmoItem** — class self-registration getter (calls FUN_100016b0("CLoadOutEquipAmmoItem", parent-getter)); registers `CLoadOutEquipAmmoItem` as a subclass of `CLoadOutEquipItem` in the engine RTTI/class-factory system.
- `FUN_106ead30` (line 1130943) — **RTTI_GetClassInfo_CLoadOutEquipGadgetItem** — class self-registration getter (calls FUN_100016b0("CLoadOutEquipGadgetItem", parent-getter)); registers `CLoadOutEquipGadgetItem` as a subclass of `CLoadOutEquipItem` in the engine RTTI/class-factory system.
- `FUN_106ead00` (line 1130927) — **RTTI_GetClassInfo_CLoadOutEquipHandToHandItem** — class self-registration getter (calls FUN_100016b0("CLoadOutEquipHandToHandItem", parent-getter)); registers `CLoadOutEquipHandToHandItem` as a subclass of `CLoadOutEquipWeaponItem` in the engine RTTI/class-factory system.
- `FUN_106eabd0` (line 1130826) — **RTTI_GetClassInfo_CLoadOutEquipItem** — class self-registration getter (calls FUN_100016b0("CLoadOutEquipItem", parent-getter)); registers `CLoadOutEquipItem` as a subclass of `CLoadOutItem` in the engine RTTI/class-factory system.
- `FUN_106eac70` (line 1130879) — **RTTI_GetClassInfo_CLoadOutEquipPrimaryItem** — class self-registration getter (calls FUN_100016b0("CLoadOutEquipPrimaryItem", parent-getter)); registers `CLoadOutEquipPrimaryItem` as a subclass of `CLoadOutEquipWeaponItem` in the engine RTTI/class-factory system.
- `FUN_106eaca0` (line 1130895) — **RTTI_GetClassInfo_CLoadOutEquipSecItem** — class self-registration getter (calls FUN_100016b0("CLoadOutEquipSecItem", parent-getter)); registers `CLoadOutEquipSecItem` as a subclass of `CLoadOutEquipWeaponItem` in the engine RTTI/class-factory system.
- `FUN_106eacd0` (line 1130911) — **RTTI_GetClassInfo_CLoadOutEquipSpecialItem** — class self-registration getter (calls FUN_100016b0("CLoadOutEquipSpecialItem", parent-getter)); registers `CLoadOutEquipSpecialItem` as a subclass of `CLoadOutEquipWeaponItem` in the engine RTTI/class-factory system.
- `FUN_106eac40` (line 1130863) — **RTTI_GetClassInfo_CLoadOutEquipWeaponItem** — class self-registration getter (calls FUN_100016b0("CLoadOutEquipWeaponItem", parent-getter)); registers `CLoadOutEquipWeaponItem` as a subclass of `CLoadOutEquipItem` in the engine RTTI/class-factory system.
- `FUN_106eab90` (line 1130807) — **RTTI_GetClassInfo_CLoadOutItem** — class self-registration getter (calls FUN_100016b0("CLoadOutItem", parent-getter)); registers `CLoadOutItem` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_106eaae0` (line 1130761) — **RTTI_GetClassInfo_CLoadOutUIStrategy** — class self-registration getter (calls FUN_100016b0("CLoadOutUIStrategy", parent-getter)); registers `CLoadOutUIStrategy` as a subclass of `CUIStrategy` in the engine RTTI/class-factory system.
- `FUN_10647530` (line 1039654) — **RTTI_GetClassInfo_CLobbyService** — class self-registration getter (calls FUN_100016b0("CLobbyService", parent-getter)); registers `CLobbyService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1084c620` (line 1340512) — **RTTI_GetClassInfo_CLobbyUIStrategy** — class self-registration getter (calls FUN_100016b0("CLobbyUIStrategy", parent-getter)); registers `CLobbyUIStrategy` as a subclass of `CUIStrategy` in the engine RTTI/class-factory system.
- `FUN_10e8bb10` (line 2398218) — **RTTI_GetClassInfo_CLoginSessionParam** — class self-registration getter (calls FUN_100016b0("CLoginSessionParam", parent-getter)); registers `CLoginSessionParam` as a subclass of `COperationData` in the engine RTTI/class-factory system.
- `FUN_1021fbb0` (line 377985) — **RTTI_GetClassInfo_CLoopingPathFollower** — class self-registration getter (calls FUN_100016b0("CLoopingPathFollower", parent-getter)); registers `CLoopingPathFollower` as a subclass of `CPathFollower` in the engine RTTI/class-factory system.
- `FUN_10573a80` (line 928830) — **RTTI_GetClassInfo_CLootPickedUpEvent** — class self-registration getter (calls FUN_100016b0("CLootPickedUpEvent", parent-getter)); registers `CLootPickedUpEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_102260c0` (line 382230) — **RTTI_GetClassInfo_CLuaResource** — class self-registration getter (calls FUN_100016b0("CLuaResource", parent-getter)); registers `CLuaResource` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_104c9440` (line 830250) — **RTTI_GetClassInfo_CMPBase** — class self-registration getter (calls FUN_100016b0("CMPBase", parent-getter)); registers `CMPBase` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1097f000` (line 1501234) — **RTTI_GetClassInfo_CMachine** — class self-registration getter (calls FUN_100016b0("CMachine", parent-getter)); registers `CMachine` as a subclass of `CPersonality` in the engine RTTI/class-factory system.
- `FUN_104cb7e0` (line 831802) — **RTTI_GetClassInfo_CMagicCrate** — class self-registration getter (calls FUN_100016b0("CMagicCrate", parent-getter)); registers `CMagicCrate` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104cbc30` (line 831882) — **RTTI_GetClassInfo_CMajorLocationEntity** — class self-registration getter (calls FUN_100016b0("CMajorLocationEntity", parent-getter)); registers `CMajorLocationEntity` as a subclass of `CEntity` in the engine RTTI/class-factory system.
- `FUN_105c0e80` (line 969096) — **RTTI_GetClassInfo_CMapElementComponent** — class self-registration getter (calls FUN_100016b0("CMapElementComponent", parent-getter)); registers `CMapElementComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104cbc00` (line 831866) — **RTTI_GetClassInfo_CMapIntelligence** — class self-registration getter (calls FUN_100016b0("CMapIntelligence", parent-getter)); registers `CMapIntelligence` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_10611eb0` (line 1011716) — **RTTI_GetClassInfo_CMapOverrideTextureEvent** — class self-registration getter (calls FUN_100016b0("CMapOverrideTextureEvent", parent-getter)); registers `CMapOverrideTextureEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_106475c0` (line 1039686) — **RTTI_GetClassInfo_CMapService** — class self-registration getter (calls FUN_100016b0("CMapService", parent-getter)); registers `CMapService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_101a6890` (line 292491) — **RTTI_GetClassInfo_CMassiveComponent** — class self-registration getter (calls FUN_100016b0("CMassiveComponent", parent-getter)); registers `CMassiveComponent` as a subclass of `COnlineAdComponent` in the engine RTTI/class-factory system.
- `FUN_10628dd0` (line 1025582) — **RTTI_GetClassInfo_CMatchService** — class self-registration getter (calls FUN_100016b0("CMatchService", parent-getter)); registers `CMatchService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_102bedd0` (line 479469) — **RTTI_GetClassInfo_CMaterialImpactFxEvent** — class self-registration getter (calls FUN_100016b0("CMaterialImpactFxEvent", parent-getter)); registers `CMaterialImpactFxEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_101f3660` (line 348923) — **RTTI_GetClassInfo_CMaterialResource** — class self-registration getter (calls FUN_100016b0("CMaterialResource", parent-getter)); registers `CMaterialResource` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_100f1290` (line 173520) — **RTTI_GetClassInfo_CMemoryStreamFile** — class self-registration getter (calls FUN_100016b0("CMemoryStreamFile", parent-getter)); registers `CMemoryStreamFile` as a subclass of `IFile` in the engine RTTI/class-factory system.
- `FUN_101a5d30` (line 291766) — **RTTI_GetClassInfo_CMetaSector** — class self-registration getter (calls FUN_100016b0("CMetaSector", parent-getter)); registers `CMetaSector` as a subclass of `CWorldSector` in the engine RTTI/class-factory system.
- `FUN_1005d1d0` (line 63603) — **RTTI_GetClassInfo_CMetagameUIComponent** — class self-registration getter (calls FUN_100016b0("CMetagameUIComponent", parent-getter)); registers `CMetagameUIComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_10e8b570` (line 2397903) — **RTTI_GetClassInfo_CMigrateSessionParam** — class self-registration getter (calls FUN_100016b0("CMigrateSessionParam", parent-getter)); registers `CMigrateSessionParam` as a subclass of `COperationData` in the engine RTTI/class-factory system.
- `FUN_104ca7d0` (line 831100) — **RTTI_GetClassInfo_CMissileNetworkComponent** — class self-registration getter (calls FUN_100016b0("CMissileNetworkComponent", parent-getter)); registers `CMissileNetworkComponent` as a subclass of `CNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_101a5eb0` (line 291782) — **RTTI_GetClassInfo_CMissionComponent** — class self-registration getter (calls FUN_100016b0("CMissionComponent", parent-getter)); registers `CMissionComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1022bc20` (line 384980) — **RTTI_GetClassInfo_CMissionHandlerEvent** — class self-registration getter (calls FUN_100016b0("CMissionHandlerEvent", parent-getter)); registers `CMissionHandlerEvent` as a subclass of `CScriptEvent` in the engine RTTI/class-factory system.
- `FUN_107b6a70` (line 1248081) — **RTTI_GetClassInfo_CMortarIncoming** — class self-registration getter (calls FUN_100016b0("CMortarIncoming", parent-getter)); registers `CMortarIncoming` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_105312c0` (line 892770) — **RTTI_GetClassInfo_CMountedWeapon** — class self-registration getter (calls FUN_100016b0("CMountedWeapon", parent-getter)); registers `CMountedWeapon` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_109804a0` (line 1501953) — **RTTI_GetClassInfo_CMountedWeaponSmartTerrain** — class self-registration getter (calls FUN_100016b0("CMountedWeaponSmartTerrain", parent-getter)); registers `CMountedWeaponSmartTerrain` as a subclass of `CSmartTerrain` in the engine RTTI/class-factory system.
- `FUN_101b9340` (line 307054) — **RTTI_GetClassInfo_CMovementResource** — class self-registration getter (calls FUN_100016b0("CMovementResource", parent-getter)); registers `CMovementResource` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_1097f0c0` (line 1501298) — **RTTI_GetClassInfo_CMusicAIInfoManager** — class self-registration getter (calls FUN_100016b0("CMusicAIInfoManager", parent-getter)); registers `CMusicAIInfoManager` as a subclass of `CSingletonEntity` in the engine RTTI/class-factory system.
- `FUN_1079adf0` (line 1233926) — **RTTI_GetClassInfo_CMuzzleFlashManager** — class self-registration getter (calls FUN_100016b0("CMuzzleFlashManager", parent-getter)); registers `CMuzzleFlashManager` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_104ca020` (line 830684) — **RTTI_GetClassInfo_CNPCSpawnerComponent** — class self-registration getter (calls FUN_100016b0("CNPCSpawnerComponent", parent-getter)); registers `CNPCSpawnerComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_109805c0` (line 1502049) — **RTTI_GetClassInfo_CNavMeshGenComponent** — class self-registration getter (calls FUN_100016b0("CNavMeshGenComponent", parent-getter)); registers `CNavMeshGenComponent` as a subclass of `CGameAIObject` in the engine RTTI/class-factory system.
- `FUN_104bdff0` (line 820740) — **RTTI_GetClassInfo_CNavMeshSectorEvent** — class self-registration getter (calls FUN_100016b0("CNavMeshSectorEvent", parent-getter)); registers `CNavMeshSectorEvent` as a subclass of `CBaseEvent` in the engine RTTI/class-factory system.
- `FUN_104a1860` (line 803031) — **RTTI_GetClassInfo_CNavMeshSectorResource** — class self-registration getter (calls FUN_100016b0("CNavMeshSectorResource", parent-getter)); registers `CNavMeshSectorResource` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_101a5fd0` (line 291878) — **RTTI_GetClassInfo_CNavigationVolumeComponent** — class self-registration getter (calls FUN_100016b0("CNavigationVolumeComponent", parent-getter)); registers `CNavigationVolumeComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_10096e20` (line 107665) — **RTTI_GetClassInfo_CNetDataContainer** — class self-registration getter (calls FUN_100016b0("CNetDataContainer", parent-getter)); registers `CNetDataContainer` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_1012afa0` (line 206169) — **RTTI_GetClassInfo_CNetDataVisitor** — class self-registration getter (calls FUN_100016b0("CNetDataVisitor", parent-getter)); registers `CNetDataVisitor` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_1012e680` (line 209313) — **RTTI_GetClassInfo_CNetDescriptor** — class self-registration getter (calls FUN_100016b0("CNetDescriptor", parent-getter)); registers `CNetDescriptor` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1089e1c0` (line 1386269) — **RTTI_GetClassInfo_CNetFuncDrawWeapon** — class self-registration getter (calls FUN_100016b0("CNetFuncDrawWeapon", parent-getter)); registers `CNetFuncDrawWeapon` as a subclass of `CPawnNetFunc` in the engine RTTI/class-factory system.
- `FUN_106d3310` (line 1117226) — **RTTI_GetClassInfo_CNetGameCtrlState** — class self-registration getter (calls FUN_100016b0("CNetGameCtrlState", parent-getter)); registers `CNetGameCtrlState` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_10783bb0` (line 1218636) — **RTTI_GetClassInfo_CNetGameCtrlStateChangeContext** — class self-registration getter (calls FUN_100016b0("CNetGameCtrlStateChangeContext", parent-getter)); registers `CNetGameCtrlStateChangeContext` as a subclass of `CNetGameCtrlStateGameContext` in the engine RTTI/class-factory system.
- `FUN_10783b80` (line 1218620) — **RTTI_GetClassInfo_CNetGameCtrlStateGameContext** — class self-registration getter (calls FUN_100016b0("CNetGameCtrlStateGameContext", parent-getter)); registers `CNetGameCtrlStateGameContext` as a subclass of `CNetGameCtrlState` in the engine RTTI/class-factory system.
- `FUN_106d3380` (line 1117261) — **RTTI_GetClassInfo_CNetGameCtrlStateLoadWorld** — class self-registration getter (calls FUN_100016b0("CNetGameCtrlStateLoadWorld", parent-getter)); registers `CNetGameCtrlStateLoadWorld` as a subclass of `CNetGameCtrlStateUpdate` in the engine RTTI/class-factory system.
- `FUN_10783c70` (line 1218702) — **RTTI_GetClassInfo_CNetGameCtrlStateLocalPresence** — class self-registration getter (calls FUN_100016b0("CNetGameCtrlStateLocalPresence", parent-getter)); registers `CNetGameCtrlStateLocalPresence` as a subclass of `CNetGameCtrlStatePresence` in the engine RTTI/class-factory system.
- `FUN_10783c00` (line 1218665) — **RTTI_GetClassInfo_CNetGameCtrlStatePresence** — class self-registration getter (calls FUN_100016b0("CNetGameCtrlStatePresence", parent-getter)); registers `CNetGameCtrlStatePresence` as a subclass of `CNetGameCtrlState` in the engine RTTI/class-factory system.
- `FUN_106d33d0` (line 1117290) — **RTTI_GetClassInfo_CNetGameCtrlStateUnloadWorld** — class self-registration getter (calls FUN_100016b0("CNetGameCtrlStateUnloadWorld", parent-getter)); registers `CNetGameCtrlStateUnloadWorld` as a subclass of `CNetGameCtrlStateUpdate` in the engine RTTI/class-factory system.
- `FUN_106d3350` (line 1117245) — **RTTI_GetClassInfo_CNetGameCtrlStateUpdate** — class self-registration getter (calls FUN_100016b0("CNetGameCtrlStateUpdate", parent-getter)); registers `CNetGameCtrlStateUpdate` as a subclass of `CNetGameCtrlState` in the engine RTTI/class-factory system.
- `FUN_1075f030` (line 1195421) — **RTTI_GetClassInfo_CNetGameCtrlStateUpdateInGame** — class self-registration getter (calls FUN_100016b0("CNetGameCtrlStateUpdateInGame", parent-getter)); registers `CNetGameCtrlStateUpdateInGame` as a subclass of `CNetGameCtrlStateUpdate` in the engine RTTI/class-factory system.
- `FUN_10783ca0` (line 1218718) — **RTTI_GetClassInfo_CNetGameCtrlStateUpdateLobby** — class self-registration getter (calls FUN_100016b0("CNetGameCtrlStateUpdateLobby", parent-getter)); registers `CNetGameCtrlStateUpdateLobby` as a subclass of `CNetGameCtrlStateUpdate` in the engine RTTI/class-factory system.
- `FUN_10e9c540` (line 2411552) — **RTTI_GetClassInfo_CNetMessageClientReady** — class self-registration getter (calls FUN_100016b0("CNetMessageClientReady", parent-getter)); registers `CNetMessageClientReady` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_10e9f340` (line 2413842) — **RTTI_GetClassInfo_CNetMessageClientReady_RdV** — class self-registration getter (calls FUN_100016b0("CNetMessageClientReady_RdV", parent-getter)); registers `CNetMessageClientReady_RdV` as a subclass of `CNetMessageClientReady` in the engine RTTI/class-factory system.
- `FUN_1012af40` (line 206154) — **RTTI_GetClassInfo_CNetMessageEmpty** — class self-registration getter (calls FUN_100016b0("CNetMessageEmpty", parent-getter)); registers `CNetMessageEmpty` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_10136840` (line 216378) — **RTTI_GetClassInfo_CNetObjectOperation** — class self-registration getter (calls FUN_100016b0("CNetObjectOperation", parent-getter)); registers `CNetObjectOperation` as a subclass of `IOperation` in the engine RTTI/class-factory system.
- `FUN_1012ff00` (line 210666) — **RTTI_GetClassInfo_CNetObjectSerializer** — class self-registration getter (calls FUN_100016b0("CNetObjectSerializer", parent-getter)); registers `CNetObjectSerializer` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_10e8eb70` (line 2401346) — **RTTI_GetClassInfo_CNetSessionMessageQuery** — class self-registration getter (calls FUN_100016b0("CNetSessionMessageQuery", parent-getter)); registers `CNetSessionMessageQuery` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_10e9c280` (line 2411386) — **RTTI_GetClassInfo_CNetSessionMessageResponse** — class self-registration getter (calls FUN_100016b0("CNetSessionMessageResponse", parent-getter)); registers `CNetSessionMessageResponse` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_10e8eba0` (line 2401362) — **RTTI_GetClassInfo_CNetSessionMigrationMessage** — class self-registration getter (calls FUN_100016b0("CNetSessionMigrationMessage", parent-getter)); registers `CNetSessionMigrationMessage` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1013f5d0` (line 222961) — **RTTI_GetClassInfo_CNetSimulationCameraMemento** — class self-registration getter (calls FUN_100016b0("CNetSimulationCameraMemento", parent-getter)); registers `CNetSimulationCameraMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_101a5f70` (line 291846) — **RTTI_GetClassInfo_CNetworkComponent** — class self-registration getter (calls FUN_100016b0("CNetworkComponent", parent-getter)); registers `CNetworkComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a5f40` (line 291830) — **RTTI_GetClassInfo_CNetworkResource** — class self-registration getter (calls FUN_100016b0("CNetworkResource", parent-getter)); registers `CNetworkResource` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_101383a0` (line 217778) — **RTTI_GetClassInfo_CNetworkSetting** — class self-registration getter (calls FUN_100016b0("CNetworkSetting", parent-getter)); registers `CNetworkSetting` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_10144400` (line 227066) — **RTTI_GetClassInfo_CNetworkSettingsCollection** — class self-registration getter (calls FUN_100016b0("CNetworkSettingsCollection", parent-getter)); registers `CNetworkSettingsCollection` as a subclass of `CNetworkSetting` in the engine RTTI/class-factory system.
- `FUN_10142bb0` (line 225721) — **RTTI_GetClassInfo_CNewConnectionOperation** — class self-registration getter (calls FUN_100016b0("CNewConnectionOperation", parent-getter)); registers `CNewConnectionOperation` as a subclass of `IOperation` in the engine RTTI/class-factory system.
- `FUN_101a69b0` (line 292587) — **RTTI_GetClassInfo_CNewParticlesComponent** — class self-registration getter (calls FUN_100016b0("CNewParticlesComponent", parent-getter)); registers `CNewParticlesComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_10255480` (line 411740) — **RTTI_GetClassInfo_CNewParticlesSystemCleanEvent** — class self-registration getter (calls FUN_100016b0("CNewParticlesSystemCleanEvent", parent-getter)); registers `CNewParticlesSystemCleanEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_102553a0` (line 411666) — **RTTI_GetClassInfo_CNewParticlesSystemPauseEvent** — class self-registration getter (calls FUN_100016b0("CNewParticlesSystemPauseEvent", parent-getter)); registers `CNewParticlesSystemPauseEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_10255370` (line 411650) — **RTTI_GetClassInfo_CNewParticlesSystemStartEvent** — class self-registration getter (calls FUN_100016b0("CNewParticlesSystemStartEvent", parent-getter)); registers `CNewParticlesSystemStartEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_10255410` (line 411703) — **RTTI_GetClassInfo_CNewParticlesSystemStopEvent** — class self-registration getter (calls FUN_100016b0("CNewParticlesSystemStopEvent", parent-getter)); registers `CNewParticlesSystemStopEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1025a590` (line 414807) — **RTTI_GetClassInfo_CNomadDbObject** — class self-registration getter (calls FUN_100016b0("CNomadDbObject", parent-getter)); registers `CNomadDbObject` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_1027f180` (line 437375) — **RTTI_GetClassInfo_CNomadDbObjectNamed** — class self-registration getter (calls FUN_100016b0("CNomadDbObjectNamed", parent-getter)); registers `CNomadDbObjectNamed` as a subclass of `CNomadDbObject` in the engine RTTI/class-factory system.
- `FUN_1003cb10` (line 41432) — **RTTI_GetClassInfo_CNomadObject** — class self-registration getter (calls FUN_100016b0("CNomadObject", parent-getter)); registers `CNomadObject` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_101a58f0` (line 291414) — **RTTI_GetClassInfo_COcclusionQueryComponent** — class self-registration getter (calls FUN_100016b0("COcclusionQueryComponent", parent-getter)); registers `COcclusionQueryComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1052eb30` (line 891222) — **RTTI_GetClassInfo_COffsetedImpactFxEvent** — class self-registration getter (calls FUN_100016b0("COffsetedImpactFxEvent", parent-getter)); registers `COffsetedImpactFxEvent` as a subclass of `CMaterialImpactFxEvent` in the engine RTTI/class-factory system.
- `FUN_101a6650` (line 292299) — **RTTI_GetClassInfo_COmniEntity** — class self-registration getter (calls FUN_100016b0("COmniEntity", parent-getter)); registers `COmniEntity` as a subclass of `CEntity` in the engine RTTI/class-factory system.
- `FUN_101a66e0` (line 292347) — **RTTI_GetClassInfo_COmniMapEntity** — class self-registration getter (calls FUN_100016b0("COmniMapEntity", parent-getter)); registers `COmniMapEntity` as a subclass of `CEntity` in the engine RTTI/class-factory system.
- `FUN_101a69e0` (line 292603) — **RTTI_GetClassInfo_COmniMapTickedEntity** — class self-registration getter (calls FUN_100016b0("COmniMapTickedEntity", parent-getter)); registers `COmniMapTickedEntity` as a subclass of `COmniMapEntity` in the engine RTTI/class-factory system.
- `FUN_1023d780` (line 397213) — **RTTI_GetClassInfo_COnGameStatChangedParam** — class self-registration getter (calls FUN_100016b0("COnGameStatChangedParam", parent-getter)); registers `COnGameStatChangedParam` as a subclass of `IOnValueChangedParam` in the engine RTTI/class-factory system.
- `FUN_102ea9a0` (line 508332) — **RTTI_GetClassInfo_COnStatChangedParam** — class self-registration getter (calls FUN_100016b0("COnStatChangedParam", parent-getter)); registers `COnStatChangedParam` as a subclass of `IOnValueChangedParam` in the engine RTTI/class-factory system.
- `FUN_101a6830` (line 292459) — **RTTI_GetClassInfo_COnlineAdComponent** — class self-registration getter (calls FUN_100016b0("COnlineAdComponent", parent-getter)); registers `COnlineAdComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104f8650` (line 859556) — **RTTI_GetClassInfo_COpenComputerEvent** — class self-registration getter (calls FUN_100016b0("COpenComputerEvent", parent-getter)); registers `COpenComputerEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_10e8a5c0` (line 2396805) — **RTTI_GetClassInfo_COperation** — class self-registration getter (calls FUN_100016b0("COperation", parent-getter)); registers `COperation` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_10e8a510` (line 2396772) — **RTTI_GetClassInfo_COperationData** — class self-registration getter (calls FUN_100016b0("COperationData", parent-getter)); registers `COperationData` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_1058df00` (line 941672) — **RTTI_GetClassInfo_COutOfWorldEvent** — class self-registration getter (calls FUN_100016b0("COutOfWorldEvent", parent-getter)); registers `COutOfWorldEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1097f520` (line 1501536) — **RTTI_GetClassInfo_CParasolAgent** — class self-registration getter (calls FUN_100016b0("CParasolAgent", parent-getter)); registers `CParasolAgent` as a subclass of `CGameAIObject` in the engine RTTI/class-factory system.
- `FUN_10984570` (line 1507441) — **RTTI_GetClassInfo_CParasolCluster** — class self-registration getter (calls FUN_100016b0("CParasolCluster", parent-getter)); registers `CParasolCluster` as a subclass of `CDynamicGameAIObject` in the engine RTTI/class-factory system.
- `FUN_101a6a10` (line 292619) — **RTTI_GetClassInfo_CParticleAutoDestroyComponent** — class self-registration getter (calls FUN_100016b0("CParticleAutoDestroyComponent", parent-getter)); registers `CParticleAutoDestroyComponent` as a subclass of `CNewParticlesComponent` in the engine RTTI/class-factory system.
- `FUN_1076d0e0` (line 1203497) — **RTTI_GetClassInfo_CParticleEventListenerComponent** — class self-registration getter (calls FUN_100016b0("CParticleEventListenerComponent", parent-getter)); registers `CParticleEventListenerComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a6a40` (line 292635) — **RTTI_GetClassInfo_CParticleFXComponent** — class self-registration getter (calls FUN_100016b0("CParticleFXComponent", parent-getter)); registers `CParticleFXComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1021d490` (line 376153) — **RTTI_GetClassInfo_CParticleFXEvent** — class self-registration getter (calls FUN_100016b0("CParticleFXEvent", parent-getter)); registers `CParticleFXEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1021c900` (line 375502) — **RTTI_GetClassInfo_CParticlePhysComponent** — class self-registration getter (calls FUN_100016b0("CParticlePhysComponent", parent-getter)); registers `CParticlePhysComponent` as a subclass of `CPhysComponent` in the engine RTTI/class-factory system.
- `FUN_103e3480` (line 676148) — **RTTI_GetClassInfo_CParticlesEmitterParamResource** — class self-registration getter (calls FUN_100016b0("CParticlesEmitterParamResource", parent-getter)); registers `CParticlesEmitterParamResource` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_10255340` (line 411634) — **RTTI_GetClassInfo_CParticlesSystemParamResource** — class self-registration getter (calls FUN_100016b0("CParticlesSystemParamResource", parent-getter)); registers `CParticlesSystemParamResource` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_108a5d30` (line 1390320) — **RTTI_GetClassInfo_CPartyService** — class self-registration getter (calls FUN_100016b0("CPartyService", parent-getter)); registers `CPartyService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_10980500` (line 1501985) — **RTTI_GetClassInfo_CPathFindTester** — class self-registration getter (calls FUN_100016b0("CPathFindTester", parent-getter)); registers `CPathFindTester` as a subclass of `CAgent` in the engine RTTI/class-factory system.
- `FUN_1021fb80` (line 377969) — **RTTI_GetClassInfo_CPathFollower** — class self-registration getter (calls FUN_100016b0("CPathFollower", parent-getter)); registers `CPathFollower` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_10982c30` (line 1505329) — **RTTI_GetClassInfo_CPatrolBrain** — class self-registration getter (calls FUN_100016b0("CPatrolBrain", parent-getter)); registers `CPatrolBrain` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_10055c50` (line 58171) — **RTTI_GetClassInfo_CPawn** — class self-registration getter (calls FUN_100016b0("CPawn", parent-getter)); registers `CPawn` as a subclass of `CPawnBase` in the engine RTTI/class-factory system.
- `FUN_10980740` (line 1502177) — **RTTI_GetClassInfo_CPawnAction** — class self-registration getter (calls FUN_100016b0("CPawnAction", parent-getter)); registers `CPawnAction` as a subclass of `CPawnBaseAction` in the engine RTTI/class-factory system.
- `FUN_1097dd40` (line 1500894) — **RTTI_GetClassInfo_CPawnAgent** — class self-registration getter (calls FUN_100016b0("CPawnAgent", parent-getter)); registers `CPawnAgent` as a subclass of `CPawnBaseAgent` in the engine RTTI/class-factory system.
- `FUN_10055c20` (line 58155) — **RTTI_GetClassInfo_CPawnBase** — class self-registration getter (calls FUN_100016b0("CPawnBase", parent-getter)); registers `CPawnBase` as a subclass of `CGameObject` in the engine RTTI/class-factory system.
- `FUN_109806e0` (line 1502145) — **RTTI_GetClassInfo_CPawnBaseAction** — class self-registration getter (calls FUN_100016b0("CPawnBaseAction", parent-getter)); registers `CPawnBaseAction` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_1097ce30` (line 1500037) — **RTTI_GetClassInfo_CPawnBaseAgent** — class self-registration getter (calls FUN_100016b0("CPawnBaseAgent", parent-getter)); registers `CPawnBaseAgent` as a subclass of `CGameAgent` in the engine RTTI/class-factory system.
- `FUN_10980710` (line 1502161) — **RTTI_GetClassInfo_CPawnBaseDecision** — class self-registration getter (calls FUN_100016b0("CPawnBaseDecision", parent-getter)); registers `CPawnBaseDecision` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10982e10` (line 1505489) — **RTTI_GetClassInfo_CPawnBaseScanner** — class self-registration getter (calls FUN_100016b0("CPawnBaseScanner", parent-getter)); registers `CPawnBaseScanner` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_109e30b0` (line 1561729) — **RTTI_GetClassInfo_CPawnBaseSensorySystem** — class self-registration getter (calls FUN_100016b0("CPawnBaseSensorySystem", parent-getter)); registers `CPawnBaseSensorySystem` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_1003d080` (line 41887) — **RTTI_GetClassInfo_CPawnBeautifier** — class self-registration getter (calls FUN_100016b0("CPawnBeautifier", parent-getter)); registers `CPawnBeautifier` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_10055c80` (line 58187) — **RTTI_GetClassInfo_CPawnBeautifierComponent** — class self-registration getter (calls FUN_100016b0("CPawnBeautifierComponent", parent-getter)); registers `CPawnBeautifierComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_105cc980` (line 974213) — **RTTI_GetClassInfo_CPawnBurnedEvent** — class self-registration getter (calls FUN_100016b0("CPawnBurnedEvent", parent-getter)); registers `CPawnBurnedEvent` as a subclass of `CBaseEvent` in the engine RTTI/class-factory system.
- `FUN_108160b0` (line 1305930) — **RTTI_GetClassInfo_CPawnCommonMemento** — class self-registration getter (calls FUN_100016b0("CPawnCommonMemento", parent-getter)); registers `CPawnCommonMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_108160e0` (line 1305946) — **RTTI_GetClassInfo_CPawnControllerMemento** — class self-registration getter (calls FUN_100016b0("CPawnControllerMemento", parent-getter)); registers `CPawnControllerMemento` as a subclass of `CPawnCommonMemento` in the engine RTTI/class-factory system.
- `FUN_10980770` (line 1502193) — **RTTI_GetClassInfo_CPawnDecision** — class self-registration getter (calls FUN_100016b0("CPawnDecision", parent-getter)); registers `CPawnDecision` as a subclass of `CPawnBaseDecision` in the engine RTTI/class-factory system.
- `FUN_10702020` (line 1145063) — **RTTI_GetClassInfo_CPawnEnemyMonitor** — class self-registration getter (calls FUN_100016b0("CPawnEnemyMonitor", parent-getter)); registers `CPawnEnemyMonitor` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1054f490` (line 908964) — **RTTI_GetClassInfo_CPawnEvent** — class self-registration getter (calls FUN_100016b0("CPawnEvent", parent-getter)); registers `CPawnEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_105f4b10` (line 995881) — **RTTI_GetClassInfo_CPawnEventFakeBullet** — class self-registration getter (calls FUN_100016b0("CPawnEventFakeBullet", parent-getter)); registers `CPawnEventFakeBullet` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_10531b20` (line 893067) — **RTTI_GetClassInfo_CPawnEventMeleeStrike** — class self-registration getter (calls FUN_100016b0("CPawnEventMeleeStrike", parent-getter)); registers `CPawnEventMeleeStrike` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_104ed3a0` (line 852584) — **RTTI_GetClassInfo_CPawnEventProcessLanding** — class self-registration getter (calls FUN_100016b0("CPawnEventProcessLanding", parent-getter)); registers `CPawnEventProcessLanding` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1097fcd0` (line 1501828) — **RTTI_GetClassInfo_CPawnHitAndRunAgent** — class self-registration getter (calls FUN_100016b0("CPawnHitAndRunAgent", parent-getter)); registers `CPawnHitAndRunAgent` as a subclass of `CPawnAgent` in the engine RTTI/class-factory system.
- `FUN_10816110` (line 1305962) — **RTTI_GetClassInfo_CPawnHostMemento** — class self-registration getter (calls FUN_100016b0("CPawnHostMemento", parent-getter)); registers `CPawnHostMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1003dd30` (line 42545) — **RTTI_GetClassInfo_CPawnInteractionMonitor** — class self-registration getter (calls FUN_100016b0("CPawnInteractionMonitor", parent-getter)); registers `CPawnInteractionMonitor` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_10816170` (line 1305994) — **RTTI_GetClassInfo_CPawnInventoryEquipmentMemento** — class self-registration getter (calls FUN_100016b0("CPawnInventoryEquipmentMemento", parent-getter)); registers `CPawnInventoryEquipmentMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_105559a0` (line 912734) — **RTTI_GetClassInfo_CPawnNetDodge** — class self-registration getter (calls FUN_100016b0("CPawnNetDodge", parent-getter)); registers `CPawnNetDodge` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1062d4d0` (line 1027745) — **RTTI_GetClassInfo_CPawnNetFunc** — class self-registration getter (calls FUN_100016b0("CPawnNetFunc", parent-getter)); registers `CPawnNetFunc` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_10700b40` (line 1144315) — **RTTI_GetClassInfo_CPawnNetMessageEntityID** — class self-registration getter (calls FUN_100016b0("CPawnNetMessageEntityID", parent-getter)); registers `CPawnNetMessageEntityID` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_108118f0` (line 1302817) — **RTTI_GetClassInfo_CPawnNetMessageStartStopShoot** — class self-registration getter (calls FUN_100016b0("CPawnNetMessageStartStopShoot", parent-getter)); registers `CPawnNetMessageStartStopShoot` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_10811960` (line 1302854) — **RTTI_GetClassInfo_CPawnNetMessageSwitchIEDMode** — class self-registration getter (calls FUN_100016b0("CPawnNetMessageSwitchIEDMode", parent-getter)); registers `CPawnNetMessageSwitchIEDMode` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_106dfa40` (line 1124116) — **RTTI_GetClassInfo_CPawnNetMessageUseEntity** — class self-registration getter (calls FUN_100016b0("CPawnNetMessageUseEntity", parent-getter)); registers `CPawnNetMessageUseEntity` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1050e930` (line 873186) — **RTTI_GetClassInfo_CPawnNetworkComponent** — class self-registration getter (calls FUN_100016b0("CPawnNetworkComponent", parent-getter)); registers `CPawnNetworkComponent` as a subclass of `CNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_10982e40` (line 1505505) — **RTTI_GetClassInfo_CPawnScanner** — class self-registration getter (calls FUN_100016b0("CPawnScanner", parent-getter)); registers `CPawnScanner` as a subclass of `CPawnBaseScanner` in the engine RTTI/class-factory system.
- `FUN_104cb810` (line 831818) — **RTTI_GetClassInfo_CPawnSoundAndFXComponent** — class self-registration getter (calls FUN_100016b0("CPawnSoundAndFXComponent", parent-getter)); registers `CPawnSoundAndFXComponent` as a subclass of `CCreatureSoundAndFXComponent` in the engine RTTI/class-factory system.
- `FUN_10816140` (line 1305978) — **RTTI_GetClassInfo_CPawnThirdPartyMemento** — class self-registration getter (calls FUN_100016b0("CPawnThirdPartyMemento", parent-getter)); registers `CPawnThirdPartyMemento` as a subclass of `CPawnCommonMemento` in the engine RTTI/class-factory system.
- `FUN_10142c20` (line 225756) — **RTTI_GetClassInfo_CPeerMessageDeliveryOperation** — class self-registration getter (calls FUN_100016b0("CPeerMessageDeliveryOperation", parent-getter)); registers `CPeerMessageDeliveryOperation` as a subclass of `IOperation` in the engine RTTI/class-factory system.
- `FUN_101a5d00` (line 291750) — **RTTI_GetClassInfo_CPersistComponent** — class self-registration getter (calls FUN_100016b0("CPersistComponent", parent-getter)); registers `CPersistComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_10204c30` (line 360530) — **RTTI_GetClassInfo_CPersistenceMgr** — class self-registration getter (calls FUN_100016b0("CPersistenceMgr", parent-getter)); registers `CPersistenceMgr` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1097efa0` (line 1501202) — **RTTI_GetClassInfo_CPersonality** — class self-registration getter (calls FUN_100016b0("CPersonality", parent-getter)); registers `CPersonality` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_106100a0` (line 1010759) — **RTTI_GetClassInfo_CPhoneCallEvent** — class self-registration getter (calls FUN_100016b0("CPhoneCallEvent", parent-getter)); registers `CPhoneCallEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_102b3fc0` (line 472545) — **RTTI_GetClassInfo_CPhysBulletHitStim** — class self-registration getter (calls FUN_100016b0("CPhysBulletHitStim", parent-getter)); registers `CPhysBulletHitStim` as a subclass of `CPhysStim` in the engine RTTI/class-factory system.
- `FUN_102fecb0` (line 521502) — **RTTI_GetClassInfo_CPhysCollisionQueryEvent** — class self-registration getter (calls FUN_100016b0("CPhysCollisionQueryEvent", parent-getter)); registers `CPhysCollisionQueryEvent` as a subclass of `CBaseEvent` in the engine RTTI/class-factory system.
- `FUN_1028b3b0` (line 445733) — **RTTI_GetClassInfo_CPhysCollisionStim** — class self-registration getter (calls FUN_100016b0("CPhysCollisionStim", parent-getter)); registers `CPhysCollisionStim` as a subclass of `CPhysStim` in the engine RTTI/class-factory system.
- `FUN_1003dca0` (line 42497) — **RTTI_GetClassInfo_CPhysComponent** — class self-registration getter (calls FUN_100016b0("CPhysComponent", parent-getter)); registers `CPhysComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_102b3ff0` (line 472561) — **RTTI_GetClassInfo_CPhysExplosionStim** — class self-registration getter (calls FUN_100016b0("CPhysExplosionStim", parent-getter)); registers `CPhysExplosionStim` as a subclass of `CPhysStim` in the engine RTTI/class-factory system.
- `FUN_10203870` (line 359479) — **RTTI_GetClassInfo_CPhysMemento** — class self-registration getter (calls FUN_100016b0("CPhysMemento", parent-getter)); registers `CPhysMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1021c9c0` (line 375566) — **RTTI_GetClassInfo_CPhysNetworkComponent** — class self-registration getter (calls FUN_100016b0("CPhysNetworkComponent", parent-getter)); registers `CPhysNetworkComponent` as a subclass of `CNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_10229a60` (line 383694) — **RTTI_GetClassInfo_CPhysOutOfWorldEvent** — class self-registration getter (calls FUN_100016b0("CPhysOutOfWorldEvent", parent-getter)); registers `CPhysOutOfWorldEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_10899ab0` (line 1383364) — **RTTI_GetClassInfo_CPhysParticleMemento** — class self-registration getter (calls FUN_100016b0("CPhysParticleMemento", parent-getter)); registers `CPhysParticleMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_101a6180` (line 292022) — **RTTI_GetClassInfo_CPhysPhantomComponent** — class self-registration getter (calls FUN_100016b0("CPhysPhantomComponent", parent-getter)); registers `CPhysPhantomComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1021c960` (line 375534) — **RTTI_GetClassInfo_CPhysRayPhantomComponent** — class self-registration getter (calls FUN_100016b0("CPhysRayPhantomComponent", parent-getter)); registers `CPhysRayPhantomComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101f3630` (line 348907) — **RTTI_GetClassInfo_CPhysResource** — class self-registration getter (calls FUN_100016b0("CPhysResource", parent-getter)); registers `CPhysResource` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_1028b380` (line 445717) — **RTTI_GetClassInfo_CPhysStim** — class self-registration getter (calls FUN_100016b0("CPhysStim", parent-getter)); registers `CPhysStim` as a subclass of `CEntityEventStims` in the engine RTTI/class-factory system.
- `FUN_104ca500` (line 830924) — **RTTI_GetClassInfo_CPickup** — class self-registration getter (calls FUN_100016b0("CPickup", parent-getter)); registers `CPickup` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104cb380` (line 831690) — **RTTI_GetClassInfo_CPickupContainer** — class self-registration getter (calls FUN_100016b0("CPickupContainer", parent-getter)); registers `CPickupContainer` as a subclass of `CPickup` in the engine RTTI/class-factory system.
- `FUN_1076d290` (line 1203609) — **RTTI_GetClassInfo_CPickupEvent** — class self-registration getter (calls FUN_100016b0("CPickupEvent", parent-getter)); registers `CPickupEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_105d8160` (line 980658) — **RTTI_GetClassInfo_CPickupGadget** — class self-registration getter (calls FUN_100016b0("CPickupGadget", parent-getter)); registers `CPickupGadget` as a subclass of `CPickup` in the engine RTTI/class-factory system.
- `FUN_107f3e60` (line 1284536) — **RTTI_GetClassInfo_CPickupGrabEvent** — class self-registration getter (calls FUN_100016b0("CPickupGrabEvent", parent-getter)); registers `CPickupGrabEvent` as a subclass of `CBaseEvent` in the engine RTTI/class-factory system.
- `FUN_107f3f10` (line 1284594) — **RTTI_GetClassInfo_CPickupMemento** — class self-registration getter (calls FUN_100016b0("CPickupMemento", parent-getter)); registers `CPickupMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1076d2c0` (line 1203625) — **RTTI_GetClassInfo_CPickupScoutedEvent** — class self-registration getter (calls FUN_100016b0("CPickupScoutedEvent", parent-getter)); registers `CPickupScoutedEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_105d8130` (line 980642) — **RTTI_GetClassInfo_CPickupWeapon** — class self-registration getter (calls FUN_100016b0("CPickupWeapon", parent-getter)); registers `CPickupWeapon` as a subclass of `CPickup` in the engine RTTI/class-factory system.
- `FUN_10980530` (line 1502001) — **RTTI_GetClassInfo_CPierAnchor** — class self-registration getter (calls FUN_100016b0("CPierAnchor", parent-getter)); registers `CPierAnchor` as a subclass of `CGameAIObject` in the engine RTTI/class-factory system.
- `FUN_104a1a10` (line 803175) — **RTTI_GetClassInfo_CPlan** — class self-registration getter (calls FUN_100016b0("CPlan", parent-getter)); registers `CPlan` as a subclass of `CAction` in the engine RTTI/class-factory system.
- `FUN_101a71d0` (line 293149) — **RTTI_GetClassInfo_CPlanetComponent** — class self-registration getter (calls FUN_100016b0("CPlanetComponent", parent-getter)); registers `CPlanetComponent` as a subclass of `CRenderableComponent` in the engine RTTI/class-factory system.
- `FUN_101a71a0` (line 293133) — **RTTI_GetClassInfo_CPlanetEntity** — class self-registration getter (calls FUN_100016b0("CPlanetEntity", parent-getter)); registers `CPlanetEntity` as a subclass of `COmniEntity` in the engine RTTI/class-factory system.
- `FUN_104cb040` (line 831529) — **RTTI_GetClassInfo_CPlanetUIComponent** — class self-registration getter (calls FUN_100016b0("CPlanetUIComponent", parent-getter)); registers `CPlanetUIComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1055a850` (line 915279) — **RTTI_GetClassInfo_CPlantMemento** — class self-registration getter (calls FUN_100016b0("CPlantMemento", parent-getter)); registers `CPlantMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_104c9b70` (line 830508) — **RTTI_GetClassInfo_CPlantNetworkComponent** — class self-registration getter (calls FUN_100016b0("CPlantNetworkComponent", parent-getter)); registers `CPlantNetworkComponent` as a subclass of `CNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_10982c60` (line 1505345) — **RTTI_GetClassInfo_CPlayActionBrain** — class self-registration getter (calls FUN_100016b0("CPlayActionBrain", parent-getter)); registers `CPlayActionBrain` as a subclass of `CBrain` in the engine RTTI/class-factory system.
- `FUN_104c9530` (line 830282) — **RTTI_GetClassInfo_CPlaybackComponent** — class self-registration getter (calls FUN_100016b0("CPlaybackComponent", parent-getter)); registers `CPlaybackComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_10046110` (line 46355) — **RTTI_GetClassInfo_CPlayer** — class self-registration getter (calls FUN_100016b0("CPlayer", parent-getter)); registers `CPlayer` as a subclass of `IPlayer` in the engine RTTI/class-factory system.
- `FUN_1075f670` (line 1195833) — **RTTI_GetClassInfo_CPlayerChangeSpawningStrategyMessage** — class self-registration getter (calls FUN_100016b0("CPlayerChangeSpawningStrategyMessage", parent-getter)); registers `CPlayerChangeSpawningStrategyMessage` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_106e9360` (line 1130165) — **RTTI_GetClassInfo_CPlayerDescriptor** — class self-registration getter (calls FUN_100016b0("CPlayerDescriptor", parent-getter)); registers `CPlayerDescriptor` as a subclass of `CNetDescriptor` in the engine RTTI/class-factory system.
- `FUN_1075f6e0` (line 1195870) — **RTTI_GetClassInfo_CPlayerInfoMessage** — class self-registration getter (calls FUN_100016b0("CPlayerInfoMessage", parent-getter)); registers `CPlayerInfoMessage` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1075f600` (line 1195796) — **RTTI_GetClassInfo_CPlayerReadyToPlayMessage** — class self-registration getter (calls FUN_100016b0("CPlayerReadyToPlayMessage", parent-getter)); registers `CPlayerReadyToPlayMessage` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1075f530` (line 1195727) — **RTTI_GetClassInfo_CPlayerRequestTeamChange** — class self-registration getter (calls FUN_100016b0("CPlayerRequestTeamChange", parent-getter)); registers `CPlayerRequestTeamChange` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1075f590` (line 1195759) — **RTTI_GetClassInfo_CPlayerSGfxKitParts** — class self-registration getter (calls FUN_100016b0("CPlayerSGfxKitParts", parent-getter)); registers `CPlayerSGfxKitParts` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_10046180` (line 46392) — **RTTI_GetClassInfo_CPlayerService** — class self-registration getter (calls FUN_100016b0("CPlayerService", parent-getter)); registers `CPlayerService` as a subclass of `IPlayerService` in the engine RTTI/class-factory system.
- `FUN_104cb8a0` (line 831850) — **RTTI_GetClassInfo_CPlayerSoundAndFXComponent** — class self-registration getter (calls FUN_100016b0("CPlayerSoundAndFXComponent", parent-getter)); registers `CPlayerSoundAndFXComponent` as a subclass of `CPawnSoundAndFXComponent` in the engine RTTI/class-factory system.
- `FUN_105faaf0` (line 999922) — **RTTI_GetClassInfo_CPlayerSoundEvent** — class self-registration getter (calls FUN_100016b0("CPlayerSoundEvent", parent-getter)); registers `CPlayerSoundEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_106e9460` (line 1130204) — **RTTI_GetClassInfo_CPlayerSpawningDetails** — class self-registration getter (calls FUN_100016b0("CPlayerSpawningDetails", parent-getter)); registers `CPlayerSpawningDetails` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1075f4d0` (line 1195694) — **RTTI_GetClassInfo_CPlayerSpawningState** — class self-registration getter (calls FUN_100016b0("CPlayerSpawningState", parent-getter)); registers `CPlayerSpawningState` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1023add0` (line 395408) — **RTTI_GetClassInfo_CPlayerStatsFullNetDataContainer** — class self-registration getter (calls FUN_100016b0("CPlayerStatsFullNetDataContainer", parent-getter)); registers `CPlayerStatsFullNetDataContainer` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1023ae00` (line 395424) — **RTTI_GetClassInfo_CPlayerStatsNetDataContainer** — class self-registration getter (calls FUN_100016b0("CPlayerStatsNetDataContainer", parent-getter)); registers `CPlayerStatsNetDataContainer` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1075f450` (line 1195662) — **RTTI_GetClassInfo_CPlayerTeamInfo** — class self-registration getter (calls FUN_100016b0("CPlayerTeamInfo", parent-getter)); registers `CPlayerTeamInfo` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_101a6bf0` (line 292779) — **RTTI_GetClassInfo_CPositionLoggerComponent** — class self-registration getter (calls FUN_100016b0("CPositionLoggerComponent", parent-getter)); registers `CPositionLoggerComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_10534890` (line 894591) — **RTTI_GetClassInfo_CPostFXRequestEvent** — class self-registration getter (calls FUN_100016b0("CPostFXRequestEvent", parent-getter)); registers `CPostFXRequestEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1076cb30` (line 1203356) — **RTTI_GetClassInfo_CPostFxDatabase** — class self-registration getter (calls FUN_100016b0("CPostFxDatabase", parent-getter)); registers `CPostFxDatabase` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_107c3d40` (line 1254510) — **RTTI_GetClassInfo_CPostFxService** — class self-registration getter (calls FUN_100016b0("CPostFxService", parent-getter)); registers `CPostFxService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1022c360` (line 385338) — **RTTI_GetClassInfo_CPreLoadState** — class self-registration getter (calls FUN_100016b0("CPreLoadState", parent-getter)); registers `CPreLoadState` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_101a6770` (line 292395) — **RTTI_GetClassInfo_CPrefabEntity** — class self-registration getter (calls FUN_100016b0("CPrefabEntity", parent-getter)); registers `CPrefabEntity` as a subclass of `CEntity` in the engine RTTI/class-factory system.
- `FUN_101a7350` (line 293277) — **RTTI_GetClassInfo_CPrefabManager** — class self-registration getter (calls FUN_100016b0("CPrefabManager", parent-getter)); registers `CPrefabManager` as a subclass of `CSingletonEntity` in the engine RTTI/class-factory system.
- `FUN_104ca830` (line 831132) — **RTTI_GetClassInfo_CProximityTriggerComponent** — class self-registration getter (calls FUN_100016b0("CProximityTriggerComponent", parent-getter)); registers `CProximityTriggerComponent` as a subclass of `CBaseTriggerComponent` in the engine RTTI/class-factory system.
- `FUN_107ec200` (line 1280152) — **RTTI_GetClassInfo_CQueryProjectileSynchroEvent** — class self-registration getter (calls FUN_100016b0("CQueryProjectileSynchroEvent", parent-getter)); registers `CQueryProjectileSynchroEvent` as a subclass of `CBaseEvent` in the engine RTTI/class-factory system.
- `FUN_108a4160` (line 1389231) — **RTTI_GetClassInfo_CQuickMatchGatherOpCtn** — class self-registration getter (calls FUN_100016b0("CQuickMatchGatherOpCtn", parent-getter)); registers `CQuickMatchGatherOpCtn` as a subclass of `CGameOperationContainer` in the engine RTTI/class-factory system.
- `FUN_108a4310` (line 1389374) — **RTTI_GetClassInfo_CQuickMatchJoinCandidateOp** — class self-registration getter (calls FUN_100016b0("CQuickMatchJoinCandidateOp", parent-getter)); registers `CQuickMatchJoinCandidateOp` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_108a41d0` (line 1389268) — **RTTI_GetClassInfo_CQuickMatchJoinOpCtn** — class self-registration getter (calls FUN_100016b0("CQuickMatchJoinOpCtn", parent-getter)); registers `CQuickMatchJoinOpCtn` as a subclass of `CGameOperationContainer` in the engine RTTI/class-factory system.
- `FUN_108a4270` (line 1389321) — **RTTI_GetClassInfo_CQuickMatchPingCandidatesOp** — class self-registration getter (calls FUN_100016b0("CQuickMatchPingCandidatesOp", parent-getter)); registers `CQuickMatchPingCandidatesOp` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_108a4200` (line 1389284) — **RTTI_GetClassInfo_CQuickMatchRetrieveCandidatesOp** — class self-registration getter (calls FUN_100016b0("CQuickMatchRetrieveCandidatesOp", parent-getter)); registers `CQuickMatchRetrieveCandidatesOp` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_108a42e0` (line 1389358) — **RTTI_GetClassInfo_CQuickMatchSelectCandidateOp** — class self-registration getter (calls FUN_100016b0("CQuickMatchSelectCandidateOp", parent-getter)); registers `CQuickMatchSelectCandidateOp` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_101a6090` (line 291942) — **RTTI_GetClassInfo_CRadarComponent** — class self-registration getter (calls FUN_100016b0("CRadarComponent", parent-getter)); registers `CRadarComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a60c0` (line 291958) — **RTTI_GetClassInfo_CRadarComponent_Player** — class self-registration getter (calls FUN_100016b0("CRadarComponent_Player", parent-getter)); registers `CRadarComponent_Player` as a subclass of `CRadarComponent` in the engine RTTI/class-factory system.
- `FUN_10502e90` (line 865366) — **RTTI_GetClassInfo_CRainComponent** — class self-registration getter (calls FUN_100016b0("CRainComponent", parent-getter)); registers `CRainComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1021fc10` (line 378017) — **RTTI_GetClassInfo_CRandomPathFollower** — class self-registration getter (calls FUN_100016b0("CRandomPathFollower", parent-getter)); registers `CRandomPathFollower` as a subclass of `CPathFollower` in the engine RTTI/class-factory system.
- `FUN_104ca3b0` (line 830892) — **RTTI_GetClassInfo_CRandomShooterComponent** — class self-registration getter (calls FUN_100016b0("CRandomShooterComponent", parent-getter)); registers `CRandomShooterComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a7110` (line 293085) — **RTTI_GetClassInfo_CRealtreeClusterComponent** — class self-registration getter (calls FUN_100016b0("CRealtreeClusterComponent", parent-getter)); registers `CRealtreeClusterComponent` as a subclass of `CClusterComponent` in the engine RTTI/class-factory system.
- `FUN_101a70e0` (line 293069) — **RTTI_GetClassInfo_CRealtreeComponent** — class self-registration getter (calls FUN_100016b0("CRealtreeComponent", parent-getter)); registers `CRealtreeComponent` as a subclass of `CRenderableComponent` in the engine RTTI/class-factory system.
- `FUN_1027f150` (line 437359) — **RTTI_GetClassInfo_CRealtreeFx** — class self-registration getter (calls FUN_100016b0("CRealtreeFx", parent-getter)); registers `CRealtreeFx` as a subclass of `CNomadDbObject` in the engine RTTI/class-factory system.
- `FUN_101a6e00` (line 292867) — **RTTI_GetClassInfo_CRealtreeFxManager** — class self-registration getter (calls FUN_100016b0("CRealtreeFxManager", parent-getter)); registers `CRealtreeFxManager` as a subclass of `CSingletonEntity` in the engine RTTI/class-factory system.
- `FUN_1018ced0` (line 274507) — **RTTI_GetClassInfo_CRealtreeResource** — class self-registration getter (calls FUN_100016b0("CRealtreeResource", parent-getter)); registers `CRealtreeResource` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_102524e0` (line 409858) — **RTTI_GetClassInfo_CRemoveSEFactEvent** — class self-registration getter (calls FUN_100016b0("CRemoveSEFactEvent", parent-getter)); registers `CRemoveSEFactEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_10055b60` (line 58091) — **RTTI_GetClassInfo_CRenderableComponent** — class self-registration getter (calls FUN_100016b0("CRenderableComponent", parent-getter)); registers `CRenderableComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_105ced20` (line 975749) — **RTTI_GetClassInfo_CRescueManager** — class self-registration getter (calls FUN_100016b0("CRescueManager", parent-getter)); registers `CRescueManager` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_106d4090` (line 1117672) — **RTTI_GetClassInfo_CResetInputOperation** — class self-registration getter (calls FUN_100016b0("CResetInputOperation", parent-getter)); registers `CResetInputOperation` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_100af0d0` (line 123680) — **RTTI_GetClassInfo_CResource** — class self-registration getter (calls FUN_100016b0("CResource", parent-getter)); registers `CResource` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_100af110` (line 123699) — **RTTI_GetClassInfo_CResourceContainer** — class self-registration getter (calls FUN_100016b0("CResourceContainer", parent-getter)); registers `CResourceContainer` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_100c2330` (line 138514) — **RTTI_GetClassInfo_CResourceNotifier** — class self-registration getter (calls FUN_100016b0("CResourceNotifier", parent-getter)); registers `CResourceNotifier` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_102705d0` (line 429163) — **RTTI_GetClassInfo_CResourceWatch** — class self-registration getter (calls FUN_100016b0("CResourceWatch", parent-getter)); registers `CResourceWatch` as a subclass of `CResourceNotifier` in the engine RTTI/class-factory system.
- `FUN_101a70b0` (line 293053) — **RTTI_GetClassInfo_CRigidGraphicComponent** — class self-registration getter (calls FUN_100016b0("CRigidGraphicComponent", parent-getter)); registers `CRigidGraphicComponent` as a subclass of `CStaticGraphicComponent` in the engine RTTI/class-factory system.
- `FUN_1021c8d0` (line 375486) — **RTTI_GetClassInfo_CRigidPhysComponent** — class self-registration getter (calls FUN_100016b0("CRigidPhysComponent", parent-getter)); registers `CRigidPhysComponent` as a subclass of `CPhysComponent` in the engine RTTI/class-factory system.
- `FUN_102cf810` (line 490418) — **RTTI_GetClassInfo_CRigidPhysOnDamageEvent** — class self-registration getter (calls FUN_100016b0("CRigidPhysOnDamageEvent", parent-getter)); registers `CRigidPhysOnDamageEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_102cf870` (line 490450) — **RTTI_GetClassInfo_CRigidPhysOnDieEvent** — class self-registration getter (calls FUN_100016b0("CRigidPhysOnDieEvent", parent-getter)); registers `CRigidPhysOnDieEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_102cf840` (line 490434) — **RTTI_GetClassInfo_CRigidPhysOnStateChangeEvent** — class self-registration getter (calls FUN_100016b0("CRigidPhysOnStateChangeEvent", parent-getter)); registers `CRigidPhysOnStateChangeEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_104cc340` (line 832255) — **RTTI_GetClassInfo_CRoadSign** — class self-registration getter (calls FUN_100016b0("CRoadSign", parent-getter)); registers `CRoadSign` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104cbde0` (line 831994) — **RTTI_GetClassInfo_CRocket** — class self-registration getter (calls FUN_100016b0("CRocket", parent-getter)); registers `CRocket` as a subclass of `CGameObject` in the engine RTTI/class-factory system.
- `FUN_101fc930` (line 355119) — **RTTI_GetClassInfo_CSRLResource** — class self-registration getter (calls FUN_100016b0("CSRLResource", parent-getter)); registers `CSRLResource` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_104cafe0` (line 831497) — **RTTI_GetClassInfo_CSafeHouseComponent** — class self-registration getter (calls FUN_100016b0("CSafeHouseComponent", parent-getter)); registers `CSafeHouseComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_10500560` (line 863969) — **RTTI_GetClassInfo_CSafeHouseKillMercEvent** — class self-registration getter (calls FUN_100016b0("CSafeHouseKillMercEvent", parent-getter)); registers `CSafeHouseKillMercEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_104a19e0` (line 803159) — **RTTI_GetClassInfo_CScanner** — class self-registration getter (calls FUN_100016b0("CScanner", parent-getter)); registers `CScanner` as a subclass of `CTask` in the engine RTTI/class-factory system.
- `FUN_10984a50` (line 1507857) — **RTTI_GetClassInfo_CScannerAMPSuitUser** — class self-registration getter (calls FUN_100016b0("CScannerAMPSuitUser", parent-getter)); registers `CScannerAMPSuitUser` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10983260` (line 1505857) — **RTTI_GetClassInfo_CScannerAgentAimingAt** — class self-registration getter (calls FUN_100016b0("CScannerAgentAimingAt", parent-getter)); registers `CScannerAgentAimingAt` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10983230` (line 1505841) — **RTTI_GetClassInfo_CScannerAgentHasRaisedWeapon** — class self-registration getter (calls FUN_100016b0("CScannerAgentHasRaisedWeapon", parent-getter)); registers `CScannerAgentHasRaisedWeapon` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_109831a0` (line 1505793) — **RTTI_GetClassInfo_CScannerAgentIsVisible** — class self-registration getter (calls FUN_100016b0("CScannerAgentIsVisible", parent-getter)); registers `CScannerAgentIsVisible` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_109831d0` (line 1505809) — **RTTI_GetClassInfo_CScannerAgentSocialProximity** — class self-registration getter (calls FUN_100016b0("CScannerAgentSocialProximity", parent-getter)); registers `CScannerAgentSocialProximity` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10983200` (line 1505825) — **RTTI_GetClassInfo_CScannerAgentStaredown** — class self-registration getter (calls FUN_100016b0("CScannerAgentStaredown", parent-getter)); registers `CScannerAgentStaredown` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10983650` (line 1506193) — **RTTI_GetClassInfo_CScannerAimStrategy** — class self-registration getter (calls FUN_100016b0("CScannerAimStrategy", parent-getter)); registers `CScannerAimStrategy` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10982d80` (line 1505441) — **RTTI_GetClassInfo_CScannerAnimalHurt** — class self-registration getter (calls FUN_100016b0("CScannerAnimalHurt", parent-getter)); registers `CScannerAnimalHurt` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10983740` (line 1506273) — **RTTI_GetClassInfo_CScannerAnimalObstacleAhead** — class self-registration getter (calls FUN_100016b0("CScannerAnimalObstacleAhead", parent-getter)); registers `CScannerAnimalObstacleAhead` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10983710` (line 1506257) — **RTTI_GetClassInfo_CScannerAnimalThreatChanged** — class self-registration getter (calls FUN_100016b0("CScannerAnimalThreatChanged", parent-getter)); registers `CScannerAnimalThreatChanged` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_109836e0` (line 1506241) — **RTTI_GetClassInfo_CScannerAnimalThreatened** — class self-registration getter (calls FUN_100016b0("CScannerAnimalThreatened", parent-getter)); registers `CScannerAnimalThreatened` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10983080` (line 1505697) — **RTTI_GetClassInfo_CScannerArmyMemberRole** — class self-registration getter (calls FUN_100016b0("CScannerArmyMemberRole", parent-getter)); registers `CScannerArmyMemberRole` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10983050` (line 1505681) — **RTTI_GetClassInfo_CScannerArmyMemberState** — class self-registration getter (calls FUN_100016b0("CScannerArmyMemberState", parent-getter)); registers `CScannerArmyMemberState` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10983620` (line 1506177) — **RTTI_GetClassInfo_CScannerBestTargetChangedPos** — class self-registration getter (calls FUN_100016b0("CScannerBestTargetChangedPos", parent-getter)); registers `CScannerBestTargetChangedPos` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10980f80` (line 1502881) — **RTTI_GetClassInfo_CScannerBlackboardFact** — class self-registration getter (calls FUN_100016b0("CScannerBlackboardFact", parent-getter)); registers `CScannerBlackboardFact` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10983440` (line 1506017) — **RTTI_GetClassInfo_CScannerCanDisableSTPDynamicAvoidance** — class self-registration getter (calls FUN_100016b0("CScannerCanDisableSTPDynamicAvoidance", parent-getter)); registers `CScannerCanDisableSTPDynamicAvoidance` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10984a80` (line 1507873) — **RTTI_GetClassInfo_CScannerCannotEnterCombat** — class self-registration getter (calls FUN_100016b0("CScannerCannotEnterCombat", parent-getter)); registers `CScannerCannotEnterCombat` as a subclass of `CPawnBaseScanner` in the engine RTTI/class-factory system.
- `FUN_10984ab0` (line 1507889) — **RTTI_GetClassInfo_CScannerCharSheetStat** — class self-registration getter (calls FUN_100016b0("CScannerCharSheetStat", parent-getter)); registers `CScannerCharSheetStat` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10982db0` (line 1505457) — **RTTI_GetClassInfo_CScannerCheckSkill** — class self-registration getter (calls FUN_100016b0("CScannerCheckSkill", parent-getter)); registers `CScannerCheckSkill` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_109837d0` (line 1506321) — **RTTI_GetClassInfo_CScannerCheckValue** — class self-registration getter (calls FUN_100016b0("CScannerCheckValue", parent-getter)); registers `CScannerCheckValue` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10982ed0` (line 1505553) — **RTTI_GetClassInfo_CScannerDead** — class self-registration getter (calls FUN_100016b0("CScannerDead", parent-getter)); registers `CScannerDead` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_109832c0` (line 1505889) — **RTTI_GetClassInfo_CScannerDominoEvent** — class self-registration getter (calls FUN_100016b0("CScannerDominoEvent", parent-getter)); registers `CScannerDominoEvent` as a subclass of `CPawnBaseScanner` in the engine RTTI/class-factory system.
- `FUN_109835f0` (line 1506161) — **RTTI_GetClassInfo_CScannerEmotionStrategy** — class self-registration getter (calls FUN_100016b0("CScannerEmotionStrategy", parent-getter)); registers `CScannerEmotionStrategy` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10982e70` (line 1505521) — **RTTI_GetClassInfo_CScannerFactExist** — class self-registration getter (calls FUN_100016b0("CScannerFactExist", parent-getter)); registers `CScannerFactExist` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10982f60` (line 1505601) — **RTTI_GetClassInfo_CScannerFireProximity** — class self-registration getter (calls FUN_100016b0("CScannerFireProximity", parent-getter)); registers `CScannerFireProximity` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10983590` (line 1506129) — **RTTI_GetClassInfo_CScannerFireStrategy** — class self-registration getter (calls FUN_100016b0("CScannerFireStrategy", parent-getter)); registers `CScannerFireStrategy` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_109830b0` (line 1505713) — **RTTI_GetClassInfo_CScannerInFOV** — class self-registration getter (calls FUN_100016b0("CScannerInFOV", parent-getter)); registers `CScannerInFOV` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10983110` (line 1505745) — **RTTI_GetClassInfo_CScannerInterestLookAtType** — class self-registration getter (calls FUN_100016b0("CScannerInterestLookAtType", parent-getter)); registers `CScannerInterestLookAtType` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10983410` (line 1506001) — **RTTI_GetClassInfo_CScannerIsAIShootMeObjectValid** — class self-registration getter (calls FUN_100016b0("CScannerIsAIShootMeObjectValid", parent-getter)); registers `CScannerIsAIShootMeObjectValid` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10983020` (line 1505665) — **RTTI_GetClassInfo_CScannerIsAnimalMounted** — class self-registration getter (calls FUN_100016b0("CScannerIsAnimalMounted", parent-getter)); registers `CScannerIsAnimalMounted` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10982d50` (line 1505425) — **RTTI_GetClassInfo_CScannerIsDead** — class self-registration getter (calls FUN_100016b0("CScannerIsDead", parent-getter)); registers `CScannerIsDead` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10983380` (line 1505953) — **RTTI_GetClassInfo_CScannerIsInBuilding** — class self-registration getter (calls FUN_100016b0("CScannerIsInBuilding", parent-getter)); registers `CScannerIsInBuilding` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_109837a0` (line 1506305) — **RTTI_GetClassInfo_CScannerIsInDistance** — class self-registration getter (calls FUN_100016b0("CScannerIsInDistance", parent-getter)); registers `CScannerIsInDistance` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_109832f0` (line 1505905) — **RTTI_GetClassInfo_CScannerIsInVehicle** — class self-registration getter (calls FUN_100016b0("CScannerIsInVehicle", parent-getter)); registers `CScannerIsInVehicle` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10982ff0` (line 1505649) — **RTTI_GetClassInfo_CScannerIsOnMountedWeapon** — class self-registration getter (calls FUN_100016b0("CScannerIsOnMountedWeapon", parent-getter)); registers `CScannerIsOnMountedWeapon` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10982fc0` (line 1505633) — **RTTI_GetClassInfo_CScannerIsPosOnBarge** — class self-registration getter (calls FUN_100016b0("CScannerIsPosOnBarge", parent-getter)); registers `CScannerIsPosOnBarge` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10982f90` (line 1505617) — **RTTI_GetClassInfo_CScannerIsRotatedTowardsPos** — class self-registration getter (calls FUN_100016b0("CScannerIsRotatedTowardsPos", parent-getter)); registers `CScannerIsRotatedTowardsPos` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_109830e0` (line 1505729) — **RTTI_GetClassInfo_CScannerIsUnderFire** — class self-registration getter (calls FUN_100016b0("CScannerIsUnderFire", parent-getter)); registers `CScannerIsUnderFire` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_109835c0` (line 1506145) — **RTTI_GetClassInfo_CScannerLookStrategy** — class self-registration getter (calls FUN_100016b0("CScannerLookStrategy", parent-getter)); registers `CScannerLookStrategy` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10982f30` (line 1505585) — **RTTI_GetClassInfo_CScannerMovingPosition** — class self-registration getter (calls FUN_100016b0("CScannerMovingPosition", parent-getter)); registers `CScannerMovingPosition` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10983170` (line 1505777) — **RTTI_GetClassInfo_CScannerMutualGreeting** — class self-registration getter (calls FUN_100016b0("CScannerMutualGreeting", parent-getter)); registers `CScannerMutualGreeting` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10983350` (line 1505937) — **RTTI_GetClassInfo_CScannerNewTargetNeeded** — class self-registration getter (calls FUN_100016b0("CScannerNewTargetNeeded", parent-getter)); registers `CScannerNewTargetNeeded` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_109836b0` (line 1506225) — **RTTI_GetClassInfo_CScannerPawnInfo** — class self-registration getter (calls FUN_100016b0("CScannerPawnInfo", parent-getter)); registers `CScannerPawnInfo` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10983290` (line 1505873) — **RTTI_GetClassInfo_CScannerPawnSenses** — class self-registration getter (calls FUN_100016b0("CScannerPawnSenses", parent-getter)); registers `CScannerPawnSenses` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_109833e0` (line 1505985) — **RTTI_GetClassInfo_CScannerRiskPoint** — class self-registration getter (calls FUN_100016b0("CScannerRiskPoint", parent-getter)); registers `CScannerRiskPoint` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10983320` (line 1505921) — **RTTI_GetClassInfo_CScannerSideLookOpening** — class self-registration getter (calls FUN_100016b0("CScannerSideLookOpening", parent-getter)); registers `CScannerSideLookOpening` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10983140` (line 1505761) — **RTTI_GetClassInfo_CScannerSocialBehavior** — class self-registration getter (calls FUN_100016b0("CScannerSocialBehavior", parent-getter)); registers `CScannerSocialBehavior` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_109833b0` (line 1505969) — **RTTI_GetClassInfo_CScannerSocialRegion** — class self-registration getter (calls FUN_100016b0("CScannerSocialRegion", parent-getter)); registers `CScannerSocialRegion` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10983680` (line 1506209) — **RTTI_GetClassInfo_CScannerSpecialStrategy** — class self-registration getter (calls FUN_100016b0("CScannerSpecialStrategy", parent-getter)); registers `CScannerSpecialStrategy` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10982f00` (line 1505569) — **RTTI_GetClassInfo_CScannerTargetVisible** — class self-registration getter (calls FUN_100016b0("CScannerTargetVisible", parent-getter)); registers `CScannerTargetVisible` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_109842b0` (line 1507249) — **RTTI_GetClassInfo_CScannerVehicleCannotReachTarget** — class self-registration getter (calls FUN_100016b0("CScannerVehicleCannotReachTarget", parent-getter)); registers `CScannerVehicleCannotReachTarget` as a subclass of `CVehicleScanner` in the engine RTTI/class-factory system.
- `FUN_109841f0` (line 1507185) — **RTTI_GetClassInfo_CScannerVehicleIntruderAboard** — class self-registration getter (calls FUN_100016b0("CScannerVehicleIntruderAboard", parent-getter)); registers `CScannerVehicleIntruderAboard` as a subclass of `CVehicleScanner` in the engine RTTI/class-factory system.
- `FUN_10984250` (line 1507217) — **RTTI_GetClassInfo_CScannerVehicleIsFunctional** — class self-registration getter (calls FUN_100016b0("CScannerVehicleIsFunctional", parent-getter)); registers `CScannerVehicleIsFunctional` as a subclass of `CVehicleScanner` in the engine RTTI/class-factory system.
- `FUN_10984280` (line 1507233) — **RTTI_GetClassInfo_CScannerVehicleIsMounted** — class self-registration getter (calls FUN_100016b0("CScannerVehicleIsMounted", parent-getter)); registers `CScannerVehicleIsMounted` as a subclass of `CVehicleScanner` in the engine RTTI/class-factory system.
- `FUN_10984220` (line 1507201) — **RTTI_GetClassInfo_CScannerVehicleMergePosReached** — class self-registration getter (calls FUN_100016b0("CScannerVehicleMergePosReached", parent-getter)); registers `CScannerVehicleMergePosReached` as a subclass of `CVehicleScanner` in the engine RTTI/class-factory system.
- `FUN_109841c0` (line 1507169) — **RTTI_GetClassInfo_CScannerVehiclePierAnchor** — class self-registration getter (calls FUN_100016b0("CScannerVehiclePierAnchor", parent-getter)); registers `CScannerVehiclePierAnchor` as a subclass of `CVehicleScanner` in the engine RTTI/class-factory system.
- `FUN_10983800` (line 1506337) — **RTTI_GetClassInfo_CScannerVehicleStandBy** — class self-registration getter (calls FUN_100016b0("CScannerVehicleStandBy", parent-getter)); registers `CScannerVehicleStandBy` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10982ea0` (line 1505537) — **RTTI_GetClassInfo_CScannerVisualThreat** — class self-registration getter (calls FUN_100016b0("CScannerVisualThreat", parent-getter)); registers `CScannerVisualThreat` as a subclass of `CPawnScanner` in the engine RTTI/class-factory system.
- `FUN_10983770` (line 1506289) — **RTTI_GetClassInfo_CScannerWalkDistance** — class self-registration getter (calls FUN_100016b0("CScannerWalkDistance", parent-getter)); registers `CScannerWalkDistance` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10635b20` (line 1032788) — **RTTI_GetClassInfo_CScoreboardService** — class self-registration getter (calls FUN_100016b0("CScoreboardService", parent-getter)); registers `CScoreboardService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_101a5830` (line 291350) — **RTTI_GetClassInfo_CScriptCallbackComponent** — class self-registration getter (calls FUN_100016b0("CScriptCallbackComponent", parent-getter)); registers `CScriptCallbackComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_102bd490` (line 478430) — **RTTI_GetClassInfo_CScriptEntityId** — class self-registration getter (calls FUN_100016b0("CScriptEntityId", parent-getter)); registers `CScriptEntityId` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_1022a610` (line 384051) — **RTTI_GetClassInfo_CScriptEvent** — class self-registration getter (calls FUN_100016b0("CScriptEvent", parent-getter)); registers `CScriptEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_101a0590` (line 287330) — **RTTI_GetClassInfo_CScriptService** — class self-registration getter (calls FUN_100016b0("CScriptService", parent-getter)); registers `CScriptService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_104cc2e0` (line 832239) — **RTTI_GetClassInfo_CScriptedScenePrefabEntity** — class self-registration getter (calls FUN_100016b0("CScriptedScenePrefabEntity", parent-getter)); registers `CScriptedScenePrefabEntity` as a subclass of `CPrefabEntity` in the engine RTTI/class-factory system.
- `FUN_10204d20` (line 360602) — **RTTI_GetClassInfo_CSectorDataResource** — class self-registration getter (calls FUN_100016b0("CSectorDataResource", parent-getter)); registers `CSectorDataResource` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_10204bd0` (line 360498) — **RTTI_GetClassInfo_CSectorDescriptorResource** — class self-registration getter (calls FUN_100016b0("CSectorDescriptorResource", parent-getter)); registers `CSectorDescriptorResource` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_101a6060` (line 291926) — **RTTI_GetClassInfo_CSectorEntity** — class self-registration getter (calls FUN_100016b0("CSectorEntity", parent-getter)); registers `CSectorEntity` as a subclass of `CEntity` in the engine RTTI/class-factory system.
- `FUN_10204c00` (line 360514) — **RTTI_GetClassInfo_CSectorPreloadResource** — class self-registration getter (calls FUN_100016b0("CSectorPreloadResource", parent-getter)); registers `CSectorPreloadResource` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_103b54d0` (line 643567) — **RTTI_GetClassInfo_CSectorResource** — class self-registration getter (calls FUN_100016b0("CSectorResource", parent-getter)); registers `CSectorResource` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_10204d50` (line 360618) — **RTTI_GetClassInfo_CSectorSpawnCategory** — class self-registration getter (calls FUN_100016b0("CSectorSpawnCategory", parent-getter)); registers `CSectorSpawnCategory` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_1012e430` (line 209179) — **RTTI_GetClassInfo_CSerializeNetDataVisitor** — class self-registration getter (calls FUN_100016b0("CSerializeNetDataVisitor", parent-getter)); registers `CSerializeNetDataVisitor` as a subclass of `CNetDataVisitor` in the engine RTTI/class-factory system.
- `FUN_1012b0e0` (line 206253) — **RTTI_GetClassInfo_CServiceMessageDataContainer** — class self-registration getter (calls FUN_100016b0("CServiceMessageDataContainer", parent-getter)); registers `CServiceMessageDataContainer` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_1012b010` (line 206203) — **RTTI_GetClassInfo_CServiceUnicastDataContainer** — class self-registration getter (calls FUN_100016b0("CServiceUnicastDataContainer", parent-getter)); registers `CServiceUnicastDataContainer` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_10e8ec30` (line 2401410) — **RTTI_GetClassInfo_CSessionCreateGameOperation** — class self-registration getter (calls FUN_100016b0("CSessionCreateGameOperation", parent-getter)); registers `CSessionCreateGameOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8ec00` (line 2401394) — **RTTI_GetClassInfo_CSessionCreateOperation** — class self-registration getter (calls FUN_100016b0("CSessionCreateOperation", parent-getter)); registers `CSessionCreateOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8ec60` (line 2401426) — **RTTI_GetClassInfo_CSessionCreateServiceOperation** — class self-registration getter (calls FUN_100016b0("CSessionCreateServiceOperation", parent-getter)); registers `CSessionCreateServiceOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8a630` (line 2396840) — **RTTI_GetClassInfo_CSessionDeleteGameOperation** — class self-registration getter (calls FUN_100016b0("CSessionDeleteGameOperation", parent-getter)); registers `CSessionDeleteGameOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8ee80` (line 2401619) — **RTTI_GetClassInfo_CSessionDeleteOperation** — class self-registration getter (calls FUN_100016b0("CSessionDeleteOperation", parent-getter)); registers `CSessionDeleteOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8eef0` (line 2401661) — **RTTI_GetClassInfo_CSessionDeleteServiceOperation** — class self-registration getter (calls FUN_100016b0("CSessionDeleteServiceOperation", parent-getter)); registers `CSessionDeleteServiceOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8ebd0` (line 2401378) — **RTTI_GetClassInfo_CSessionDescriptor** — class self-registration getter (calls FUN_100016b0("CSessionDescriptor", parent-getter)); registers `CSessionDescriptor` as a subclass of `CNetDescriptor` in the engine RTTI/class-factory system.
- `FUN_10e8efe0` (line 2401748) — **RTTI_GetClassInfo_CSessionEndOperation** — class self-registration getter (calls FUN_100016b0("CSessionEndOperation", parent-getter)); registers `CSessionEndOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e89ed0` (line 2396316) — **RTTI_GetClassInfo_CSessionInfo** — class self-registration getter (calls FUN_100016b0("CSessionInfo", parent-getter)); registers `CSessionInfo` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_10e97270` (line 2407959) — **RTTI_GetClassInfo_CSessionInfo_RdV** — class self-registration getter (calls FUN_100016b0("CSessionInfo_RdV", parent-getter)); registers `CSessionInfo_RdV` as a subclass of `CSessionInfo` in the engine RTTI/class-factory system.
- `FUN_10e8ed80` (line 2401529) — **RTTI_GetClassInfo_CSessionJoinGameOperation** — class self-registration getter (calls FUN_100016b0("CSessionJoinGameOperation", parent-getter)); registers `CSessionJoinGameOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8ed30` (line 2401500) — **RTTI_GetClassInfo_CSessionJoinOperation** — class self-registration getter (calls FUN_100016b0("CSessionJoinOperation", parent-getter)); registers `CSessionJoinOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8edd0` (line 2401558) — **RTTI_GetClassInfo_CSessionJoinServiceOperation** — class self-registration getter (calls FUN_100016b0("CSessionJoinServiceOperation", parent-getter)); registers `CSessionJoinServiceOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8ee20` (line 2401587) — **RTTI_GetClassInfo_CSessionLoginOperation** — class self-registration getter (calls FUN_100016b0("CSessionLoginOperation", parent-getter)); registers `CSessionLoginOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8ee50` (line 2401603) — **RTTI_GetClassInfo_CSessionLogoutOperation** — class self-registration getter (calls FUN_100016b0("CSessionLogoutOperation", parent-getter)); registers `CSessionLogoutOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8f030` (line 2401777) — **RTTI_GetClassInfo_CSessionMigrateOperation** — class self-registration getter (calls FUN_100016b0("CSessionMigrateOperation", parent-getter)); registers `CSessionMigrateOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8a600` (line 2396824) — **RTTI_GetClassInfo_CSessionOperation** — class self-registration getter (calls FUN_100016b0("CSessionOperation", parent-getter)); registers `CSessionOperation` as a subclass of `COperation` in the engine RTTI/class-factory system.
- `FUN_10ea9b60` (line 2420397) — **RTTI_GetClassInfo_CSessionQueryOperation** — class self-registration getter (calls FUN_100016b0("CSessionQueryOperation", parent-getter)); registers `CSessionQueryOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8ece0` (line 2401471) — **RTTI_GetClassInfo_CSessionSearchOperation** — class self-registration getter (calls FUN_100016b0("CSessionSearchOperation", parent-getter)); registers `CSessionSearchOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8f080` (line 2401806) — **RTTI_GetClassInfo_CSessionSendInviteOperation** — class self-registration getter (calls FUN_100016b0("CSessionSendInviteOperation", parent-getter)); registers `CSessionSendInviteOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8ef40` (line 2401690) — **RTTI_GetClassInfo_CSessionStartNetOperation** — class self-registration getter (calls FUN_100016b0("CSessionStartNetOperation", parent-getter)); registers `CSessionStartNetOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8ef90` (line 2401719) — **RTTI_GetClassInfo_CSessionStartOperation** — class self-registration getter (calls FUN_100016b0("CSessionStartOperation", parent-getter)); registers `CSessionStartOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_10e8ec90` (line 2401442) — **RTTI_GetClassInfo_CSessionUpdateOperation** — class self-registration getter (calls FUN_100016b0("CSessionUpdateOperation", parent-getter)); registers `CSessionUpdateOperation` as a subclass of `CSessionOperation` in the engine RTTI/class-factory system.
- `FUN_107e6510` (line 1276429) — **RTTI_GetClassInfo_CSetNetInstanceIdEvent** — class self-registration getter (calls FUN_100016b0("CSetNetInstanceIdEvent", parent-getter)); registers `CSetNetInstanceIdEvent` as a subclass of `CBaseEvent` in the engine RTTI/class-factory system.
- `FUN_106d3fe0` (line 1117640) — **RTTI_GetClassInfo_CShaderPreloadOperation** — class self-registration getter (calls FUN_100016b0("CShaderPreloadOperation", parent-getter)); registers `CShaderPreloadOperation` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d4010` (line 1117656) — **RTTI_GetClassInfo_CShaderPreloadOperationBoot** — class self-registration getter (calls FUN_100016b0("CShaderPreloadOperationBoot", parent-getter)); registers `CShaderPreloadOperationBoot` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_103b5500` (line 643583) — **RTTI_GetClassInfo_CShortRangeResource** — class self-registration getter (calls FUN_100016b0("CShortRangeResource", parent-getter)); registers `CShortRangeResource` as a subclass of `CSectorResource` in the engine RTTI/class-factory system.
- `FUN_101a5ee0` (line 291798) — **RTTI_GetClassInfo_CSimpleAnimationComponent** — class self-registration getter (calls FUN_100016b0("CSimpleAnimationComponent", parent-getter)); registers `CSimpleAnimationComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1024a810` (line 406562) — **RTTI_GetClassInfo_CSimpleEntityEvent** — class self-registration getter (calls FUN_100016b0("CSimpleEntityEvent", parent-getter)); registers `CSimpleEntityEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_101a5fa0` (line 291862) — **RTTI_GetClassInfo_CSimpleNetworkComponent** — class self-registration getter (calls FUN_100016b0("CSimpleNetworkComponent", parent-getter)); registers `CSimpleNetworkComponent` as a subclass of `CNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_101a7140` (line 293101) — **RTTI_GetClassInfo_CSimplePrimitiveComponent** — class self-registration getter (calls FUN_100016b0("CSimplePrimitiveComponent", parent-getter)); registers `CSimplePrimitiveComponent` as a subclass of `CRenderableComponent` in the engine RTTI/class-factory system.
- `FUN_101a6680` (line 292315) — **RTTI_GetClassInfo_CSingletonEntity** — class self-registration getter (calls FUN_100016b0("CSingletonEntity", parent-getter)); registers `CSingletonEntity` as a subclass of `COmniEntity` in the engine RTTI/class-factory system.
- `FUN_101b8e20` (line 306634) — **RTTI_GetClassInfo_CSkeletonResource** — class self-registration getter (calls FUN_100016b0("CSkeletonResource", parent-getter)); registers `CSkeletonResource` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_10980410` (line 1501905) — **RTTI_GetClassInfo_CSmartTerrain** — class self-registration getter (calls FUN_100016b0("CSmartTerrain", parent-getter)); registers `CSmartTerrain` as a subclass of `CDynamicGameAIObject` in the engine RTTI/class-factory system.
- `FUN_10980440` (line 1501921) — **RTTI_GetClassInfo_CSmartTerrainManager** — class self-registration getter (calls FUN_100016b0("CSmartTerrainManager", parent-getter)); registers `CSmartTerrainManager` as a subclass of `CSingletonEntity` in the engine RTTI/class-factory system.
- `FUN_109804d0` (line 1501969) — **RTTI_GetClassInfo_CSniperPoint** — class self-registration getter (calls FUN_100016b0("CSniperPoint", parent-getter)); registers `CSniperPoint` as a subclass of `CGameAIObject` in the engine RTTI/class-factory system.
- `FUN_101a6b30` (line 292715) — **RTTI_GetClassInfo_CSoundComponent** — class self-registration getter (calls FUN_100016b0("CSoundComponent", parent-getter)); registers `CSoundComponent` as a subclass of `CSoundObjectCallbacksComponent` in the engine RTTI/class-factory system.
- `FUN_101b9370` (line 307070) — **RTTI_GetClassInfo_CSoundEvent** — class self-registration getter (calls FUN_100016b0("CSoundEvent", parent-getter)); registers `CSoundEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_101a6b60` (line 292731) — **RTTI_GetClassInfo_CSoundLineComponent** — class self-registration getter (calls FUN_100016b0("CSoundLineComponent", parent-getter)); registers `CSoundLineComponent` as a subclass of `CBasicShapeComponent` in the engine RTTI/class-factory system.
- `FUN_101a7380` (line 293293) — **RTTI_GetClassInfo_CSoundManager** — class self-registration getter (calls FUN_100016b0("CSoundManager", parent-getter)); registers `CSoundManager` as a subclass of `CSingletonEntity` in the engine RTTI/class-factory system.
- `FUN_101a6b00` (line 292699) — **RTTI_GetClassInfo_CSoundObjectCallbacksComponent** — class self-registration getter (calls FUN_100016b0("CSoundObjectCallbacksComponent", parent-getter)); registers `CSoundObjectCallbacksComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_102df2b0` (line 499436) — **RTTI_GetClassInfo_CSoundResource** — class self-registration getter (calls FUN_100016b0("CSoundResource", parent-getter)); registers `CSoundResource` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_101a6b90` (line 292747) — **RTTI_GetClassInfo_CSoundShapeComponent** — class self-registration getter (calls FUN_100016b0("CSoundShapeComponent", parent-getter)); registers `CSoundShapeComponent` as a subclass of `IShapeComponent` in the engine RTTI/class-factory system.
- `FUN_1025a560` (line 414791) — **RTTI_GetClassInfo_CSoundSwitchValueEvent** — class self-registration getter (calls FUN_100016b0("CSoundSwitchValueEvent", parent-getter)); registers `CSoundSwitchValueEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_101a6e60` (line 292899) — **RTTI_GetClassInfo_CSpawnPoint** — class self-registration getter (calls FUN_100016b0("CSpawnPoint", parent-getter)); registers `CSpawnPoint` as a subclass of `COmniMapEntity` in the engine RTTI/class-factory system.
- `FUN_101a6f50` (line 292960) — **RTTI_GetClassInfo_CSpawnPointBlue** — class self-registration getter (calls FUN_100016b0("CSpawnPointBlue", parent-getter)); registers `CSpawnPointBlue` as a subclass of `CSpawnPoint` in the engine RTTI/class-factory system.
- `FUN_101a6fd0` (line 293005) — **RTTI_GetClassInfo_CSpawnPointBlueStart** — class self-registration getter (calls FUN_100016b0("CSpawnPointBlueStart", parent-getter)); registers `CSpawnPointBlueStart` as a subclass of `CSpawnPointBlue` in the engine RTTI/class-factory system.
- `FUN_101a6e90` (line 292915) — **RTTI_GetClassInfo_CSpawnPointBuddy** — class self-registration getter (calls FUN_100016b0("CSpawnPointBuddy", parent-getter)); registers `CSpawnPointBuddy` as a subclass of `CSpawnPoint` in the engine RTTI/class-factory system.
- `FUN_101a6f00` (line 292931) — **RTTI_GetClassInfo_CSpawnPointRed** — class self-registration getter (calls FUN_100016b0("CSpawnPointRed", parent-getter)); registers `CSpawnPointRed` as a subclass of `CSpawnPoint` in the engine RTTI/class-factory system.
- `FUN_101a6fa0` (line 292989) — **RTTI_GetClassInfo_CSpawnPointRedStart** — class self-registration getter (calls FUN_100016b0("CSpawnPointRedStart", parent-getter)); registers `CSpawnPointRedStart` as a subclass of `CSpawnPointRed` in the engine RTTI/class-factory system.
- `FUN_1005aa00` (line 61706) — **RTTI_GetClassInfo_CSpawnPointService** — class self-registration getter (calls FUN_100016b0("CSpawnPointService", parent-getter)); registers `CSpawnPointService` as a subclass of `ISpawnPointService` in the engine RTTI/class-factory system.
- `FUN_101a7000` (line 293021) — **RTTI_GetClassInfo_CSpawnPointSpectator** — class self-registration getter (calls FUN_100016b0("CSpawnPointSpectator", parent-getter)); registers `CSpawnPointSpectator` as a subclass of `CSpawnPoint` in the engine RTTI/class-factory system.
- `FUN_10567940` (line 921903) — **RTTI_GetClassInfo_CSpawnerUnitFactory** — class self-registration getter (calls FUN_100016b0("CSpawnerUnitFactory", parent-getter)); registers `CSpawnerUnitFactory` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_105679b0` (line 921919) — **RTTI_GetClassInfo_CSpawnerUnitFactory_Single** — class self-registration getter (calls FUN_100016b0("CSpawnerUnitFactory_Single", parent-getter)); registers `CSpawnerUnitFactory_Single` as a subclass of `CSpawnerUnitFactory` in the engine RTTI/class-factory system.
- `FUN_104cab30` (line 831273) — **RTTI_GetClassInfo_CSpecialEventPoint** — class self-registration getter (calls FUN_100016b0("CSpecialEventPoint", parent-getter)); registers `CSpecialEventPoint` as a subclass of `CEntity` in the engine RTTI/class-factory system.
- `FUN_1075df30` (line 1194648) — **RTTI_GetClassInfo_CSpectatorPlayer** — class self-registration getter (calls FUN_100016b0("CSpectatorPlayer", parent-getter)); registers `CSpectatorPlayer` as a subclass of `IPlayer` in the engine RTTI/class-factory system.
- `FUN_101a7170` (line 293117) — **RTTI_GetClassInfo_CSplinePrimitiveComponent** — class self-registration getter (calls FUN_100016b0("CSplinePrimitiveComponent", parent-getter)); registers `CSplinePrimitiveComponent` as a subclass of `CRenderableComponent` in the engine RTTI/class-factory system.
- `FUN_104c92f0` (line 830187) — **RTTI_GetClassInfo_CStateMachineBlobResource** — class self-registration getter (calls FUN_100016b0("CStateMachineBlobResource", parent-getter)); registers `CStateMachineBlobResource` as a subclass of `CStateMachineResource` in the engine RTTI/class-factory system.
- `FUN_104c92c0` (line 830171) — **RTTI_GetClassInfo_CStateMachineResource** — class self-registration getter (calls FUN_100016b0("CStateMachineResource", parent-getter)); registers `CStateMachineResource` as a subclass of `CResourceContainer` in the engine RTTI/class-factory system.
- `FUN_10258750` (line 413744) — **RTTI_GetClassInfo_CStaticClusterPhysComponent** — class self-registration getter (calls FUN_100016b0("CStaticClusterPhysComponent", parent-getter)); registers `CStaticClusterPhysComponent` as a subclass of `CPhysComponent` in the engine RTTI/class-factory system.
- `FUN_101a6c20` (line 292795) — **RTTI_GetClassInfo_CStaticDecalComponent** — class self-registration getter (calls FUN_100016b0("CStaticDecalComponent", parent-getter)); registers `CStaticDecalComponent` as a subclass of `CRenderableComponent` in the engine RTTI/class-factory system.
- `FUN_101a7080` (line 293037) — **RTTI_GetClassInfo_CStaticGraphicComponent** — class self-registration getter (calls FUN_100016b0("CStaticGraphicComponent", parent-getter)); registers `CStaticGraphicComponent` as a subclass of `CBaseGraphicComponent` in the engine RTTI/class-factory system.
- `FUN_10204c60` (line 360546) — **RTTI_GetClassInfo_CStaticPhysComponent** — class self-registration getter (calls FUN_100016b0("CStaticPhysComponent", parent-getter)); registers `CStaticPhysComponent` as a subclass of `CPhysComponent` in the engine RTTI/class-factory system.
- `FUN_104cb010` (line 831513) — **RTTI_GetClassInfo_CStealthComponent** — class self-registration getter (calls FUN_100016b0("CStealthComponent", parent-getter)); registers `CStealthComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_105e7a80` (line 988721) — **RTTI_GetClassInfo_CStickyFlameEvent** — class self-registration getter (calls FUN_100016b0("CStickyFlameEvent", parent-getter)); registers `CStickyFlameEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1068bee0` (line 1081387) — **RTTI_GetClassInfo_CStimEffectTable** — class self-registration getter (calls FUN_100016b0("CStimEffectTable", parent-getter)); registers `CStimEffectTable` as a subclass of `CBaseEntity` in the engine RTTI/class-factory system.
- `FUN_1076d080` (line 1203481) — **RTTI_GetClassInfo_CStimsEmitterComponent** — class self-registration getter (calls FUN_100016b0("CStimsEmitterComponent", parent-getter)); registers `CStimsEmitterComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1097f3a0` (line 1501408) — **RTTI_GetClassInfo_CStingbatAgent** — class self-registration getter (calls FUN_100016b0("CStingbatAgent", parent-getter)); registers `CStingbatAgent` as a subclass of `CBtzAnimalAgent` in the engine RTTI/class-factory system.
- `FUN_101b8ef0` (line 306702) — **RTTI_GetClassInfo_CStopDialogEvent** — class self-registration getter (calls FUN_100016b0("CStopDialogEvent", parent-getter)); registers `CStopDialogEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_104cab90` (line 831305) — **RTTI_GetClassInfo_CStrategicPoint** — class self-registration getter (calls FUN_100016b0("CStrategicPoint", parent-getter)); registers `CStrategicPoint` as a subclass of `CTagPoint` in the engine RTTI/class-factory system.
- `FUN_1067aed0` (line 1072408) — **RTTI_GetClassInfo_CSuccessHitEvent** — class self-registration getter (calls FUN_100016b0("CSuccessHitEvent", parent-getter)); registers `CSuccessHitEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_101a58c0` (line 291398) — **RTTI_GetClassInfo_CSuicideComponent** — class self-registration getter (calls FUN_100016b0("CSuicideComponent", parent-getter)); registers `CSuicideComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1023e370` (line 397768) — **RTTI_GetClassInfo_CSystemMessageText** — class self-registration getter (calls FUN_100016b0("CSystemMessageText", parent-getter)); registers `CSystemMessageText` as a subclass of `CGameMessageText` in the engine RTTI/class-factory system.
- `FUN_10647740` (line 1039750) — **RTTI_GetClassInfo_CTDMSpawnPointService** — class self-registration getter (calls FUN_100016b0("CTDMSpawnPointService", parent-getter)); registers `CTDMSpawnPointService` as a subclass of `CDMSpawnPointService` in the engine RTTI/class-factory system.
- `FUN_104cab60` (line 831289) — **RTTI_GetClassInfo_CTagPoint** — class self-registration getter (calls FUN_100016b0("CTagPoint", parent-getter)); registers `CTagPoint` as a subclass of `CEntity` in the engine RTTI/class-factory system.
- `FUN_1097f370` (line 1501392) — **RTTI_GetClassInfo_CTapirusAgent** — class self-registration getter (calls FUN_100016b0("CTapirusAgent", parent-getter)); registers `CTapirusAgent` as a subclass of `CBtzAnimalAgent` in the engine RTTI/class-factory system.
- `FUN_104a1950` (line 803111) — **RTTI_GetClassInfo_CTask** — class self-registration getter (calls FUN_100016b0("CTask", parent-getter)); registers `CTask` as a subclass of `CTaskRoot` in the engine RTTI/class-factory system.
- `FUN_109846f0` (line 1507569) — **RTTI_GetClassInfo_CTaskAMPSuitAim** — class self-registration getter (calls FUN_100016b0("CTaskAMPSuitAim", parent-getter)); registers `CTaskAMPSuitAim` as a subclass of `CAMPSuitAction` in the engine RTTI/class-factory system.
- `FUN_10984720` (line 1507585) — **RTTI_GetClassInfo_CTaskAMPSuitChase** — class self-registration getter (calls FUN_100016b0("CTaskAMPSuitChase", parent-getter)); registers `CTaskAMPSuitChase` as a subclass of `CAMPSuitAction` in the engine RTTI/class-factory system.
- `FUN_10984690` (line 1507537) — **RTTI_GetClassInfo_CTaskAMPSuitPathFollow** — class self-registration getter (calls FUN_100016b0("CTaskAMPSuitPathFollow", parent-getter)); registers `CTaskAMPSuitPathFollow` as a subclass of `CAMPSuitAction` in the engine RTTI/class-factory system.
- `FUN_109846c0` (line 1507553) — **RTTI_GetClassInfo_CTaskAMPSuitSelectWeapon** — class self-registration getter (calls FUN_100016b0("CTaskAMPSuitSelectWeapon", parent-getter)); registers `CTaskAMPSuitSelectWeapon` as a subclass of `CAMPSuitAction` in the engine RTTI/class-factory system.
- `FUN_10984750` (line 1507601) — **RTTI_GetClassInfo_CTaskAMPSuitShoot** — class self-registration getter (calls FUN_100016b0("CTaskAMPSuitShoot", parent-getter)); registers `CTaskAMPSuitShoot` as a subclass of `CAMPSuitAction` in the engine RTTI/class-factory system.
- `FUN_10982240` (line 1504481) — **RTTI_GetClassInfo_CTaskActivateInfamyPose** — class self-registration getter (calls FUN_100016b0("CTaskActivateInfamyPose", parent-getter)); registers `CTaskActivateInfamyPose` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10982cf0` (line 1505393) — **RTTI_GetClassInfo_CTaskActivateSocialSTP** — class self-registration getter (calls FUN_100016b0("CTaskActivateSocialSTP", parent-getter)); registers `CTaskActivateSocialSTP` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10980890` (line 1502289) — **RTTI_GetClassInfo_CTaskAimAt** — class self-registration getter (calls FUN_100016b0("CTaskAimAt", parent-getter)); registers `CTaskAimAt` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10984160` (line 1507137) — **RTTI_GetClassInfo_CTaskAirAnimalVehicleControl** — class self-registration getter (calls FUN_100016b0("CTaskAirAnimalVehicleControl", parent-getter)); registers `CTaskAirAnimalVehicleControl` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_109839b0` (line 1506481) — **RTTI_GetClassInfo_CTaskAirPathFollow** — class self-registration getter (calls FUN_100016b0("CTaskAirPathFollow", parent-getter)); registers `CTaskAirPathFollow` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_109842e0` (line 1507265) — **RTTI_GetClassInfo_CTaskAnimalAttack** — class self-registration getter (calls FUN_100016b0("CTaskAnimalAttack", parent-getter)); registers `CTaskAnimalAttack` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10982de0` (line 1505473) — **RTTI_GetClassInfo_CTaskAnimalCheckVisionStatus** — class self-registration getter (calls FUN_100016b0("CTaskAnimalCheckVisionStatus", parent-getter)); registers `CTaskAnimalCheckVisionStatus` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10983920` (line 1506433) — **RTTI_GetClassInfo_CTaskAnimalCommand** — class self-registration getter (calls FUN_100016b0("CTaskAnimalCommand", parent-getter)); registers `CTaskAnimalCommand` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109838f0` (line 1506417) — **RTTI_GetClassInfo_CTaskAnimalPathFollow** — class self-registration getter (calls FUN_100016b0("CTaskAnimalPathFollow", parent-getter)); registers `CTaskAnimalPathFollow` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10983950` (line 1506449) — **RTTI_GetClassInfo_CTaskAnimalUseSkills** — class self-registration getter (calls FUN_100016b0("CTaskAnimalUseSkills", parent-getter)); registers `CTaskAnimalUseSkills` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10982150` (line 1504401) — **RTTI_GetClassInfo_CTaskAttackStrategy** — class self-registration getter (calls FUN_100016b0("CTaskAttackStrategy", parent-getter)); registers `CTaskAttackStrategy` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10982270` (line 1504497) — **RTTI_GetClassInfo_CTaskBreakSocialPair** — class self-registration getter (calls FUN_100016b0("CTaskBreakSocialPair", parent-getter)); registers `CTaskBreakSocialPair` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109839e0` (line 1506497) — **RTTI_GetClassInfo_CTaskBroadcastStims** — class self-registration getter (calls FUN_100016b0("CTaskBroadcastStims", parent-getter)); registers `CTaskBroadcastStims` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10984600` (line 1507489) — **RTTI_GetClassInfo_CTaskBtzAnimalChase** — class self-registration getter (calls FUN_100016b0("CTaskBtzAnimalChase", parent-getter)); registers `CTaskBtzAnimalChase` as a subclass of `CBtzAnimalAction` in the engine RTTI/class-factory system.
- `FUN_109845d0` (line 1507473) — **RTTI_GetClassInfo_CTaskBtzAttack** — class self-registration getter (calls FUN_100016b0("CTaskBtzAttack", parent-getter)); registers `CTaskBtzAttack` as a subclass of `CPawnBaseAction` in the engine RTTI/class-factory system.
- `FUN_10982030` (line 1504305) — **RTTI_GetClassInfo_CTaskBuddyDown** — class self-registration getter (calls FUN_100016b0("CTaskBuddyDown", parent-getter)); registers `CTaskBuddyDown` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10983a40` (line 1506529) — **RTTI_GetClassInfo_CTaskCalcLineDist** — class self-registration getter (calls FUN_100016b0("CTaskCalcLineDist", parent-getter)); registers `CTaskCalcLineDist` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10980a40` (line 1502433) — **RTTI_GetClassInfo_CTaskChase** — class self-registration getter (calls FUN_100016b0("CTaskChase", parent-getter)); registers `CTaskChase` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10981580` (line 1503393) — **RTTI_GetClassInfo_CTaskCheckActionSignal** — class self-registration getter (calls FUN_100016b0("CTaskCheckActionSignal", parent-getter)); registers `CTaskCheckActionSignal` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10981c40` (line 1503969) — **RTTI_GetClassInfo_CTaskCheckAimStrategy** — class self-registration getter (calls FUN_100016b0("CTaskCheckAimStrategy", parent-getter)); registers `CTaskCheckAimStrategy` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10982630` (line 1504817) — **RTTI_GetClassInfo_CTaskCheckAmmoStatus** — class self-registration getter (calls FUN_100016b0("CTaskCheckAmmoStatus", parent-getter)); registers `CTaskCheckAmmoStatus` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10983860` (line 1506369) — **RTTI_GetClassInfo_CTaskCheckAnimalCanTryAnotherRunAwayDestination** — class self-registration getter (calls FUN_100016b0("CTaskCheckAnimalCanTryAnotherRunAwayDestination", parent-getter)); registers `CTaskCheckAnimalCanTryAnotherRunAwayDestination` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10984c90` (line 1508049) — **RTTI_GetClassInfo_CTaskCheckAnimalIsMounted** — class self-registration getter (calls FUN_100016b0("CTaskCheckAnimalIsMounted", parent-getter)); registers `CTaskCheckAnimalIsMounted` as a subclass of `CBtzAnimalAction` in the engine RTTI/class-factory system.
- `FUN_109838c0` (line 1506401) — **RTTI_GetClassInfo_CTaskCheckAnimalThreaten** — class self-registration getter (calls FUN_100016b0("CTaskCheckAnimalThreaten", parent-getter)); registers `CTaskCheckAnimalThreaten` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10981af0` (line 1503857) — **RTTI_GetClassInfo_CTaskCheckArmyRole** — class self-registration getter (calls FUN_100016b0("CTaskCheckArmyRole", parent-getter)); registers `CTaskCheckArmyRole` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981b20` (line 1503873) — **RTTI_GetClassInfo_CTaskCheckArmyRoleAction** — class self-registration getter (calls FUN_100016b0("CTaskCheckArmyRoleAction", parent-getter)); registers `CTaskCheckArmyRoleAction` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10980da0` (line 1502721) — **RTTI_GetClassInfo_CTaskCheckBargeSide** — class self-registration getter (calls FUN_100016b0("CTaskCheckBargeSide", parent-getter)); registers `CTaskCheckBargeSide` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10983560` (line 1506113) — **RTTI_GetClassInfo_CTaskCheckBlindCombatLevel** — class self-registration getter (calls FUN_100016b0("CTaskCheckBlindCombatLevel", parent-getter)); registers `CTaskCheckBlindCombatLevel` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10980bc0` (line 1502561) — **RTTI_GetClassInfo_CTaskCheckBuildingEntry** — class self-registration getter (calls FUN_100016b0("CTaskCheckBuildingEntry", parent-getter)); registers `CTaskCheckBuildingEntry` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10984960` (line 1507777) — **RTTI_GetClassInfo_CTaskCheckCharSheetStat** — class self-registration getter (calls FUN_100016b0("CTaskCheckCharSheetStat", parent-getter)); registers `CTaskCheckCharSheetStat` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10981760` (line 1503553) — **RTTI_GetClassInfo_CTaskCheckClearPath** — class self-registration getter (calls FUN_100016b0("CTaskCheckClearPath", parent-getter)); registers `CTaskCheckClearPath` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10982600` (line 1504801) — **RTTI_GetClassInfo_CTaskCheckCombatMercInRadius** — class self-registration getter (calls FUN_100016b0("CTaskCheckCombatMercInRadius", parent-getter)); registers `CTaskCheckCombatMercInRadius` as a subclass of `CPawnBaseDecision` in the engine RTTI/class-factory system.
- `FUN_10981eb0` (line 1504177) — **RTTI_GetClassInfo_CTaskCheckCoverDist** — class self-registration getter (calls FUN_100016b0("CTaskCheckCoverDist", parent-getter)); registers `CTaskCheckCoverDist` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10983b30` (line 1506609) — **RTTI_GetClassInfo_CTaskCheckCurrentSocialOccupation** — class self-registration getter (calls FUN_100016b0("CTaskCheckCurrentSocialOccupation", parent-getter)); registers `CTaskCheckCurrentSocialOccupation` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981fd0` (line 1504273) — **RTTI_GetClassInfo_CTaskCheckCurrentWeapon** — class self-registration getter (calls FUN_100016b0("CTaskCheckCurrentWeapon", parent-getter)); registers `CTaskCheckCurrentWeapon` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10980d10` (line 1502673) — **RTTI_GetClassInfo_CTaskCheckDifficultyLevel** — class self-registration getter (calls FUN_100016b0("CTaskCheckDifficultyLevel", parent-getter)); registers `CTaskCheckDifficultyLevel` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10983ce0` (line 1506753) — **RTTI_GetClassInfo_CTaskCheckDisturbanceType** — class self-registration getter (calls FUN_100016b0("CTaskCheckDisturbanceType", parent-getter)); registers `CTaskCheckDisturbanceType` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_109822d0` (line 1504529) — **RTTI_GetClassInfo_CTaskCheckDominoData** — class self-registration getter (calls FUN_100016b0("CTaskCheckDominoData", parent-getter)); registers `CTaskCheckDominoData` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981c10` (line 1503953) — **RTTI_GetClassInfo_CTaskCheckEmotionStrategy** — class self-registration getter (calls FUN_100016b0("CTaskCheckEmotionStrategy", parent-getter)); registers `CTaskCheckEmotionStrategy` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981010` (line 1502929) — **RTTI_GetClassInfo_CTaskCheckFactExist** — class self-registration getter (calls FUN_100016b0("CTaskCheckFactExist", parent-getter)); registers `CTaskCheckFactExist` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10980b30` (line 1502513) — **RTTI_GetClassInfo_CTaskCheckFireProximity** — class self-registration getter (calls FUN_100016b0("CTaskCheckFireProximity", parent-getter)); registers `CTaskCheckFireProximity` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10981e80` (line 1504161) — **RTTI_GetClassInfo_CTaskCheckFireRange** — class self-registration getter (calls FUN_100016b0("CTaskCheckFireRange", parent-getter)); registers `CTaskCheckFireRange` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981bb0` (line 1503921) — **RTTI_GetClassInfo_CTaskCheckFireStrategy** — class self-registration getter (calls FUN_100016b0("CTaskCheckFireStrategy", parent-getter)); registers `CTaskCheckFireStrategy` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981340` (line 1503201) — **RTTI_GetClassInfo_CTaskCheckIdleBehavior** — class self-registration getter (calls FUN_100016b0("CTaskCheckIdleBehavior", parent-getter)); registers `CTaskCheckIdleBehavior` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10983aa0` (line 1506561) — **RTTI_GetClassInfo_CTaskCheckInterestLookAtType** — class self-registration getter (calls FUN_100016b0("CTaskCheckInterestLookAtType", parent-getter)); registers `CTaskCheckInterestLookAtType` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_109824e0` (line 1504705) — **RTTI_GetClassInfo_CTaskCheckIsInBuilding** — class self-registration getter (calls FUN_100016b0("CTaskCheckIsInBuilding", parent-getter)); registers `CTaskCheckIsInBuilding` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10982450` (line 1504657) — **RTTI_GetClassInfo_CTaskCheckIsInDistance** — class self-registration getter (calls FUN_100016b0("CTaskCheckIsInDistance", parent-getter)); registers `CTaskCheckIsInDistance` as a subclass of `CPawnBaseDecision` in the engine RTTI/class-factory system.
- `FUN_109834d0` (line 1506065) — **RTTI_GetClassInfo_CTaskCheckIsInFOV** — class self-registration getter (calls FUN_100016b0("CTaskCheckIsInFOV", parent-getter)); registers `CTaskCheckIsInFOV` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10982300` (line 1504545) — **RTTI_GetClassInfo_CTaskCheckIsPlayingBark** — class self-registration getter (calls FUN_100016b0("CTaskCheckIsPlayingBark", parent-getter)); registers `CTaskCheckIsPlayingBark` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981be0` (line 1503937) — **RTTI_GetClassInfo_CTaskCheckLookStrategy** — class self-registration getter (calls FUN_100016b0("CTaskCheckLookStrategy", parent-getter)); registers `CTaskCheckLookStrategy` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981ca0` (line 1504001) — **RTTI_GetClassInfo_CTaskCheckMovingFire** — class self-registration getter (calls FUN_100016b0("CTaskCheckMovingFire", parent-getter)); registers `CTaskCheckMovingFire` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981ee0` (line 1504193) — **RTTI_GetClassInfo_CTaskCheckODUType** — class self-registration getter (calls FUN_100016b0("CTaskCheckODUType", parent-getter)); registers `CTaskCheckODUType` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981070` (line 1502961) — **RTTI_GetClassInfo_CTaskCheckObjectBlockingPath** — class self-registration getter (calls FUN_100016b0("CTaskCheckObjectBlockingPath", parent-getter)); registers `CTaskCheckObjectBlockingPath` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10980c20` (line 1502593) — **RTTI_GetClassInfo_CTaskCheckObstaclesInRegion** — class self-registration getter (calls FUN_100016b0("CTaskCheckObstaclesInRegion", parent-getter)); registers `CTaskCheckObstaclesInRegion` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_109812b0` (line 1503153) — **RTTI_GetClassInfo_CTaskCheckPlayerAction** — class self-registration getter (calls FUN_100016b0("CTaskCheckPlayerAction", parent-getter)); registers `CTaskCheckPlayerAction` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10983c20` (line 1506689) — **RTTI_GetClassInfo_CTaskCheckPlayerInfamy** — class self-registration getter (calls FUN_100016b0("CTaskCheckPlayerInfamy", parent-getter)); registers `CTaskCheckPlayerInfamy` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10980d70` (line 1502705) — **RTTI_GetClassInfo_CTaskCheckPosInLoadedSector** — class self-registration getter (calls FUN_100016b0("CTaskCheckPosInLoadedSector", parent-getter)); registers `CTaskCheckPosInLoadedSector` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10980a10` (line 1502417) — **RTTI_GetClassInfo_CTaskCheckPosOnSpline** — class self-registration getter (calls FUN_100016b0("CTaskCheckPosOnSpline", parent-getter)); registers `CTaskCheckPosOnSpline` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10981430` (line 1503281) — **RTTI_GetClassInfo_CTaskCheckProjEscapeType** — class self-registration getter (calls FUN_100016b0("CTaskCheckProjEscapeType", parent-getter)); registers `CTaskCheckProjEscapeType` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10983c80` (line 1506721) — **RTTI_GetClassInfo_CTaskCheckProximity** — class self-registration getter (calls FUN_100016b0("CTaskCheckProximity", parent-getter)); registers `CTaskCheckProximity` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10981130` (line 1503025) — **RTTI_GetClassInfo_CTaskCheckQueryRange** — class self-registration getter (calls FUN_100016b0("CTaskCheckQueryRange", parent-getter)); registers `CTaskCheckQueryRange` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_109814c0` (line 1503329) — **RTTI_GetClassInfo_CTaskCheckRegionTransition** — class self-registration getter (calls FUN_100016b0("CTaskCheckRegionTransition", parent-getter)); registers `CTaskCheckRegionTransition` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10983b00` (line 1506593) — **RTTI_GetClassInfo_CTaskCheckRegionType** — class self-registration getter (calls FUN_100016b0("CTaskCheckRegionType", parent-getter)); registers `CTaskCheckRegionType` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10983d10` (line 1506769) — **RTTI_GetClassInfo_CTaskCheckRelativeInfamy** — class self-registration getter (calls FUN_100016b0("CTaskCheckRelativeInfamy", parent-getter)); registers `CTaskCheckRelativeInfamy` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10983530` (line 1506097) — **RTTI_GetClassInfo_CTaskCheckSawSomethingLevel** — class self-registration getter (calls FUN_100016b0("CTaskCheckSawSomethingLevel", parent-getter)); registers `CTaskCheckSawSomethingLevel` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981310` (line 1503185) — **RTTI_GetClassInfo_CTaskCheckSeeFriendNearby** — class self-registration getter (calls FUN_100016b0("CTaskCheckSeeFriendNearby", parent-getter)); registers `CTaskCheckSeeFriendNearby` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10982cc0` (line 1505377) — **RTTI_GetClassInfo_CTaskCheckSmartTerrainType** — class self-registration getter (calls FUN_100016b0("CTaskCheckSmartTerrainType", parent-getter)); registers `CTaskCheckSmartTerrainType` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10983ad0` (line 1506577) — **RTTI_GetClassInfo_CTaskCheckSocialProximity** — class self-registration getter (calls FUN_100016b0("CTaskCheckSocialProximity", parent-getter)); registers `CTaskCheckSocialProximity` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10980b60` (line 1502529) — **RTTI_GetClassInfo_CTaskCheckSpecialMissionBehaviour** — class self-registration getter (calls FUN_100016b0("CTaskCheckSpecialMissionBehaviour", parent-getter)); registers `CTaskCheckSpecialMissionBehaviour` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981c70` (line 1503985) — **RTTI_GetClassInfo_CTaskCheckSpecialStrategy** — class self-registration getter (calls FUN_100016b0("CTaskCheckSpecialStrategy", parent-getter)); registers `CTaskCheckSpecialStrategy` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981b50` (line 1503889) — **RTTI_GetClassInfo_CTaskCheckSquadAction** — class self-registration getter (calls FUN_100016b0("CTaskCheckSquadAction", parent-getter)); registers `CTaskCheckSquadAction` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981b80` (line 1503905) — **RTTI_GetClassInfo_CTaskCheckSquadRole** — class self-registration getter (calls FUN_100016b0("CTaskCheckSquadRole", parent-getter)); registers `CTaskCheckSquadRole` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10983d40` (line 1506785) — **RTTI_GetClassInfo_CTaskCheckStressLevel** — class self-registration getter (calls FUN_100016b0("CTaskCheckStressLevel", parent-getter)); registers `CTaskCheckStressLevel` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981f70` (line 1504241) — **RTTI_GetClassInfo_CTaskCheckTargetHeightDiff** — class self-registration getter (calls FUN_100016b0("CTaskCheckTargetHeightDiff", parent-getter)); registers `CTaskCheckTargetHeightDiff` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981f40` (line 1504225) — **RTTI_GetClassInfo_CTaskCheckTargetRange** — class self-registration getter (calls FUN_100016b0("CTaskCheckTargetRange", parent-getter)); registers `CTaskCheckTargetRange` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981fa0` (line 1504257) — **RTTI_GetClassInfo_CTaskCheckTargetType** — class self-registration getter (calls FUN_100016b0("CTaskCheckTargetType", parent-getter)); registers `CTaskCheckTargetType` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981f10` (line 1504209) — **RTTI_GetClassInfo_CTaskCheckTargetVisible** — class self-registration getter (calls FUN_100016b0("CTaskCheckTargetVisible", parent-getter)); registers `CTaskCheckTargetVisible` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10983890` (line 1506385) — **RTTI_GetClassInfo_CTaskCheckThreatDistance** — class self-registration getter (calls FUN_100016b0("CTaskCheckThreatDistance", parent-getter)); registers `CTaskCheckThreatDistance` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10980fe0` (line 1502913) — **RTTI_GetClassInfo_CTaskCheckUnderFire** — class self-registration getter (calls FUN_100016b0("CTaskCheckUnderFire", parent-getter)); registers `CTaskCheckUnderFire` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10982000` (line 1504289) — **RTTI_GetClassInfo_CTaskCheckUsingCover** — class self-registration getter (calls FUN_100016b0("CTaskCheckUsingCover", parent-getter)); registers `CTaskCheckUsingCover` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10983c50` (line 1506705) — **RTTI_GetClassInfo_CTaskCheckViewBlocked** — class self-registration getter (calls FUN_100016b0("CTaskCheckViewBlocked", parent-getter)); registers `CTaskCheckViewBlocked` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_109812e0` (line 1503169) — **RTTI_GetClassInfo_CTaskCheckVisibleByPlayer** — class self-registration getter (calls FUN_100016b0("CTaskCheckVisibleByPlayer", parent-getter)); registers `CTaskCheckVisibleByPlayer` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_109817c0` (line 1503585) — **RTTI_GetClassInfo_CTaskChooseCoverAttack** — class self-registration getter (calls FUN_100016b0("CTaskChooseCoverAttack", parent-getter)); registers `CTaskChooseCoverAttack` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10982690` (line 1504849) — **RTTI_GetClassInfo_CTaskChurchAssault** — class self-registration getter (calls FUN_100016b0("CTaskChurchAssault", parent-getter)); registers `CTaskChurchAssault` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10983bf0` (line 1506673) — **RTTI_GetClassInfo_CTaskCleanBriefingAnim** — class self-registration getter (calls FUN_100016b0("CTaskCleanBriefingAnim", parent-getter)); registers `CTaskCleanBriefingAnim` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10982570` (line 1504753) — **RTTI_GetClassInfo_CTaskClearMoveToDynamics** — class self-registration getter (calls FUN_100016b0("CTaskClearMoveToDynamics", parent-getter)); registers `CTaskClearMoveToDynamics` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10980c50` (line 1502609) — **RTTI_GetClassInfo_CTaskComputeInterpolatedPos** — class self-registration getter (calls FUN_100016b0("CTaskComputeInterpolatedPos", parent-getter)); registers `CTaskComputeInterpolatedPos` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10981910` (line 1503697) — **RTTI_GetClassInfo_CTaskComputeLeapFrogStep** — class self-registration getter (calls FUN_100016b0("CTaskComputeLeapFrogStep", parent-getter)); registers `CTaskComputeLeapFrogStep` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10981cd0` (line 1504017) — **RTTI_GetClassInfo_CTaskComputeProjectileTrajectory** — class self-registration getter (calls FUN_100016b0("CTaskComputeProjectileTrajectory", parent-getter)); registers `CTaskComputeProjectileTrajectory` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981d00` (line 1504033) — **RTTI_GetClassInfo_CTaskComputeSynchActionPosition** — class self-registration getter (calls FUN_100016b0("CTaskComputeSynchActionPosition", parent-getter)); registers `CTaskComputeSynchActionPosition` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10984930` (line 1507761) — **RTTI_GetClassInfo_CTaskCopterAim** — class self-registration getter (calls FUN_100016b0("CTaskCopterAim", parent-getter)); registers `CTaskCopterAim` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10981970` (line 1503729) — **RTTI_GetClassInfo_CTaskCoverAttack** — class self-registration getter (calls FUN_100016b0("CTaskCoverAttack", parent-getter)); registers `CTaskCoverAttack` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10980bf0` (line 1502577) — **RTTI_GetClassInfo_CTaskDebugSetCurrentBehavior** — class self-registration getter (calls FUN_100016b0("CTaskDebugSetCurrentBehavior", parent-getter)); registers `CTaskDebugSetCurrentBehavior` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10984bd0` (line 1507985) — **RTTI_GetClassInfo_CTaskDisablePawnBehaviorsWhileRunning** — class self-registration getter (calls FUN_100016b0("CTaskDisablePawnBehaviorsWhileRunning", parent-getter)); registers `CTaskDisablePawnBehaviorsWhileRunning` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10982660` (line 1504833) — **RTTI_GetClassInfo_CTaskDisableSTPDynamicAvoidance** — class self-registration getter (calls FUN_100016b0("CTaskDisableSTPDynamicAvoidance", parent-getter)); registers `CTaskDisableSTPDynamicAvoidance` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10980f20` (line 1502849) — **RTTI_GetClassInfo_CTaskDisplayError** — class self-registration getter (calls FUN_100016b0("CTaskDisplayError", parent-getter)); registers `CTaskDisplayError` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10983cb0` (line 1506737) — **RTTI_GetClassInfo_CTaskDisplaySTPClippingError** — class self-registration getter (calls FUN_100016b0("CTaskDisplaySTPClippingError", parent-getter)); registers `CTaskDisplaySTPClippingError` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109849f0` (line 1507825) — **RTTI_GetClassInfo_CTaskDroneBombChase** — class self-registration getter (calls FUN_100016b0("CTaskDroneBombChase", parent-getter)); registers `CTaskDroneBombChase` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10984a20` (line 1507841) — **RTTI_GetClassInfo_CTaskDroneBombMoveTo** — class self-registration getter (calls FUN_100016b0("CTaskDroneBombMoveTo", parent-getter)); registers `CTaskDroneBombMoveTo` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109818e0` (line 1503681) — **RTTI_GetClassInfo_CTaskDropItem** — class self-registration getter (calls FUN_100016b0("CTaskDropItem", parent-getter)); registers `CTaskDropItem` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10982090` (line 1504337) — **RTTI_GetClassInfo_CTaskEmitBark** — class self-registration getter (calls FUN_100016b0("CTaskEmitBark", parent-getter)); registers `CTaskEmitBark` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10984c30` (line 1508017) — **RTTI_GetClassInfo_CTaskEndJumpDown** — class self-registration getter (calls FUN_100016b0("CTaskEndJumpDown", parent-getter)); registers `CTaskEndJumpDown` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981370` (line 1503217) — **RTTI_GetClassInfo_CTaskFindAIShootMeObject** — class self-registration getter (calls FUN_100016b0("CTaskFindAIShootMeObject", parent-getter)); registers `CTaskFindAIShootMeObject` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10980a70` (line 1502449) — **RTTI_GetClassInfo_CTaskFindCover** — class self-registration getter (calls FUN_100016b0("CTaskFindCover", parent-getter)); registers `CTaskFindCover` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10981790` (line 1503569) — **RTTI_GetClassInfo_CTaskFindCoverAttack** — class self-registration getter (calls FUN_100016b0("CTaskFindCoverAttack", parent-getter)); registers `CTaskFindCoverAttack` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10980ad0` (line 1502481) — **RTTI_GetClassInfo_CTaskFindEscapePos** — class self-registration getter (calls FUN_100016b0("CTaskFindEscapePos", parent-getter)); registers `CTaskFindEscapePos` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10983a70` (line 1506545) — **RTTI_GetClassInfo_CTaskFindInterestLookAt** — class self-registration getter (calls FUN_100016b0("CTaskFindInterestLookAt", parent-getter)); registers `CTaskFindInterestLookAt` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981940` (line 1503713) — **RTTI_GetClassInfo_CTaskFindLeapFrogStep** — class self-registration getter (calls FUN_100016b0("CTaskFindLeapFrogStep", parent-getter)); registers `CTaskFindLeapFrogStep` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10981190` (line 1503057) — **RTTI_GetClassInfo_CTaskFindMountedWeapon** — class self-registration getter (calls FUN_100016b0("CTaskFindMountedWeapon", parent-getter)); registers `CTaskFindMountedWeapon` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981730` (line 1503537) — **RTTI_GetClassInfo_CTaskFindPlayerTarget** — class self-registration getter (calls FUN_100016b0("CTaskFindPlayerTarget", parent-getter)); registers `CTaskFindPlayerTarget` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10982510` (line 1504721) — **RTTI_GetClassInfo_CTaskFindProtectionPoint** — class self-registration getter (calls FUN_100016b0("CTaskFindProtectionPoint", parent-getter)); registers `CTaskFindProtectionPoint` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10983470` (line 1506033) — **RTTI_GetClassInfo_CTaskFindRandomDest** — class self-registration getter (calls FUN_100016b0("CTaskFindRandomDest", parent-getter)); registers `CTaskFindRandomDest` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10983830` (line 1506353) — **RTTI_GetClassInfo_CTaskFindRescueDest** — class self-registration getter (calls FUN_100016b0("CTaskFindRescueDest", parent-getter)); registers `CTaskFindRescueDest` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10981a30` (line 1503793) — **RTTI_GetClassInfo_CTaskFindRiskPoints** — class self-registration getter (calls FUN_100016b0("CTaskFindRiskPoints", parent-getter)); registers `CTaskFindRiskPoints` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109813d0` (line 1503249) — **RTTI_GetClassInfo_CTaskFindSocialFleePos** — class self-registration getter (calls FUN_100016b0("CTaskFindSocialFleePos", parent-getter)); registers `CTaskFindSocialFleePos` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981a90` (line 1503825) — **RTTI_GetClassInfo_CTaskFindStrategicPoint** — class self-registration getter (calls FUN_100016b0("CTaskFindStrategicPoint", parent-getter)); registers `CTaskFindStrategicPoint` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981160` (line 1503041) — **RTTI_GetClassInfo_CTaskFindVisualThreat** — class self-registration getter (calls FUN_100016b0("CTaskFindVisualThreat", parent-getter)); registers `CTaskFindVisualThreat` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10980fb0` (line 1502897) — **RTTI_GetClassInfo_CTaskFindWorldEntity** — class self-registration getter (calls FUN_100016b0("CTaskFindWorldEntity", parent-getter)); registers `CTaskFindWorldEntity` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109821b0` (line 1504433) — **RTTI_GetClassInfo_CTaskFireStrategySelector** — class self-registration getter (calls FUN_100016b0("CTaskFireStrategySelector", parent-getter)); registers `CTaskFireStrategySelector` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10981700` (line 1503521) — **RTTI_GetClassInfo_CTaskFuzzyChoice** — class self-registration getter (calls FUN_100016b0("CTaskFuzzyChoice", parent-getter)); registers `CTaskFuzzyChoice` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10980b90` (line 1502545) — **RTTI_GetClassInfo_CTaskGetBuildingEntry** — class self-registration getter (calls FUN_100016b0("CTaskGetBuildingEntry", parent-getter)); registers `CTaskGetBuildingEntry` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109809e0` (line 1502401) — **RTTI_GetClassInfo_CTaskGetClosestSplinePos** — class self-registration getter (calls FUN_100016b0("CTaskGetClosestSplinePos", parent-getter)); registers `CTaskGetClosestSplinePos` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10980c80` (line 1502625) — **RTTI_GetClassInfo_CTaskGetNextPathPos** — class self-registration getter (calls FUN_100016b0("CTaskGetNextPathPos", parent-getter)); registers `CTaskGetNextPathPos` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10981a00` (line 1503777) — **RTTI_GetClassInfo_CTaskGetPatrolPath** — class self-registration getter (calls FUN_100016b0("CTaskGetPatrolPath", parent-getter)); registers `CTaskGetPatrolPath` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109819a0` (line 1503745) — **RTTI_GetClassInfo_CTaskGetPosOnNavMesh** — class self-registration getter (calls FUN_100016b0("CTaskGetPosOnNavMesh", parent-getter)); registers `CTaskGetPosOnNavMesh` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10983a10` (line 1506513) — **RTTI_GetClassInfo_CTaskGetRescuePositions** — class self-registration getter (calls FUN_100016b0("CTaskGetRescuePositions", parent-getter)); registers `CTaskGetRescuePositions` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10982390` (line 1504593) — **RTTI_GetClassInfo_CTaskGetSniperPoint** — class self-registration getter (calls FUN_100016b0("CTaskGetSniperPoint", parent-getter)); registers `CTaskGetSniperPoint` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109819d0` (line 1503761) — **RTTI_GetClassInfo_CTaskGetStraightPath** — class self-registration getter (calls FUN_100016b0("CTaskGetStraightPath", parent-getter)); registers `CTaskGetStraightPath` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10980e30` (line 1502769) — **RTTI_GetClassInfo_CTaskHighTargetAttackPos** — class self-registration getter (calls FUN_100016b0("CTaskHighTargetAttackPos", parent-getter)); registers `CTaskHighTargetAttackPos` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10983500` (line 1506081) — **RTTI_GetClassInfo_CTaskIncreaseSawSomethingLevel** — class self-registration getter (calls FUN_100016b0("CTaskIncreaseSawSomethingLevel", parent-getter)); registers `CTaskIncreaseSawSomethingLevel` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10980cb0` (line 1502641) — **RTTI_GetClassInfo_CTaskIncrementPathPos** — class self-registration getter (calls FUN_100016b0("CTaskIncrementPathPos", parent-getter)); registers `CTaskIncrementPathPos` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10984c00` (line 1508001) — **RTTI_GetClassInfo_CTaskJump** — class self-registration getter (calls FUN_100016b0("CTaskJump", parent-getter)); registers `CTaskJump` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10980b00` (line 1502497) — **RTTI_GetClassInfo_CTaskLookAround** — class self-registration getter (calls FUN_100016b0("CTaskLookAround", parent-getter)); registers `CTaskLookAround` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109821e0` (line 1504449) — **RTTI_GetClassInfo_CTaskLookAroundTarget** — class self-registration getter (calls FUN_100016b0("CTaskLookAroundTarget", parent-getter)); registers `CTaskLookAroundTarget` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109808c0` (line 1502305) — **RTTI_GetClassInfo_CTaskLookAt** — class self-registration getter (calls FUN_100016b0("CTaskLookAt", parent-getter)); registers `CTaskLookAt` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109825d0` (line 1504785) — **RTTI_GetClassInfo_CTaskLookAtVehicle** — class self-registration getter (calls FUN_100016b0("CTaskLookAtVehicle", parent-getter)); registers `CTaskLookAtVehicle` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10982210` (line 1504465) — **RTTI_GetClassInfo_CTaskLookRandom** — class self-registration getter (calls FUN_100016b0("CTaskLookRandom", parent-getter)); registers `CTaskLookRandom` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10980e60` (line 1502785) — **RTTI_GetClassInfo_CTaskManageAnchor** — class self-registration getter (calls FUN_100016b0("CTaskManageAnchor", parent-getter)); registers `CTaskManageAnchor` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10980dd0` (line 1502737) — **RTTI_GetClassInfo_CTaskManageArmy** — class self-registration getter (calls FUN_100016b0("CTaskManageArmy", parent-getter)); registers `CTaskManageArmy` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10984ba0` (line 1507969) — **RTTI_GetClassInfo_CTaskMeleeCombo** — class self-registration getter (calls FUN_100016b0("CTaskMeleeCombo", parent-getter)); registers `CTaskMeleeCombo` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10982180` (line 1504417) — **RTTI_GetClassInfo_CTaskMoveStrategy** — class self-registration getter (calls FUN_100016b0("CTaskMoveStrategy", parent-getter)); registers `CTaskMoveStrategy` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10980860` (line 1502273) — **RTTI_GetClassInfo_CTaskMoveTo** — class self-registration getter (calls FUN_100016b0("CTaskMoveTo", parent-getter)); registers `CTaskMoveTo` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109807d0` (line 1502225) — **RTTI_GetClassInfo_CTaskNextWeapon** — class self-registration getter (calls FUN_100016b0("CTaskNextWeapon", parent-getter)); registers `CTaskNextWeapon` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981d60` (line 1504065) — **RTTI_GetClassInfo_CTaskNotifyUnreachablePos** — class self-registration getter (calls FUN_100016b0("CTaskNotifyUnreachablePos", parent-getter)); registers `CTaskNotifyUnreachablePos` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981400` (line 1503265) — **RTTI_GetClassInfo_CTaskOperateOnFlagField** — class self-registration getter (calls FUN_100016b0("CTaskOperateOnFlagField", parent-getter)); registers `CTaskOperateOnFlagField` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10984310` (line 1507281) — **RTTI_GetClassInfo_CTaskOrientAndPlayAnim** — class self-registration getter (calls FUN_100016b0("CTaskOrientAndPlayAnim", parent-getter)); registers `CTaskOrientAndPlayAnim` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109808f0` (line 1502321) — **RTTI_GetClassInfo_CTaskOrientToward** — class self-registration getter (calls FUN_100016b0("CTaskOrientToward", parent-getter)); registers `CTaskOrientToward` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10982060` (line 1504321) — **RTTI_GetClassInfo_CTaskPathAnalyzer** — class self-registration getter (calls FUN_100016b0("CTaskPathAnalyzer", parent-getter)); registers `CTaskPathAnalyzer` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10980920` (line 1502337) — **RTTI_GetClassInfo_CTaskPathFind** — class self-registration getter (calls FUN_100016b0("CTaskPathFind", parent-getter)); registers `CTaskPathFind` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10980980` (line 1502369) — **RTTI_GetClassInfo_CTaskPathFindAndMoveTo** — class self-registration getter (calls FUN_100016b0("CTaskPathFindAndMoveTo", parent-getter)); registers `CTaskPathFindAndMoveTo` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10980950` (line 1502353) — **RTTI_GetClassInfo_CTaskPathFollow** — class self-registration getter (calls FUN_100016b0("CTaskPathFollow", parent-getter)); registers `CTaskPathFollow` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10982d20` (line 1505409) — **RTTI_GetClassInfo_CTaskPatrol** — class self-registration getter (calls FUN_100016b0("CTaskPatrol", parent-getter)); registers `CTaskPatrol` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109817f0` (line 1503601) — **RTTI_GetClassInfo_CTaskPlayAnim** — class self-registration getter (calls FUN_100016b0("CTaskPlayAnim", parent-getter)); registers `CTaskPlayAnim` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10983bc0` (line 1506657) — **RTTI_GetClassInfo_CTaskPlayBriefingAnim** — class self-registration getter (calls FUN_100016b0("CTaskPlayBriefingAnim", parent-getter)); registers `CTaskPlayBriefingAnim` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981820` (line 1503617) — **RTTI_GetClassInfo_CTaskPlaySound** — class self-registration getter (calls FUN_100016b0("CTaskPlaySound", parent-getter)); registers `CTaskPlaySound` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10981220` (line 1503105) — **RTTI_GetClassInfo_CTaskPredictImpactPos** — class self-registration getter (calls FUN_100016b0("CTaskPredictImpactPos", parent-getter)); registers `CTaskPredictImpactPos` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981d30` (line 1504049) — **RTTI_GetClassInfo_CTaskPrepareSynchActionPosition** — class self-registration getter (calls FUN_100016b0("CTaskPrepareSynchActionPosition", parent-getter)); registers `CTaskPrepareSynchActionPosition` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10983b60` (line 1506625) — **RTTI_GetClassInfo_CTaskPushPlayer** — class self-registration getter (calls FUN_100016b0("CTaskPushPlayer", parent-getter)); registers `CTaskPushPlayer` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109825a0` (line 1504769) — **RTTI_GetClassInfo_CTaskRequestVehicle** — class self-registration getter (calls FUN_100016b0("CTaskRequestVehicle", parent-getter)); registers `CTaskRequestVehicle` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10982540` (line 1504737) — **RTTI_GetClassInfo_CTaskReserveProtectionPoint** — class self-registration getter (calls FUN_100016b0("CTaskReserveProtectionPoint", parent-getter)); registers `CTaskReserveProtectionPoint` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109823c0` (line 1504609) — **RTTI_GetClassInfo_CTaskReserveSniperPoint** — class self-registration getter (calls FUN_100016b0("CTaskReserveSniperPoint", parent-getter)); registers `CTaskReserveSniperPoint` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10980e00` (line 1502753) — **RTTI_GetClassInfo_CTaskResourceManager** — class self-registration getter (calls FUN_100016b0("CTaskResourceManager", parent-getter)); registers `CTaskResourceManager` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10980ec0` (line 1502817) — **RTTI_GetClassInfo_CTaskReturnFailure** — class self-registration getter (calls FUN_100016b0("CTaskReturnFailure", parent-getter)); registers `CTaskReturnFailure` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_104a1920` (line 803095) — **RTTI_GetClassInfo_CTaskRoot** — class self-registration getter (calls FUN_100016b0("CTaskRoot", parent-getter)); registers `CTaskRoot` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_10981850` (line 1503633) — **RTTI_GetClassInfo_CTaskSavePosInFact** — class self-registration getter (calls FUN_100016b0("CTaskSavePosInFact", parent-getter)); registers `CTaskSavePosInFact` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109810d0` (line 1502993) — **RTTI_GetClassInfo_CTaskSearchOpponents** — class self-registration getter (calls FUN_100016b0("CTaskSearchOpponents", parent-getter)); registers `CTaskSearchOpponents` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981100` (line 1503009) — **RTTI_GetClassInfo_CTaskSelectBestOpponents** — class self-registration getter (calls FUN_100016b0("CTaskSelectBestOpponents", parent-getter)); registers `CTaskSelectBestOpponents` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10982330` (line 1504561) — **RTTI_GetClassInfo_CTaskSelectBestTarget** — class self-registration getter (calls FUN_100016b0("CTaskSelectBestTarget", parent-getter)); registers `CTaskSelectBestTarget` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_10984b70` (line 1507953) — **RTTI_GetClassInfo_CTaskSelectHitAndRunPoint** — class self-registration getter (calls FUN_100016b0("CTaskSelectHitAndRunPoint", parent-getter)); registers `CTaskSelectHitAndRunPoint` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981a60` (line 1503809) — **RTTI_GetClassInfo_CTaskSelectRiskPoint** — class self-registration getter (calls FUN_100016b0("CTaskSelectRiskPoint", parent-getter)); registers `CTaskSelectRiskPoint` as a subclass of `CPawnDecision` in the engine RTTI/class-factory system.
- `FUN_109814f0` (line 1503345) — **RTTI_GetClassInfo_CTaskSelectWeapon** — class self-registration getter (calls FUN_100016b0("CTaskSelectWeapon", parent-getter)); registers `CTaskSelectWeapon` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109815b0` (line 1503409) — **RTTI_GetClassInfo_CTaskSendActionSignal** — class self-registration getter (calls FUN_100016b0("CTaskSendActionSignal", parent-getter)); registers `CTaskSendActionSignal` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109818b0` (line 1503665) — **RTTI_GetClassInfo_CTaskSendBrainEvent** — class self-registration getter (calls FUN_100016b0("CTaskSendBrainEvent", parent-getter)); registers `CTaskSendBrainEvent` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10983b90` (line 1506641) — **RTTI_GetClassInfo_CTaskSendDominoEvent** — class self-registration getter (calls FUN_100016b0("CTaskSendDominoEvent", parent-getter)); registers `CTaskSendDominoEvent` as a subclass of `CPawnBaseAction` in the engine RTTI/class-factory system.
- `FUN_10981280` (line 1503137) — **RTTI_GetClassInfo_CTaskSendHMREvent** — class self-registration getter (calls FUN_100016b0("CTaskSendHMREvent", parent-getter)); registers `CTaskSendHMREvent` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981550` (line 1503377) — **RTTI_GetClassInfo_CTaskSendReport** — class self-registration getter (calls FUN_100016b0("CTaskSendReport", parent-getter)); registers `CTaskSendReport` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10982480` (line 1504673) — **RTTI_GetClassInfo_CTaskSendSocialReport** — class self-registration getter (calls FUN_100016b0("CTaskSendSocialReport", parent-getter)); registers `CTaskSendSocialReport` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981e20` (line 1504129) — **RTTI_GetClassInfo_CTaskSetAimStrategy** — class self-registration getter (calls FUN_100016b0("CTaskSetAimStrategy", parent-getter)); registers `CTaskSetAimStrategy` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10980d40` (line 1502689) — **RTTI_GetClassInfo_CTaskSetCurrentState** — class self-registration getter (calls FUN_100016b0("CTaskSetCurrentState", parent-getter)); registers `CTaskSetCurrentState` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981df0` (line 1504113) — **RTTI_GetClassInfo_CTaskSetEmotionStrategy** — class self-registration getter (calls FUN_100016b0("CTaskSetEmotionStrategy", parent-getter)); registers `CTaskSetEmotionStrategy` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10982360` (line 1504577) — **RTTI_GetClassInfo_CTaskSetFacialEmotion** — class self-registration getter (calls FUN_100016b0("CTaskSetFacialEmotion", parent-getter)); registers `CTaskSetFacialEmotion` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981d90` (line 1504081) — **RTTI_GetClassInfo_CTaskSetFireStrategy** — class self-registration getter (calls FUN_100016b0("CTaskSetFireStrategy", parent-getter)); registers `CTaskSetFireStrategy` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109824b0` (line 1504689) — **RTTI_GetClassInfo_CTaskSetForcedLookAtEntity** — class self-registration getter (calls FUN_100016b0("CTaskSetForcedLookAtEntity", parent-getter)); registers `CTaskSetForcedLookAtEntity` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10984c60` (line 1508033) — **RTTI_GetClassInfo_CTaskSetHiding** — class self-registration getter (calls FUN_100016b0("CTaskSetHiding", parent-getter)); registers `CTaskSetHiding` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10981dc0` (line 1504097) — **RTTI_GetClassInfo_CTaskSetLookStrategy** — class self-registration getter (calls FUN_100016b0("CTaskSetLookStrategy", parent-getter)); registers `CTaskSetLookStrategy` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981ac0` (line 1503841) — **RTTI_GetClassInfo_CTaskSetPathPointPosition** — class self-registration getter (calls FUN_100016b0("CTaskSetPathPointPosition", parent-getter)); registers `CTaskSetPathPointPosition` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10981610` (line 1503441) — **RTTI_GetClassInfo_CTaskSetPawnAttribute** — class self-registration getter (calls FUN_100016b0("CTaskSetPawnAttribute", parent-getter)); registers `CTaskSetPawnAttribute` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109815e0` (line 1503425) — **RTTI_GetClassInfo_CTaskSetPawnTarget** — class self-registration getter (calls FUN_100016b0("CTaskSetPawnTarget", parent-getter)); registers `CTaskSetPawnTarget` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981640` (line 1503457) — **RTTI_GetClassInfo_CTaskSetPostureAttribute** — class self-registration getter (calls FUN_100016b0("CTaskSetPostureAttribute", parent-getter)); registers `CTaskSetPostureAttribute` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981670` (line 1503473) — **RTTI_GetClassInfo_CTaskSetPostureIntention** — class self-registration getter (calls FUN_100016b0("CTaskSetPostureIntention", parent-getter)); registers `CTaskSetPostureIntention` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109822a0` (line 1504513) — **RTTI_GetClassInfo_CTaskSetSocialEngageMode** — class self-registration getter (calls FUN_100016b0("CTaskSetSocialEngageMode", parent-getter)); registers `CTaskSetSocialEngageMode` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981e50` (line 1504145) — **RTTI_GetClassInfo_CTaskSetSpecialStrategy** — class self-registration getter (calls FUN_100016b0("CTaskSetSpecialStrategy", parent-getter)); registers `CTaskSetSpecialStrategy` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10980aa0` (line 1502465) — **RTTI_GetClassInfo_CTaskSetSpeed** — class self-registration getter (calls FUN_100016b0("CTaskSetSpeed", parent-getter)); registers `CTaskSetSpeed` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10982420` (line 1504641) — **RTTI_GetClassInfo_CTaskSetStanceOnSniperPoint** — class self-registration getter (calls FUN_100016b0("CTaskSetStanceOnSniperPoint", parent-getter)); registers `CTaskSetStanceOnSniperPoint` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109834a0` (line 1506049) — **RTTI_GetClassInfo_CTaskSetSyncState** — class self-registration getter (calls FUN_100016b0("CTaskSetSyncState", parent-getter)); registers `CTaskSetSyncState` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10980800` (line 1502241) — **RTTI_GetClassInfo_CTaskShoot** — class self-registration getter (calls FUN_100016b0("CTaskShoot", parent-getter)); registers `CTaskShoot` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10980830` (line 1502257) — **RTTI_GetClassInfo_CTaskShootMortar** — class self-registration getter (calls FUN_100016b0("CTaskShootMortar", parent-getter)); registers `CTaskShootMortar` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981250` (line 1503121) — **RTTI_GetClassInfo_CTaskShootMountedWeapon** — class self-registration getter (calls FUN_100016b0("CTaskShootMountedWeapon", parent-getter)); registers `CTaskShootMountedWeapon` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109816d0` (line 1503505) — **RTTI_GetClassInfo_CTaskSmartTerrainExecutor** — class self-registration getter (calls FUN_100016b0("CTaskSmartTerrainExecutor", parent-getter)); registers `CTaskSmartTerrainExecutor` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109816a0` (line 1503489) — **RTTI_GetClassInfo_CTaskSmartTerrainFinder** — class self-registration getter (calls FUN_100016b0("CTaskSmartTerrainFinder", parent-getter)); registers `CTaskSmartTerrainFinder` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10981490` (line 1503313) — **RTTI_GetClassInfo_CTaskSpecialVehicleDetach** — class self-registration getter (calls FUN_100016b0("CTaskSpecialVehicleDetach", parent-getter)); registers `CTaskSpecialVehicleDetach` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109809b0` (line 1502385) — **RTTI_GetClassInfo_CTaskSplinePathFind** — class self-registration getter (calls FUN_100016b0("CTaskSplinePathFind", parent-getter)); registers `CTaskSplinePathFind` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109820c0` (line 1504353) — **RTTI_GetClassInfo_CTaskStopBark** — class self-registration getter (calls FUN_100016b0("CTaskStopBark", parent-getter)); registers `CTaskStopBark` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109820f0` (line 1504369) — **RTTI_GetClassInfo_CTaskStopBarkGesture** — class self-registration getter (calls FUN_100016b0("CTaskStopBarkGesture", parent-getter)); registers `CTaskStopBarkGesture` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981520` (line 1503361) — **RTTI_GetClassInfo_CTaskSwitchWeapon** — class self-registration getter (calls FUN_100016b0("CTaskSwitchWeapon", parent-getter)); registers `CTaskSwitchWeapon` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10981460` (line 1503297) — **RTTI_GetClassInfo_CTaskTeleportInVehicleSeat** — class self-registration getter (calls FUN_100016b0("CTaskTeleportInVehicleSeat", parent-getter)); registers `CTaskTeleportInVehicleSeat` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109848a0` (line 1507713) — **RTTI_GetClassInfo_CTaskTurretOrientTo** — class self-registration getter (calls FUN_100016b0("CTaskTurretOrientTo", parent-getter)); registers `CTaskTurretOrientTo` as a subclass of `CTurretAction` in the engine RTTI/class-factory system.
- `FUN_10984840` (line 1507681) — **RTTI_GetClassInfo_CTaskTurretSelectWeapon** — class self-registration getter (calls FUN_100016b0("CTaskTurretSelectWeapon", parent-getter)); registers `CTaskTurretSelectWeapon` as a subclass of `CTurretAction` in the engine RTTI/class-factory system.
- `FUN_10984870` (line 1507697) — **RTTI_GetClassInfo_CTaskTurretSetState** — class self-registration getter (calls FUN_100016b0("CTaskTurretSetState", parent-getter)); registers `CTaskTurretSetState` as a subclass of `CTurretAction` in the engine RTTI/class-factory system.
- `FUN_109847e0` (line 1507649) — **RTTI_GetClassInfo_CTaskTurretShoot** — class self-registration getter (calls FUN_100016b0("CTaskTurretShoot", parent-getter)); registers `CTaskTurretShoot` as a subclass of `CTurretAction` in the engine RTTI/class-factory system.
- `FUN_10984810` (line 1507665) — **RTTI_GetClassInfo_CTaskTurretType** — class self-registration getter (calls FUN_100016b0("CTaskTurretType", parent-getter)); registers `CTaskTurretType` as a subclass of `CTurretDecision` in the engine RTTI/class-factory system.
- `FUN_10981880` (line 1503649) — **RTTI_GetClassInfo_CTaskUnReserveCover** — class self-registration getter (calls FUN_100016b0("CTaskUnReserveCover", parent-getter)); registers `CTaskUnReserveCover` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10980ef0` (line 1502833) — **RTTI_GetClassInfo_CTaskUpdateBlackboard** — class self-registration getter (calls FUN_100016b0("CTaskUpdateBlackboard", parent-getter)); registers `CTaskUpdateBlackboard` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109813a0` (line 1503233) — **RTTI_GetClassInfo_CTaskUpdateBuddyAiming** — class self-registration getter (calls FUN_100016b0("CTaskUpdateBuddyAiming", parent-getter)); registers `CTaskUpdateBuddyAiming` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10980ce0` (line 1502657) — **RTTI_GetClassInfo_CTaskUpdatePathPos** — class self-registration getter (calls FUN_100016b0("CTaskUpdatePathPos", parent-getter)); registers `CTaskUpdatePathPos` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109811f0` (line 1503089) — **RTTI_GetClassInfo_CTaskUseAIBuilding** — class self-registration getter (calls FUN_100016b0("CTaskUseAIBuilding", parent-getter)); registers `CTaskUseAIBuilding` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109811c0` (line 1503073) — **RTTI_GetClassInfo_CTaskUseMountedWeapon** — class self-registration getter (calls FUN_100016b0("CTaskUseMountedWeapon", parent-getter)); registers `CTaskUseMountedWeapon` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_109823f0` (line 1504625) — **RTTI_GetClassInfo_CTaskUseSniperPoint** — class self-registration getter (calls FUN_100016b0("CTaskUseSniperPoint", parent-getter)); registers `CTaskUseSniperPoint` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_10983ec0` (line 1506913) — **RTTI_GetClassInfo_CTaskVehicleAccost** — class self-registration getter (calls FUN_100016b0("CTaskVehicleAccost", parent-getter)); registers `CTaskVehicleAccost` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10983e60` (line 1506881) — **RTTI_GetClassInfo_CTaskVehicleAggressiveMove** — class self-registration getter (calls FUN_100016b0("CTaskVehicleAggressiveMove", parent-getter)); registers `CTaskVehicleAggressiveMove` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10983fe0` (line 1507009) — **RTTI_GetClassInfo_CTaskVehicleBoostFactor** — class self-registration getter (calls FUN_100016b0("CTaskVehicleBoostFactor", parent-getter)); registers `CTaskVehicleBoostFactor` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10983e00` (line 1506849) — **RTTI_GetClassInfo_CTaskVehicleChase** — class self-registration getter (calls FUN_100016b0("CTaskVehicleChase", parent-getter)); registers `CTaskVehicleChase` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_109840a0` (line 1507073) — **RTTI_GetClassInfo_CTaskVehicleCheckExitOnLand** — class self-registration getter (calls FUN_100016b0("CTaskVehicleCheckExitOnLand", parent-getter)); registers `CTaskVehicleCheckExitOnLand` as a subclass of `CVehicleDecision` in the engine RTTI/class-factory system.
- `FUN_109840d0` (line 1507089) — **RTTI_GetClassInfo_CTaskVehicleCheckSpeed** — class self-registration getter (calls FUN_100016b0("CTaskVehicleCheckSpeed", parent-getter)); registers `CTaskVehicleCheckSpeed` as a subclass of `CVehicleDecision` in the engine RTTI/class-factory system.
- `FUN_10984100` (line 1507105) — **RTTI_GetClassInfo_CTaskVehicleCheckUserPriority** — class self-registration getter (calls FUN_100016b0("CTaskVehicleCheckUserPriority", parent-getter)); registers `CTaskVehicleCheckUserPriority` as a subclass of `CVehicleDecision` in the engine RTTI/class-factory system.
- `FUN_10983fb0` (line 1506993) — **RTTI_GetClassInfo_CTaskVehicleEnableSteeringEngine** — class self-registration getter (calls FUN_100016b0("CTaskVehicleEnableSteeringEngine", parent-getter)); registers `CTaskVehicleEnableSteeringEngine` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10983f50` (line 1506961) — **RTTI_GetClassInfo_CTaskVehicleEscapeProjectile** — class self-registration getter (calls FUN_100016b0("CTaskVehicleEscapeProjectile", parent-getter)); registers `CTaskVehicleEscapeProjectile` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10984040` (line 1507041) — **RTTI_GetClassInfo_CTaskVehicleGetBargePos** — class self-registration getter (calls FUN_100016b0("CTaskVehicleGetBargePos", parent-getter)); registers `CTaskVehicleGetBargePos` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10983f80` (line 1506977) — **RTTI_GetClassInfo_CTaskVehicleGetMergePos** — class self-registration getter (calls FUN_100016b0("CTaskVehicleGetMergePos", parent-getter)); registers `CTaskVehicleGetMergePos` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10983e90` (line 1506897) — **RTTI_GetClassInfo_CTaskVehicleGetPierAnchor** — class self-registration getter (calls FUN_100016b0("CTaskVehicleGetPierAnchor", parent-getter)); registers `CTaskVehicleGetPierAnchor` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10983f20` (line 1506945) — **RTTI_GetClassInfo_CTaskVehicleOrientToward** — class self-registration getter (calls FUN_100016b0("CTaskVehicleOrientToward", parent-getter)); registers `CTaskVehicleOrientToward` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10983da0` (line 1506817) — **RTTI_GetClassInfo_CTaskVehiclePathFollow** — class self-registration getter (calls FUN_100016b0("CTaskVehiclePathFollow", parent-getter)); registers `CTaskVehiclePathFollow` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10984900` (line 1507745) — **RTTI_GetClassInfo_CTaskVehicleSelectWeapon** — class self-registration getter (calls FUN_100016b0("CTaskVehicleSelectWeapon", parent-getter)); registers `CTaskVehicleSelectWeapon` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10983e30` (line 1506865) — **RTTI_GetClassInfo_CTaskVehicleSetUserRolePriority** — class self-registration getter (calls FUN_100016b0("CTaskVehicleSetUserRolePriority", parent-getter)); registers `CTaskVehicleSetUserRolePriority` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_109848d0` (line 1507729) — **RTTI_GetClassInfo_CTaskVehicleShoot** — class self-registration getter (calls FUN_100016b0("CTaskVehicleShoot", parent-getter)); registers `CTaskVehicleShoot` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10984010` (line 1507025) — **RTTI_GetClassInfo_CTaskVehicleSink** — class self-registration getter (calls FUN_100016b0("CTaskVehicleSink", parent-getter)); registers `CTaskVehicleSink` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10983dd0` (line 1506833) — **RTTI_GetClassInfo_CTaskVehicleStop** — class self-registration getter (calls FUN_100016b0("CTaskVehicleStop", parent-getter)); registers `CTaskVehicleStop` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10983ef0` (line 1506929) — **RTTI_GetClassInfo_CTaskVehicleTurnAround** — class self-registration getter (calls FUN_100016b0("CTaskVehicleTurnAround", parent-getter)); registers `CTaskVehicleTurnAround` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10984070` (line 1507057) — **RTTI_GetClassInfo_CTaskVehicleTurnCheat** — class self-registration getter (calls FUN_100016b0("CTaskVehicleTurnCheat", parent-getter)); registers `CTaskVehicleTurnCheat` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_10984130` (line 1507121) — **RTTI_GetClassInfo_CTaskVehicleUpdatePathFollow** — class self-registration getter (calls FUN_100016b0("CTaskVehicleUpdatePathFollow", parent-getter)); registers `CTaskVehicleUpdatePathFollow` as a subclass of `CVehicleAction` in the engine RTTI/class-factory system.
- `FUN_109807a0` (line 1502209) — **RTTI_GetClassInfo_CTaskWait** — class self-registration getter (calls FUN_100016b0("CTaskWait", parent-getter)); registers `CTaskWait` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10984b10` (line 1507921) — **RTTI_GetClassInfo_CTaskWaitAnimGroup** — class self-registration getter (calls FUN_100016b0("CTaskWaitAnimGroup", parent-getter)); registers `CTaskWaitAnimGroup` as a subclass of `CPawnBaseAction` in the engine RTTI/class-factory system.
- `FUN_10981040` (line 1502945) — **RTTI_GetClassInfo_CTaskWaitFactExist** — class self-registration getter (calls FUN_100016b0("CTaskWaitFactExist", parent-getter)); registers `CTaskWaitFactExist` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10980e90` (line 1502801) — **RTTI_GetClassInfo_CTaskWaitOriented** — class self-registration getter (calls FUN_100016b0("CTaskWaitOriented", parent-getter)); registers `CTaskWaitOriented` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10984990` (line 1507793) — **RTTI_GetClassInfo_CTaskWaspChase** — class self-registration getter (calls FUN_100016b0("CTaskWaspChase", parent-getter)); registers `CTaskWaspChase` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109849c0` (line 1507809) — **RTTI_GetClassInfo_CTaskWaspMoveTo** — class self-registration getter (calls FUN_100016b0("CTaskWaspMoveTo", parent-getter)); registers `CTaskWaspMoveTo` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_10982120` (line 1504385) — **RTTI_GetClassInfo_CTaskWatchFlyingProjectile** — class self-registration getter (calls FUN_100016b0("CTaskWatchFlyingProjectile", parent-getter)); registers `CTaskWatchFlyingProjectile` as a subclass of `CPawnAction` in the engine RTTI/class-factory system.
- `FUN_1023e5a0` (line 397837) — **RTTI_GetClassInfo_CTeamChatMessage** — class self-registration getter (calls FUN_100016b0("CTeamChatMessage", parent-getter)); registers `CTeamChatMessage` as a subclass of `CChatMessage` in the engine RTTI/class-factory system.
- `FUN_10705df0` (line 1147251) — **RTTI_GetClassInfo_CTeamManager** — class self-registration getter (calls FUN_100016b0("CTeamManager", parent-getter)); registers `CTeamManager` as a subclass of `ITeamManager` in the engine RTTI/class-factory system.
- `FUN_104ef7f0` (line 854010) — **RTTI_GetClassInfo_CTerm** — class self-registration getter (calls FUN_100016b0("CTerm", parent-getter)); registers `CTerm` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_109e54b0` (line 1562539) — **RTTI_GetClassInfo_CTermFactList** — class self-registration getter (calls FUN_100016b0("CTermFactList", parent-getter)); registers `CTermFactList` as a subclass of `CTerm` in the engine RTTI/class-factory system.
- `FUN_104ef8b0` (line 854059) — **RTTI_GetClassInfo_CTermSingleFact** — class self-registration getter (calls FUN_100016b0("CTermSingleFact", parent-getter)); registers `CTermSingleFact` as a subclass of `CTerm` in the engine RTTI/class-factory system.
- `FUN_103b5530` (line 643599) — **RTTI_GetClassInfo_CTextureMipResource** — class self-registration getter (calls FUN_100016b0("CTextureMipResource", parent-getter)); registers `CTextureMipResource` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_1018d200` (line 274665) — **RTTI_GetClassInfo_CTextureResource** — class self-registration getter (calls FUN_100016b0("CTextureResource", parent-getter)); registers `CTextureResource` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_1097f3d0` (line 1501424) — **RTTI_GetClassInfo_CThanatorAgent** — class self-registration getter (calls FUN_100016b0("CThanatorAgent", parent-getter)); registers `CThanatorAgent` as a subclass of `CBtzAnimalAgent` in the engine RTTI/class-factory system.
- `FUN_104c9470` (line 830266) — **RTTI_GetClassInfo_CThinPropaneTank** — class self-registration getter (calls FUN_100016b0("CThinPropaneTank", parent-getter)); registers `CThinPropaneTank` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_104c9f00` (line 830636) — **RTTI_GetClassInfo_CToxicCloudComponent** — class self-registration getter (calls FUN_100016b0("CToxicCloudComponent", parent-getter)); registers `CToxicCloudComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_107aaad0` (line 1241133) — **RTTI_GetClassInfo_CTrackingEvent** — class self-registration getter (calls FUN_100016b0("CTrackingEvent", parent-getter)); registers `CTrackingEvent` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_107aab40` (line 1241168) — **RTTI_GetClassInfo_CTrackingEventFPSClientToggle** — class self-registration getter (calls FUN_100016b0("CTrackingEventFPSClientToggle", parent-getter)); registers `CTrackingEventFPSClientToggle` as a subclass of `CTrackingEventLevelToggle` in the engine RTTI/class-factory system.
- `FUN_107aab10` (line 1241152) — **RTTI_GetClassInfo_CTrackingEventLevelToggle** — class self-registration getter (calls FUN_100016b0("CTrackingEventLevelToggle", parent-getter)); registers `CTrackingEventLevelToggle` as a subclass of `CTrackingEvent` in the engine RTTI/class-factory system.
- `FUN_104cbed0` (line 832026) — **RTTI_GetClassInfo_CTrackingService** — class self-registration getter (calls FUN_100016b0("CTrackingService", parent-getter)); registers `CTrackingService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_101356e0` (line 215431) — **RTTI_GetClassInfo_CTransmissionTableInfoMsg** — class self-registration getter (calls FUN_100016b0("CTransmissionTableInfoMsg", parent-getter)); registers `CTransmissionTableInfoMsg` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_104ca380` (line 830876) — **RTTI_GetClassInfo_CTrapComponent** — class self-registration getter (calls FUN_100016b0("CTrapComponent", parent-getter)); registers `CTrapComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_106d1cf0` (line 1116942) — **RTTI_GetClassInfo_CTravelStartOperation** — class self-registration getter (calls FUN_100016b0("CTravelStartOperation", parent-getter)); registers `CTravelStartOperation` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_106d1d20` (line 1116958) — **RTTI_GetClassInfo_CTravelStopOperation** — class self-registration getter (calls FUN_100016b0("CTravelStopOperation", parent-getter)); registers `CTravelStopOperation` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_107b2ec0` (line 1246250) — **RTTI_GetClassInfo_CTriggerChangeCountEvent** — class self-registration getter (calls FUN_100016b0("CTriggerChangeCountEvent", parent-getter)); registers `CTriggerChangeCountEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1021c990` (line 375550) — **RTTI_GetClassInfo_CTriggerComponent** — class self-registration getter (calls FUN_100016b0("CTriggerComponent", parent-getter)); registers `CTriggerComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_105e0b30` (line 985509) — **RTTI_GetClassInfo_CTriggerEnableEvent** — class self-registration getter (calls FUN_100016b0("CTriggerEnableEvent", parent-getter)); registers `CTriggerEnableEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_102dc5f0` (line 497965) — **RTTI_GetClassInfo_CTriggerEvent** — class self-registration getter (calls FUN_100016b0("CTriggerEvent", parent-getter)); registers `CTriggerEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1052a7c0` (line 888868) — **RTTI_GetClassInfo_CTriggerSimpleEvent** — class self-registration getter (calls FUN_100016b0("CTriggerSimpleEvent", parent-getter)); registers `CTriggerSimpleEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_10984780` (line 1507617) — **RTTI_GetClassInfo_CTurretAction** — class self-registration getter (calls FUN_100016b0("CTurretAction", parent-getter)); registers `CTurretAction` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_109847b0` (line 1507633) — **RTTI_GetClassInfo_CTurretDecision** — class self-registration getter (calls FUN_100016b0("CTurretDecision", parent-getter)); registers `CTurretDecision` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_104c95f0` (line 830330) — **RTTI_GetClassInfo_CTurretSoundAndFXComponent** — class self-registration getter (calls FUN_100016b0("CTurretSoundAndFXComponent", parent-getter)); registers `CTurretSoundAndFXComponent` as a subclass of `CCreatureSoundAndFXComponent` in the engine RTTI/class-factory system.
- `FUN_105f9d20` (line 999332) — **RTTI_GetClassInfo_CTutorial** — class self-registration getter (calls FUN_100016b0("CTutorial", parent-getter)); registers `CTutorial` as a subclass of `CChallenge` in the engine RTTI/class-factory system.
- `FUN_1003ced0` (line 41743) — **RTTI_GetClassInfo_CUIStrategy** — class self-registration getter (calls FUN_100016b0("CUIStrategy", parent-getter)); registers `CUIStrategy` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_106eae80` (line 1131043) — **RTTI_GetClassInfo_CUIStrategyService** — class self-registration getter (calls FUN_100016b0("CUIStrategyService", parent-getter)); registers `CUIStrategyService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_10693040` (line 1085207) — **RTTI_GetClassInfo_CUseEquipmentEvent** — class self-registration getter (calls FUN_100016b0("CUseEquipmentEvent", parent-getter)); registers `CUseEquipmentEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_107ec070` (line 1280084) — **RTTI_GetClassInfo_CUsePlantedEquipmentEvent** — class self-registration getter (calls FUN_100016b0("CUsePlantedEquipmentEvent", parent-getter)); registers `CUsePlantedEquipmentEvent` as a subclass of `CUseEquipmentEvent` in the engine RTTI/class-factory system.
- `FUN_10a13150` (line 1582552) — **RTTI_GetClassInfo_CVariantParameter** — class self-registration getter (calls FUN_100016b0("CVariantParameter", parent-getter)); registers `CVariantParameter` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_104c9f60` (line 830652) — **RTTI_GetClassInfo_CVehicle** — class self-registration getter (calls FUN_100016b0("CVehicle", parent-getter)); registers `CVehicle` as a subclass of `CVehicleBase` in the engine RTTI/class-factory system.
- `FUN_10983980` (line 1506465) — **RTTI_GetClassInfo_CVehicleAction** — class self-registration getter (calls FUN_100016b0("CVehicleAction", parent-getter)); registers `CVehicleAction` as a subclass of `CAgentAction` in the engine RTTI/class-factory system.
- `FUN_1097e250` (line 1501010) — **RTTI_GetClassInfo_CVehicleAgent** — class self-registration getter (calls FUN_100016b0("CVehicleAgent", parent-getter)); registers `CVehicleAgent` as a subclass of `CGameAgent` in the engine RTTI/class-factory system.
- `FUN_104c9960` (line 830428) — **RTTI_GetClassInfo_CVehicleBase** — class self-registration getter (calls FUN_100016b0("CVehicleBase", parent-getter)); registers `CVehicleBase` as a subclass of `CGameObject` in the engine RTTI/class-factory system.
- `FUN_1076d1d0` (line 1203577) — **RTTI_GetClassInfo_CVehicleCopterPhysComponent** — class self-registration getter (calls FUN_100016b0("CVehicleCopterPhysComponent", parent-getter)); registers `CVehicleCopterPhysComponent` as a subclass of `CVehiclePhysComponent` in the engine RTTI/class-factory system.
- `FUN_10771830` (line 1205892) — **RTTI_GetClassInfo_CVehicleDamagedPartEvent** — class self-registration getter (calls FUN_100016b0("CVehicleDamagedPartEvent", parent-getter)); registers `CVehicleDamagedPartEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_10983d70` (line 1506801) — **RTTI_GetClassInfo_CVehicleDecision** — class self-registration getter (calls FUN_100016b0("CVehicleDecision", parent-getter)); registers `CVehicleDecision` as a subclass of `CAgentDecision` in the engine RTTI/class-factory system.
- `FUN_10729df0` (line 1166867) — **RTTI_GetClassInfo_CVehicleEngineFloodedEvent** — class self-registration getter (calls FUN_100016b0("CVehicleEngineFloodedEvent", parent-getter)); registers `CVehicleEngineFloodedEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_10563160` (line 919321) — **RTTI_GetClassInfo_CVehicleEventExplosion** — class self-registration getter (calls FUN_100016b0("CVehicleEventExplosion", parent-getter)); registers `CVehicleEventExplosion` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_105631d0` (line 919358) — **RTTI_GetClassInfo_CVehicleEventFinalExplosion** — class self-registration getter (calls FUN_100016b0("CVehicleEventFinalExplosion", parent-getter)); registers `CVehicleEventFinalExplosion` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1052a830` (line 888905) — **RTTI_GetClassInfo_CVehicleEventIsDestructable** — class self-registration getter (calls FUN_100016b0("CVehicleEventIsDestructable", parent-getter)); registers `CVehicleEventIsDestructable` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1059a730` (line 949592) — **RTTI_GetClassInfo_CVehicleEventLandTrigger** — class self-registration getter (calls FUN_100016b0("CVehicleEventLandTrigger", parent-getter)); registers `CVehicleEventLandTrigger` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1052a8a0` (line 888942) — **RTTI_GetClassInfo_CVehicleEventSetEngineBroken** — class self-registration getter (calls FUN_100016b0("CVehicleEventSetEngineBroken", parent-getter)); registers `CVehicleEventSetEngineBroken` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1076d1a0` (line 1203561) — **RTTI_GetClassInfo_CVehicleFloatingPhysComponent** — class self-registration getter (calls FUN_100016b0("CVehicleFloatingPhysComponent", parent-getter)); registers `CVehicleFloatingPhysComponent` as a subclass of `CVehiclePhysComponent` in the engine RTTI/class-factory system.
- `FUN_1052ec10` (line 891296) — **RTTI_GetClassInfo_CVehicleFlyingPhysComponent** — class self-registration getter (calls FUN_100016b0("CVehicleFlyingPhysComponent", parent-getter)); registers `CVehicleFlyingPhysComponent` as a subclass of `CVehiclePhysComponent` in the engine RTTI/class-factory system.
- `FUN_101a5950` (line 291446) — **RTTI_GetClassInfo_CVehicleMaterialComponent** — class self-registration getter (calls FUN_100016b0("CVehicleMaterialComponent", parent-getter)); registers `CVehicleMaterialComponent` as a subclass of `CCustomMaterialComponent` in the engine RTTI/class-factory system.
- `FUN_1076e630` (line 1204294) — **RTTI_GetClassInfo_CVehicleNetMessageExplosion** — class self-registration getter (calls FUN_100016b0("CVehicleNetMessageExplosion", parent-getter)); registers `CVehicleNetMessageExplosion` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_106906d0` (line 1084074) — **RTTI_GetClassInfo_CVehicleNetworkComponent** — class self-registration getter (calls FUN_100016b0("CVehicleNetworkComponent", parent-getter)); registers `CVehicleNetworkComponent` as a subclass of `CNetworkComponent` in the engine RTTI/class-factory system.
- `FUN_1076d170` (line 1203545) — **RTTI_GetClassInfo_CVehicleParagliderPhysComponent** — class self-registration getter (calls FUN_100016b0("CVehicleParagliderPhysComponent", parent-getter)); registers `CVehicleParagliderPhysComponent` as a subclass of `CVehiclePhysComponent` in the engine RTTI/class-factory system.
- `FUN_1052ebe0` (line 891280) — **RTTI_GetClassInfo_CVehiclePhysComponent** — class self-registration getter (calls FUN_100016b0("CVehiclePhysComponent", parent-getter)); registers `CVehiclePhysComponent` as a subclass of `CPhysComponent` in the engine RTTI/class-factory system.
- `FUN_10984190` (line 1507153) — **RTTI_GetClassInfo_CVehicleScanner** — class self-registration getter (calls FUN_100016b0("CVehicleScanner", parent-getter)); registers `CVehicleScanner` as a subclass of `CAgentScanner` in the engine RTTI/class-factory system.
- `FUN_10980470` (line 1501937) — **RTTI_GetClassInfo_CVehicleSmartTerrain** — class self-registration getter (calls FUN_100016b0("CVehicleSmartTerrain", parent-getter)); registers `CVehicleSmartTerrain` as a subclass of `CSmartTerrain` in the engine RTTI/class-factory system.
- `FUN_1076d470` (line 1203641) — **RTTI_GetClassInfo_CVehicleSpawnedPartNetDescriptor** — class self-registration getter (calls FUN_100016b0("CVehicleSpawnedPartNetDescriptor", parent-getter)); registers `CVehicleSpawnedPartNetDescriptor` as a subclass of `CNetDescriptor` in the engine RTTI/class-factory system.
- `FUN_109a3f50` (line 1527023) — **RTTI_GetClassInfo_CVehicleStrategy** — class self-registration getter (calls FUN_100016b0("CVehicleStrategy", parent-getter)); registers `CVehicleStrategy` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_109a4000` (line 1527079) — **RTTI_GetClassInfo_CVehicleStrategyAIObject** — class self-registration getter (calls FUN_100016b0("CVehicleStrategyAIObject", parent-getter)); registers `CVehicleStrategyAIObject` as a subclass of `CVehicleStrategy` in the engine RTTI/class-factory system.
- `FUN_109ca590` (line 1548851) — **RTTI_GetClassInfo_CVehicleStrategyEntity** — class self-registration getter (calls FUN_100016b0("CVehicleStrategyEntity", parent-getter)); registers `CVehicleStrategyEntity` as a subclass of `CVehicleStrategy` in the engine RTTI/class-factory system.
- `FUN_109a3f90` (line 1527042) — **RTTI_GetClassInfo_CVehicleStrategyPosition** — class self-registration getter (calls FUN_100016b0("CVehicleStrategyPosition", parent-getter)); registers `CVehicleStrategyPosition` as a subclass of `CVehicleStrategy` in the engine RTTI/class-factory system.
- `FUN_10565bb0` (line 920824) — **RTTI_GetClassInfo_CVehicleType** — class self-registration getter (calls FUN_100016b0("CVehicleType", parent-getter)); registers `CVehicleType` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_105d2a10` (line 978022) — **RTTI_GetClassInfo_CVehicleTypeEngine** — class self-registration getter (calls FUN_100016b0("CVehicleTypeEngine", parent-getter)); registers `CVehicleTypeEngine` as a subclass of `CVehicleType` in the engine RTTI/class-factory system.
- `FUN_10565be0` (line 920840) — **RTTI_GetClassInfo_CVehicleTypeFlying** — class self-registration getter (calls FUN_100016b0("CVehicleTypeFlying", parent-getter)); registers `CVehicleTypeFlying` as a subclass of `CVehicleType` in the engine RTTI/class-factory system.
- `FUN_106d4180` (line 1117704) — **RTTI_GetClassInfo_CVehicleTypeWheeled** — class self-registration getter (calls FUN_100016b0("CVehicleTypeWheeled", parent-getter)); registers `CVehicleTypeWheeled` as a subclass of `CVehicleTypeEngine` in the engine RTTI/class-factory system.
- `FUN_1076d140` (line 1203529) — **RTTI_GetClassInfo_CVehicleWheeledPhysComponent** — class self-registration getter (calls FUN_100016b0("CVehicleWheeledPhysComponent", parent-getter)); registers `CVehicleWheeledPhysComponent` as a subclass of `CVehiclePhysComponent` in the engine RTTI/class-factory system.
- `FUN_1097f310` (line 1501360) — **RTTI_GetClassInfo_CViperwolfAgent** — class self-registration getter (calls FUN_100016b0("CViperwolfAgent", parent-getter)); registers `CViperwolfAgent` as a subclass of `CBtzAnimalAgent` in the engine RTTI/class-factory system.
- `FUN_101a5860` (line 291366) — **RTTI_GetClassInfo_CVisibilityOcclusionVolumeComponent** — class self-registration getter (calls FUN_100016b0("CVisibilityOcclusionVolumeComponent", parent-getter)); registers `CVisibilityOcclusionVolumeComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1097ddd0` (line 1500942) — **RTTI_GetClassInfo_CVisibleObject** — class self-registration getter (calls FUN_100016b0("CVisibleObject", parent-getter)); registers `CVisibleObject` as a subclass of `CGameAIObject` in the engine RTTI/class-factory system.
- `FUN_102530e0` (line 410250) — **RTTI_GetClassInfo_CVisibleObjectEvent** — class self-registration getter (calls FUN_100016b0("CVisibleObjectEvent", parent-getter)); registers `CVisibleObjectEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_101a73b0` (line 293309) — **RTTI_GetClassInfo_CVoiceFxManager** — class self-registration getter (calls FUN_100016b0("CVoiceFxManager", parent-getter)); registers `CVoiceFxManager` as a subclass of `CSingletonEntity` in the engine RTTI/class-factory system.
- `FUN_106f0a40` (line 1135136) — **RTTI_GetClassInfo_CVoteQuestion** — class self-registration getter (calls FUN_100016b0("CVoteQuestion", parent-getter)); registers `CVoteQuestion` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_106f0ab0` (line 1135166) — **RTTI_GetClassInfo_CVoteQuestionMatch** — class self-registration getter (calls FUN_100016b0("CVoteQuestionMatch", parent-getter)); registers `CVoteQuestionMatch` as a subclass of `CVoteQuestion` in the engine RTTI/class-factory system.
- `FUN_106f0b70` (line 1135216) — **RTTI_GetClassInfo_CVoteQuestionPlayer** — class self-registration getter (calls FUN_100016b0("CVoteQuestionPlayer", parent-getter)); registers `CVoteQuestionPlayer` as a subclass of `CVoteQuestion` in the engine RTTI/class-factory system.
- `FUN_106f01e0` (line 1134834) — **RTTI_GetClassInfo_CVotingService** — class self-registration getter (calls FUN_100016b0("CVotingService", parent-getter)); registers `CVotingService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_104cc460` (line 832271) — **RTTI_GetClassInfo_CWagerRegion** — class self-registration getter (calls FUN_100016b0("CWagerRegion", parent-getter)); registers `CWagerRegion` as a subclass of `CBasicRegionEntity` in the engine RTTI/class-factory system.
- `FUN_104c9cc0` (line 830556) — **RTTI_GetClassInfo_CWeapon** — class self-registration getter (calls FUN_100016b0("CWeapon", parent-getter)); registers `CWeapon` as a subclass of `CEquipmentBase` in the engine RTTI/class-factory system.
- `FUN_1076d670` (line 1203688) — **RTTI_GetClassInfo_CWeaponControllerMemento** — class self-registration getter (calls FUN_100016b0("CWeaponControllerMemento", parent-getter)); registers `CWeaponControllerMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_105fab90` (line 999975) — **RTTI_GetClassInfo_CWeaponEventBulletShot** — class self-registration getter (calls FUN_100016b0("CWeaponEventBulletShot", parent-getter)); registers `CWeaponEventBulletShot` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_105d2a80` (line 978059) — **RTTI_GetClassInfo_CWeaponEventFireBullet** — class self-registration getter (calls FUN_100016b0("CWeaponEventFireBullet", parent-getter)); registers `CWeaponEventFireBullet` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_10815440` (line 1305463) — **RTTI_GetClassInfo_CWeaponEventReload** — class self-registration getter (calls FUN_100016b0("CWeaponEventReload", parent-getter)); registers `CWeaponEventReload` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_1074c780` (line 1187949) — **RTTI_GetClassInfo_CWeaponFireBulletProperties** — class self-registration getter (calls FUN_100016b0("CWeaponFireBulletProperties", parent-getter)); registers `CWeaponFireBulletProperties` as a subclass of `CWeaponFireProperties` in the engine RTTI/class-factory system.
- `FUN_1062ec60` (line 1028877) — **RTTI_GetClassInfo_CWeaponFireBulletStrategy** — class self-registration getter (calls FUN_100016b0("CWeaponFireBulletStrategy", parent-getter)); registers `CWeaponFireBulletStrategy` as a subclass of `CWeaponFireStrategy` in the engine RTTI/class-factory system.
- `FUN_10581ca0` (line 936316) — **RTTI_GetClassInfo_CWeaponFireMeleeStrategy** — class self-registration getter (calls FUN_100016b0("CWeaponFireMeleeStrategy", parent-getter)); registers `CWeaponFireMeleeStrategy` as a subclass of `CWeaponFireStrategy` in the engine RTTI/class-factory system.
- `FUN_1074c820` (line 1187986) — **RTTI_GetClassInfo_CWeaponFireProjectileProperties** — class self-registration getter (calls FUN_100016b0("CWeaponFireProjectileProperties", parent-getter)); registers `CWeaponFireProjectileProperties` as a subclass of `CWeaponFireBulletProperties` in the engine RTTI/class-factory system.
- `FUN_1062ec90` (line 1028893) — **RTTI_GetClassInfo_CWeaponFireProjectileStrategy** — class self-registration getter (calls FUN_100016b0("CWeaponFireProjectileStrategy", parent-getter)); registers `CWeaponFireProjectileStrategy` as a subclass of `CWeaponFireBulletStrategy` in the engine RTTI/class-factory system.
- `FUN_1074c750` (line 1187933) — **RTTI_GetClassInfo_CWeaponFireProperties** — class self-registration getter (calls FUN_100016b0("CWeaponFireProperties", parent-getter)); registers `CWeaponFireProperties` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_10581ba0` (line 936264) — **RTTI_GetClassInfo_CWeaponFireStrategy** — class self-registration getter (calls FUN_100016b0("CWeaponFireStrategy", parent-getter)); registers `CWeaponFireStrategy` as a subclass of `CEquipmentUseStrategy` in the engine RTTI/class-factory system.
- `FUN_107ebf90` (line 1280002) — **RTTI_GetClassInfo_CWeaponIEDMemento** — class self-registration getter (calls FUN_100016b0("CWeaponIEDMemento", parent-getter)); registers `CWeaponIEDMemento` as a subclass of `CWeaponProjectileMemento` in the engine RTTI/class-factory system.
- `FUN_107ebf30` (line 1279970) — **RTTI_GetClassInfo_CWeaponMemento** — class self-registration getter (calls FUN_100016b0("CWeaponMemento", parent-getter)); registers `CWeaponMemento` as a subclass of `CNetDataContainer` in the engine RTTI/class-factory system.
- `FUN_108206a0` (line 1312703) — **RTTI_GetClassInfo_CWeaponProjectileControllerMemento** — class self-registration getter (calls FUN_100016b0("CWeaponProjectileControllerMemento", parent-getter)); registers `CWeaponProjectileControllerMemento` as a subclass of `CWeaponControllerMemento` in the engine RTTI/class-factory system.
- `FUN_107ebf60` (line 1279986) — **RTTI_GetClassInfo_CWeaponProjectileMemento** — class self-registration getter (calls FUN_100016b0("CWeaponProjectileMemento", parent-getter)); registers `CWeaponProjectileMemento` as a subclass of `CWeaponMemento` in the engine RTTI/class-factory system.
- `FUN_1054f420` (line 908927) — **RTTI_GetClassInfo_CWeaponUsedEvent** — class self-registration getter (calls FUN_100016b0("CWeaponUsedEvent", parent-getter)); registers `CWeaponUsedEvent` as a subclass of `CEntityEvent` in the engine RTTI/class-factory system.
- `FUN_10581c70` (line 936300) — **RTTI_GetClassInfo_CWeaponsService** — class self-registration getter (calls FUN_100016b0("CWeaponsService", parent-getter)); registers `CWeaponsService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_101a5cd0` (line 291734) — **RTTI_GetClassInfo_CWorldSector** — class self-registration getter (calls FUN_100016b0("CWorldSector", parent-getter)); registers `CWorldSector` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_100c2a90` (line 138894) — **RTTI_GetClassInfo_CXmlResource** — class self-registration getter (calls FUN_100016b0("CXmlResource", parent-getter)); registers `CXmlResource` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_101a6030` (line 291910) — **RTTI_GetClassInfo_CZoneInfoComponent** — class self-registration getter (calls FUN_100016b0("CZoneInfoComponent", parent-getter)); registers `CZoneInfoComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a7320` (line 293261) — **RTTI_GetClassInfo_CZoneLogicManager** — class self-registration getter (calls FUN_100016b0("CZoneLogicManager", parent-getter)); registers `CZoneLogicManager` as a subclass of `CSingletonEntity` in the engine RTTI/class-factory system.
- `FUN_101a67d0` (line 292427) — **RTTI_GetClassInfo_CZoneLogicRegion** — class self-registration getter (calls FUN_100016b0("CZoneLogicRegion", parent-getter)); registers `CZoneLogicRegion` as a subclass of `CBasicRegionEntity` in the engine RTTI/class-factory system.
- `FUN_1018cf00` (line 274523) — **RTTI_GetClassInfo_CZoneSectorResource** — class self-registration getter (calls FUN_100016b0("CZoneSectorResource", parent-getter)); registers `CZoneSectorResource` as a subclass of `CResource` in the engine RTTI/class-factory system.
- `FUN_1097fc60` (line 1501794) — **RTTI_GetClassInfo_ChaliceAgent** — class self-registration getter (calls FUN_100016b0("ChaliceAgent", parent-getter)); registers `ChaliceAgent` as a subclass of `PlantAgent` in the engine RTTI/class-factory system.
- `FUN_1097f460` (line 1501472) — **RTTI_GetClassInfo_HammerheadAgent** — class self-registration getter (calls FUN_100016b0("HammerheadAgent", parent-getter)); registers `HammerheadAgent` as a subclass of `CBtzAnimalAgent` in the engine RTTI/class-factory system.
- `FUN_101a0620` (line 287378) — **RTTI_GetClassInfo_IAuthorizationService** — class self-registration getter (calls FUN_100016b0("IAuthorizationService", parent-getter)); registers `IAuthorizationService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_102f1f90` (line 513951) — **RTTI_GetClassInfo_ICollectionIgnitorComponent** — class self-registration getter (calls FUN_100016b0("ICollectionIgnitorComponent", parent-getter)); registers `ICollectionIgnitorComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_102cf8e0` (line 490487) — **RTTI_GetClassInfo_ICountersService** — class self-registration getter (calls FUN_100016b0("ICountersService", parent-getter)); registers `ICountersService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_100c1d10` (line 138152) — **RTTI_GetClassInfo_IFile** — class self-registration getter (calls FUN_100016b0("IFile", parent-getter)); registers `IFile` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_1054f310` (line 908889) — **RTTI_GetClassInfo_IGOStateContext** — class self-registration getter (calls FUN_100016b0("IGOStateContext", parent-getter)); registers `IGOStateContext` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_101a05c0` (line 287346) — **RTTI_GetClassInfo_IGameMessageService** — class self-registration getter (calls FUN_100016b0("IGameMessageService", parent-getter)); registers `IGameMessageService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1003cb50` (line 41451) — **RTTI_GetClassInfo_IGameModeService** — class self-registration getter (calls FUN_100016b0("IGameModeService", parent-getter)); registers `IGameModeService` as a subclass of `CNomadObject` in the engine RTTI/class-factory system.
- `FUN_101983d0` (line 280838) — **RTTI_GetClassInfo_IGameSoundService** — class self-registration getter (calls FUN_100016b0("IGameSoundService", parent-getter)); registers `IGameSoundService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_104f9430` (line 860145) — **RTTI_GetClassInfo_IGameStatsService** — class self-registration getter (calls FUN_100016b0("IGameStatsService", parent-getter)); registers `IGameStatsService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1018d1d0` (line 274649) — **RTTI_GetClassInfo_IMagmaDebugTextService** — class self-registration getter (calls FUN_100016b0("IMagmaDebugTextService", parent-getter)); registers `IMagmaDebugTextService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1023d740` (line 397194) — **RTTI_GetClassInfo_IOnValueChangedParam** — class self-registration getter (calls FUN_100016b0("IOnValueChangedParam", parent-getter)); registers `IOnValueChangedParam` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_10136800` (line 216359) — **RTTI_GetClassInfo_IOperation** — class self-registration getter (calls FUN_100016b0("IOperation", parent-getter)); registers `IOperation` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_10046070` (line 46304) — **RTTI_GetClassInfo_IPlayer** — class self-registration getter (calls FUN_100016b0("IPlayer", parent-getter)); registers `IPlayer` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_100460b0` (line 46323) — **RTTI_GetClassInfo_IPlayerService** — class self-registration getter (calls FUN_100016b0("IPlayerService", parent-getter)); registers `IPlayerService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_101a6aa0` (line 292667) — **RTTI_GetClassInfo_IShapeComponent** — class self-registration getter (calls FUN_100016b0("IShapeComponent", parent-getter)); registers `IShapeComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_101a6710` (line 292363) — **RTTI_GetClassInfo_IShapeEntity** — class self-registration getter (calls FUN_100016b0("IShapeEntity", parent-getter)); registers `IShapeEntity` as a subclass of `COmniMapEntity` in the engine RTTI/class-factory system.
- `FUN_1005a9d0` (line 61690) — **RTTI_GetClassInfo_ISpawnPointService** — class self-registration getter (calls FUN_100016b0("ISpawnPointService", parent-getter)); registers `ISpawnPointService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_10705dc0` (line 1147235) — **RTTI_GetClassInfo_ITeamManager** — class self-registration getter (calls FUN_100016b0("ITeamManager", parent-getter)); registers `ITeamManager` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_108d98d0` (line 1419073) — **RTTI_GetClassInfo_MoveData** — class self-registration getter (calls FUN_100016b0("MoveData", parent-getter)); registers `MoveData` as a subclass of `ActionData` in the engine RTTI/class-factory system.
- `FUN_104c9ea0` (line 830604) — **RTTI_GetClassInfo_Plant** — class self-registration getter (calls FUN_100016b0("Plant", parent-getter)); registers `Plant` as a subclass of `CPawnBase` in the engine RTTI/class-factory system.
- `FUN_1097fba0` (line 1501730) — **RTTI_GetClassInfo_PlantAgent** — class self-registration getter (calls FUN_100016b0("PlantAgent", parent-getter)); registers `PlantAgent` as a subclass of `CPawnBaseAgent` in the engine RTTI/class-factory system.
- `FUN_1003cc60` (line 41535) — **RTTI_GetClassInfo_PlazaArmouryService** — class self-registration getter (calls FUN_100016b0("PlazaArmouryService", parent-getter)); registers `PlazaArmouryService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1003cff0` (line 41839) — **RTTI_GetClassInfo_PlazaArmouryUIStrategy** — class self-registration getter (calls FUN_100016b0("PlazaArmouryUIStrategy", parent-getter)); registers `PlazaArmouryUIStrategy` as a subclass of `CUIStrategy` in the engine RTTI/class-factory system.
- `FUN_1003cc90` (line 41551) — **RTTI_GetClassInfo_PlazaChatService** — class self-registration getter (calls FUN_100016b0("PlazaChatService", parent-getter)); registers `PlazaChatService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1003ccc0` (line 41567) — **RTTI_GetClassInfo_PlazaContextualInteractionService** — class self-registration getter (calls FUN_100016b0("PlazaContextualInteractionService", parent-getter)); registers `PlazaContextualInteractionService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1003cf60` (line 41791) — **RTTI_GetClassInfo_PlazaContextualInteractionUIStrategy** — class self-registration getter (calls FUN_100016b0("PlazaContextualInteractionUIStrategy", parent-getter)); registers `PlazaContextualInteractionUIStrategy` as a subclass of `CUIStrategy` in the engine RTTI/class-factory system.
- `FUN_1003ccf0` (line 41583) — **RTTI_GetClassInfo_PlazaCoreService** — class self-registration getter (calls FUN_100016b0("PlazaCoreService", parent-getter)); registers `PlazaCoreService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1003cde0` (line 41663) — **RTTI_GetClassInfo_PlazaFriendService** — class self-registration getter (calls FUN_100016b0("PlazaFriendService", parent-getter)); registers `PlazaFriendService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1003cfc0` (line 41823) — **RTTI_GetClassInfo_PlazaFriendUIStrategy** — class self-registration getter (calls FUN_100016b0("PlazaFriendUIStrategy", parent-getter)); registers `PlazaFriendUIStrategy` as a subclass of `CUIStrategy` in the engine RTTI/class-factory system.
- `FUN_1003cbc0` (line 41485) — **RTTI_GetClassInfo_PlazaGameOperationBuilder** — class self-registration getter (calls FUN_100016b0("PlazaGameOperationBuilder", parent-getter)); registers `PlazaGameOperationBuilder` as a subclass of `CGameOperationBuilder` in the engine RTTI/class-factory system.
- `FUN_1003cc30` (line 41519) — **RTTI_GetClassInfo_PlazaGameOperationJoin** — class self-registration getter (calls FUN_100016b0("PlazaGameOperationJoin", parent-getter)); registers `PlazaGameOperationJoin` as a subclass of `CGameOperation` in the engine RTTI/class-factory system.
- `FUN_1003cf00` (line 41759) — **RTTI_GetClassInfo_PlazaHudUIStrategy** — class self-registration getter (calls FUN_100016b0("PlazaHudUIStrategy", parent-getter)); registers `PlazaHudUIStrategy` as a subclass of `CUIStrategy` in the engine RTTI/class-factory system.
- `FUN_1003ce70` (line 41711) — **RTTI_GetClassInfo_PlazaMetaGameService** — class self-registration getter (calls FUN_100016b0("PlazaMetaGameService", parent-getter)); registers `PlazaMetaGameService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1003d020` (line 41855) — **RTTI_GetClassInfo_PlazaMetaGameUIStrategy** — class self-registration getter (calls FUN_100016b0("PlazaMetaGameUIStrategy", parent-getter)); registers `PlazaMetaGameUIStrategy` as a subclass of `CUIStrategy` in the engine RTTI/class-factory system.
- `FUN_1003cd20` (line 41599) — **RTTI_GetClassInfo_PlazaNetworkService** — class self-registration getter (calls FUN_100016b0("PlazaNetworkService", parent-getter)); registers `PlazaNetworkService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1003cf30` (line 41775) — **RTTI_GetClassInfo_PlazaOverHeadPanelUIStrategy** — class self-registration getter (calls FUN_100016b0("PlazaOverHeadPanelUIStrategy", parent-getter)); registers `PlazaOverHeadPanelUIStrategy` as a subclass of `CUIStrategy` in the engine RTTI/class-factory system.
- `FUN_1003d0b0` (line 41903) — **RTTI_GetClassInfo_PlazaPawnBeautifierRemotePlayer** — class self-registration getter (calls FUN_100016b0("PlazaPawnBeautifierRemotePlayer", parent-getter)); registers `PlazaPawnBeautifierRemotePlayer` as a subclass of `CPawnBeautifier` in the engine RTTI/class-factory system.
- `FUN_1003d0e0` (line 41919) — **RTTI_GetClassInfo_PlazaPawnRemotePlayerComponent** — class self-registration getter (calls FUN_100016b0("PlazaPawnRemotePlayerComponent", parent-getter)); registers `PlazaPawnRemotePlayerComponent` as a subclass of `CEntityComponent` in the engine RTTI/class-factory system.
- `FUN_1003cdb0` (line 41647) — **RTTI_GetClassInfo_PlazaPlayGroupService** — class self-registration getter (calls FUN_100016b0("PlazaPlayGroupService", parent-getter)); registers `PlazaPlayGroupService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1003cf90` (line 41807) — **RTTI_GetClassInfo_PlazaPlayGroupUIStrategy** — class self-registration getter (calls FUN_100016b0("PlazaPlayGroupUIStrategy", parent-getter)); registers `PlazaPlayGroupUIStrategy` as a subclass of `CUIStrategy` in the engine RTTI/class-factory system.
- `FUN_1003ce10` (line 41679) — **RTTI_GetClassInfo_PlazaPlayerProfileService** — class self-registration getter (calls FUN_100016b0("PlazaPlayerProfileService", parent-getter)); registers `PlazaPlayerProfileService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1003cd80` (line 41631) — **RTTI_GetClassInfo_PlazaPlayerService** — class self-registration getter (calls FUN_100016b0("PlazaPlayerService", parent-getter)); registers `PlazaPlayerService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1003ce40` (line 41695) — **RTTI_GetClassInfo_PlazaVoiceChatService** — class self-registration getter (calls FUN_100016b0("PlazaVoiceChatService", parent-getter)); registers `PlazaVoiceChatService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1003cea0` (line 41727) — **RTTI_GetClassInfo_PlazaWarStatisticService** — class self-registration getter (calls FUN_100016b0("PlazaWarStatisticService", parent-getter)); registers `PlazaWarStatisticService` as a subclass of `IGameModeService` in the engine RTTI/class-factory system.
- `FUN_1003d050` (line 41871) — **RTTI_GetClassInfo_PlazaWarStatisticUIStrategy** — class self-registration getter (calls FUN_100016b0("PlazaWarStatisticUIStrategy", parent-getter)); registers `PlazaWarStatisticUIStrategy` as a subclass of `CUIStrategy` in the engine RTTI/class-factory system.
- `FUN_102bdfd0` (line 478895) — **RTTI_GetClassInfo_SPhysMaterial** — class self-registration getter (calls FUN_100016b0("SPhysMaterial", parent-getter)); registers `SPhysMaterial` as a subclass of `CNomadDbObjectNamed` in the engine RTTI/class-factory system.
- `FUN_1027f200` (line 437391) — **RTTI_GetClassInfo_SSettings** — class self-registration getter (calls FUN_100016b0("SSettings", parent-getter)); registers `SSettings` as a subclass of `CNomadDbObjectNamed` in the engine RTTI/class-factory system.
- `FUN_1036ff60` (line 599832) — **RTTI_GetClassInfo_SSettings** — class self-registration getter (calls FUN_100016b0("SSettings", parent-getter)); registers `SSettings` as a subclass of `CNomadDbObjectNamed` in the engine RTTI/class-factory system.
- `FUN_107aff70` (line 1244304) — **RTTI_GetClassInfo_SSettings** — class self-registration getter (calls FUN_100016b0("SSettings", parent-getter)); registers `SSettings` as a subclass of `CNomadDbObjectNamed` in the engine RTTI/class-factory system.
- `FUN_105343a0` (line 894344) — **RTTI_GetClassInfo_SSkillFxBase** — class self-registration getter (calls FUN_100016b0("SSkillFxBase", parent-getter)); registers `SSkillFxBase` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_105344d0` (line 894443) — **RTTI_GetClassInfo_SSkillFxBlink** — class self-registration getter (calls FUN_100016b0("SSkillFxBlink", parent-getter)); registers `SSkillFxBlink` as a subclass of `SSkillFxBase` in the engine RTTI/class-factory system.
- `FUN_105344a0` (line 894427) — **RTTI_GetClassInfo_SSkillFxCamo** — class self-registration getter (calls FUN_100016b0("SSkillFxCamo", parent-getter)); registers `SSkillFxCamo` as a subclass of `SSkillFxParticles` in the engine RTTI/class-factory system.
- `FUN_105343e0` (line 894363) — **RTTI_GetClassInfo_SSkillFxDelayed** — class self-registration getter (calls FUN_100016b0("SSkillFxDelayed", parent-getter)); registers `SSkillFxDelayed` as a subclass of `SSkillFxBase` in the engine RTTI/class-factory system.
- `FUN_10534410` (line 894379) — **RTTI_GetClassInfo_SSkillFxObject** — class self-registration getter (calls FUN_100016b0("SSkillFxObject", parent-getter)); registers `SSkillFxObject` as a subclass of `SSkillFxBase` in the engine RTTI/class-factory system.
- `FUN_10534440` (line 894395) — **RTTI_GetClassInfo_SSkillFxParticles** — class self-registration getter (calls FUN_100016b0("SSkillFxParticles", parent-getter)); registers `SSkillFxParticles` as a subclass of `SSkillFxObject` in the engine RTTI/class-factory system.
- `FUN_10534500` (line 894459) — **RTTI_GetClassInfo_SSkillFxPostFx** — class self-registration getter (calls FUN_100016b0("SSkillFxPostFx", parent-getter)); registers `SSkillFxPostFx` as a subclass of `SSkillFxBase` in the engine RTTI/class-factory system.
- `FUN_105345e0` (line 894533) — **RTTI_GetClassInfo_SSkillFxShakeAndRumble** — class self-registration getter (calls FUN_100016b0("SSkillFxShakeAndRumble", parent-getter)); registers `SSkillFxShakeAndRumble` as a subclass of `SSkillFxBase` in the engine RTTI/class-factory system.
- `FUN_10534470` (line 894411) — **RTTI_GetClassInfo_SSkillFxShield** — class self-registration getter (calls FUN_100016b0("SSkillFxShield", parent-getter)); registers `SSkillFxShield` as a subclass of `SSkillFxBase` in the engine RTTI/class-factory system.
- `FUN_10534570` (line 894496) — **RTTI_GetClassInfo_SSkillFxSlowmo** — class self-registration getter (calls FUN_100016b0("SSkillFxSlowmo", parent-getter)); registers `SSkillFxSlowmo` as a subclass of `SSkillFxBase` in the engine RTTI/class-factory system.
- `FUN_10534610` (line 894549) — **RTTI_GetClassInfo_SSkillFxTacticalStrike** — class self-registration getter (calls FUN_100016b0("SSkillFxTacticalStrike", parent-getter)); registers `SSkillFxTacticalStrike` as a subclass of `SSkillFxBase` in the engine RTTI/class-factory system.
- `FUN_1097fc30` (line 1501778) — **RTTI_GetClassInfo_SquidAgent** — class self-registration getter (calls FUN_100016b0("SquidAgent", parent-getter)); registers `SquidAgent` as a subclass of `PlantAgent` in the engine RTTI/class-factory system.
- `FUN_1097f430` (line 1501456) — **RTTI_GetClassInfo_SturmbeestAgent** — class self-registration getter (calls FUN_100016b0("SturmbeestAgent", parent-getter)); registers `SturmbeestAgent` as a subclass of `CBtzAnimalAgent` in the engine RTTI/class-factory system.
- `FUN_108e59f0` (line 1427647) — **RTTI_GetClassInfo_TerritoryManagement** — class self-registration getter (calls FUN_100016b0("TerritoryManagement", parent-getter)); registers `TerritoryManagement` as a subclass of `Action` in the engine RTTI/class-factory system.
- `FUN_104c9ed0` (line 830620) — **RTTI_GetClassInfo_Turret** — class self-registration getter (calls FUN_100016b0("Turret", parent-getter)); registers `Turret` as a subclass of `CPawnBase` in the engine RTTI/class-factory system.
- `FUN_1097f930` (line 1501624) — **RTTI_GetClassInfo_TurretAgent** — class self-registration getter (calls FUN_100016b0("TurretAgent", parent-getter)); registers `TurretAgent` as a subclass of `CPawnBaseAgent` in the engine RTTI/class-factory system.
- `FUN_109eaee0` (line 1565511) — **RTTI_GetClassInfo_TurretSensorySystem** — class self-registration getter (calls FUN_100016b0("TurretSensorySystem", parent-getter)); registers `TurretSensorySystem` as a subclass of `CPawnBaseSensorySystem` in the engine RTTI/class-factory system.
- `FUN_108e7bb0` (line 1429083) — **RTTI_GetClassInfo_VisualAction** — class self-registration getter (calls FUN_100016b0("VisualAction", parent-getter)); registers `VisualAction` as a subclass of `<root>` in the engine RTTI/class-factory system.
- `FUN_108e7c20` (line 1429118) — **RTTI_GetClassInfo_VisualAttack** — class self-registration getter (calls FUN_100016b0("VisualAttack", parent-getter)); registers `VisualAttack` as a subclass of `VisualMove` in the engine RTTI/class-factory system.
- `FUN_108e7bf0` (line 1429102) — **RTTI_GetClassInfo_VisualMove** — class self-registration getter (calls FUN_100016b0("VisualMove", parent-getter)); registers `VisualMove` as a subclass of `VisualAction` in the engine RTTI/class-factory system.

---

## Appendix: Subsystem String-Tag Index (navigational aid, not individually labeled)

Every occurrence of the pattern `(*DAT_1100038c)("...")` across the WHOLE dump — this
function-pointer call takes a string and appears to register/look up a log-category, script-
class-name, or console-command tag (paired with `FUN_10003590(str, id)` immediately after in
most call sites). It is a cheap way to see WHAT concept lives at a given line number without
reading the surrounding function — 1,015 hits total, spanning the full 2.6M-line file. Use this
to jump to interesting areas (e.g. `CDominoManager`, `CMovieSystem`, `FlashUI`,
`gfx_DensityLodScale`, weapon/ability names like `StartChargingShot`) that weren't individually
swept in this pass. Not exhaustive of all string literals in the file — only this specific
call-site pattern.

- line 4869 — `"custom"`
- line 42165 — `"CFCXConsoleService"`
- line 45436 — `"WARNING_NETWORK_CONNECTION_LOST"`
- line 62064 — `"CGRGenericEventWithParam"`
- line 62066 — `"PlayerId"`
- line 62195 — `"GREventPlayerJoin"`
- line 63520 — `"PlazaShallowRemotePlayer"`
- line 98082 — `"ultra"`
- line 133749 — `"ERROR"`
- line 139106 — `"english"`
- line 139182 — `"sound_"`
- line 139216 — `"english"`
- line 157321 — `"farcry2"`
- line 157328 — `"editor"`
- line 157335 — `"fc2editor"`
- line 171103 — `"APPDATA"`
- line 171117 — `"MYDOCS"`
- line 171546 — `"generated"`
- line 181524 — `"shadersobj"`
- line 219378 — `"CNetworkSettingGeneric"`
- line 219411 — `"CNetworkSettingGeneric"`
- line 227212 — `"Simulation"`
- line 227217 — `"Service"`
- line 228412 — `"CNetworkSettingGeneric"`
- line 228414 — `"CryString"`
- line 240099 — `"General"`
- line 240155 — `"Transmission"`
- line 240211 — `"MainSocket"`
- line 240267 — `"NetworkEngine"`
- line 240397 — `"Failed"`
- line 250979 — `"medium"`
- line 250981 — `"medium"`
- line 250983 — `"medium"`
- line 250985 — `"medium"`
- line 250987 — `"medium"`
- line 250989 — `"medium"`
- line 250991 — `"medium"`
- line 250993 — `"medium"`
- line 250995 — `"medium"`
- line 250997 — `"medium"`
- line 250999 — `"medium"`
- line 251002 — `"medium"`
- line 262880 — `"gfx_ShowConfig"`
- line 262913 — `"gfx_ConfigChange"`
- line 262946 — `"gfx_DensityLodScale"`
- line 263438 — `"medium"`
- line 276201 — `"screenshot"`
- line 276230 — `"snapshot"`
- line 276259 — `"snapshot_viewport"`
- line 276288 — `"render_menu_only"`
- line 276317 — `"console_dump_elements"`
- line 276346 — `"clear"`
- line 284618 — `"menu_tips"`
- line 287683 — `"CDependenciesService"`
- line 290327 — `"CGenericEntityEvent"`
- line 290329 — `"CTerminalPTR"`
- line 295937 — `"CSceneObjectComponent"`
- line 295939 — `"CSceneAdaptiveBloom"`
- line 295970 — `"CSceneObjectComponent"`
- line 295972 — `"CScenePostFxDepthOfField"`
- line 296003 — `"CSceneObjectComponent"`
- line 296005 — `"CScenePostFxGlow"`
- line 296036 — `"CSceneObjectComponent"`
- line 296038 — `"CScenePostFxOutline"`
- line 296069 — `"CSceneObjectComponent"`
- line 296071 — `"CScenePostFxSmartBlur"`
- line 296102 — `"CSceneObjectComponent"`
- line 296104 — `"CScenePostFxMotionBlur"`
- line 319071 — `"UNSET"`
- line 320553 — `"Cloth"`
- line 320563 — `"Flesh"`
- line 337267 — `"GREventNextState"`
- line 346417 — `"Subtitles"`
- line 368437 — `"f268c5d31e7171b45bb045010cb4348d"`
- line 368444 — `"tEkuWU7h"`
- line 369927 — `"net_createLanAccount"`
- line 369942 — `"net_createOnlineAccount"`
- line 370399 — `"Default"`
- line 370436 — `"RendezVous"`
- line 370442 — `"Agora"`
- line 372142 — `"CDominoDelayManager"`
- line 372164 — `"GetInstance"`
- line 372486 — `"finished"`
- line 372661 — `"CDominoSoundManager"`
- line 372683 — `"GetInstance"`
- line 373320 — `"CDominoSequenceManager"`
- line 373342 — `"GetInstance"`
- line 375059 — `"get_stats"`
- line 375065 — `"is_playback_done"`
- line 375122 — `"get_stats"`
- line 375137 — `"get_playback_info"`
- line 375152 — `"is_playback_done"`
- line 375184 — `"is_playback_done"`
- line 375199 — `"get_playback_info"`
- line 375214 — `"get_stats"`
- line 377291 — `"SpawnedPhysEntity"`
- line 381200 — `"Realtree_Broken_Branch"`
- line 383068 — `"flashdebug"`
- line 383102 — `"flashopen"`
- line 383136 — `"flashclose"`
- line 383170 — `"flashpause"`
- line 383203 — `"flashreload"`
- line 383237 — `"flashinvoke"`
- line 383271 — `"flashsetlayer"`
- line 383305 — `"flashsetvar"`
- line 383339 — `"flashalign"`
- line 383445 — `"flashdebug"`
- line 383460 — `"flashopen"`
- line 383475 — `"flashclose"`
- line 383490 — `"flashpause"`
- line 383505 — `"flashreload"`
- line 383520 — `"flashinvoke"`
- line 383535 — `"flashsetlayer"`
- line 383550 — `"flashsetvar"`
- line 383565 — `"flashalign"`
- line 383580 — `"flashscale"`
- line 383595 — `"flashbind"`
- line 383610 — `"flashunbind"`
- line 383625 — `"binkopen"`
- line 383640 — `"binkclose"`
- line 383655 — `"binkpause"`
- line 383670 — `"binkshow"`
- line 384272 — `"Event_"`
- line 384352 — `"Event_"`
- line 386508 — `"CWorldLoaderServiceEvent"`
- line 388871 — `"Normal"`
- line 388876 — `"Italic"`
- line 392080 — `"FlashUI"`
- line 392732 — `"english"`
- line 392738 — `"dutch"`
- line 392744 — `"french"`
- line 392750 — `"german"`
- line 394747 — `"AllPeer"`
- line 394939 — `"Single"`
- line 394944 — `"Multi"`
- line 394949 — `"Plaza"`
- line 399319 — `"CGameGenericSetting"`
- line 399352 — `"CGameGenericSetting"`
- line 399354 — `"CryString"`
- line 399385 — `"CGameGenericSetting"`
- line 399418 — `"CGameGenericSetting"`
- line 399569 — `"SetSetting"`
- line 400395 — `"SetSetting"`
- line 411131 — `"Grass"`
- line 423825 — `"scriptcallbacks"`
- line 424221 — `"scriptcallbacks"`
- line 424287 — `"CScriptCallbackSystem"`
- line 424309 — `"GetInstance"`
- line 428295 — `"Decal"`
- line 458900 — `"CDominoManager"`
- line 458922 — `"GetInstance"`
- line 461170 — `"common"`
- line 461221 — `"metagame"`
- line 487295 — `"CDominoWaterLevelManager"`
- line 487317 — `"GetInstance"`
- line 496089 — `"CGenericEntityEvent"`
- line 501398 — `"CDominoConsoleCommandManager"`
- line 501420 — `"GetInstance"`
- line 501881 — `"dominoBoxInstance_"`
- line 505902 — `"minimap"`
- line 505918 — `"icons"`
- line 541401 — `"Subject"`
- line 541438 — `"Opponent"`
- line 572681 — `"CMovieSystem"`
- line 572703 — `"GetInstance"`
- line 617054 — `"HIGH_"`
- line 617130 — `"HIGH_"`
- line 656590 — `"CTerrain"`
- line 656612 — `"GetInstance"`
- line 675850 — `"Water"`
- line 682633 — `"FrameJobState_"`
- line 717293 — `"Generic"`
- line 833279 — `"quitToMainMenu"`
- line 833355 — `"quitToMainMenu"`
- line 833370 — `"slowframe"`
- line 833680 — `"RTSetDeltaTime"`
- line 833712 — `"RTSetWindForce"`
- line 833744 — `"RTGenesis"`
- line 833776 — `"RTRegen"`
- line 833805 — `"RTDefoliant"`
- line 833837 — `"SetMaxFrameRate"`
- line 833869 — `"SetFPCameraOffsetX"`
- line 833901 — `"SetFPCameraOffsetY"`
- line 833933 — `"SetFPCameraOffsetZ"`
- line 834276 — `"_deploadnewparticles"`
- line 834836 — `"Stats_preset"`
- line 834869 — `"load_level"`
- line 834899 — `"Stats"`
- line 834928 — `"EndOfGame"`
- line 834957 — `"InGameCredits"`
- line 834986 — `"PopUpObjective"`
- line 835016 — `"draw_method"`
- line 835045 — `"activate_log"`
- line 835074 — `"deactivate_log"`
- line 836048 — `"game_status"`
- line 836640 — `"ubidays"`
- line 837230 — `"medium"`
- line 837244 — `"ultrahigh"`
- line 848078 — `"Menu_L"`
- line 848117 — `"z_lobby_01"`
- line 848119 — `"z_lobby_01_l"`
- line 852123 — `"Menus_Panels_Completion_List_Exploration"`
- line 856549 — `"CFact"`
- line 856551 — `"CEntityHandle"`
- line 859814 — `"CFact"`
- line 859816 — `"EntityId"`
- line 863220 — `"DominoSocialRegionAlreadyIdle"`
- line 863277 — `"DominoSocialRegionAlreadyCombat"`
- line 863334 — `"DominoSocialRegionSwitchedToIdle"`
- line 863391 — `"DominoSocialRegionSwitchedToCombat"`
- line 863776 — `"DominoWagerFailure"`
- line 863833 — `"DominoWagerSuccess"`
- line 863890 — `"DominoWagerCombatStarted"`
- line 864907 — `"CFCXRegionManager"`
- line 864929 — `"GetInstance"`
- line 876939 — `"_lvl_"`
- line 877028 — `"invalid"`
- line 879864 — `"Trigger_Ability_Effect"`
- line 879875 — `"Remove_Sprint_Event"`
- line 882622 — `"lowhealth"`
- line 882648 — `"DeathRecoveryFX"`
- line 882655 — `"lowhealth"`
- line 911484 — `"CFact"`
- line 911486 — `"ndVec3"`
- line 911517 — `"CGOStateContext"`
- line 911519 — `"CGameObject"`
- line 934785 — `"splash_impulse"`
- line 934796 — `"splash_impulse_L"`
- line 934807 — `"splash_impulse_R"`
- line 935226 — `"CFact"`
- line 935228 — `"float"`
- line 938187 — `"StartChargingShot"`
- line 938198 — `"ResetChargedShot"`
- line 938209 — `"cancel_charge"`
- line 938220 — `"StopShooting"`
- line 938231 — `"WantFinisher"`
- line 938242 — `"FinalFinisher"`
- line 938253 — `"ResetWeaponBonus"`
- line 940843 — `"CGenericEntityEvent"`
- line 940845 — `"CPawn"`
- line 941244 — `"detonate"`
- line 941468 — `"launchprojectile"`
- line 941720 — `"launchprojectile"`
- line 944241 — `"launchprojectile"`
- line 952416 — `"CFact"`
- line 952724 — `"begin_take_flag"`
- line 952735 — `"end_take_flag"`
- line 952746 — `"take_flag_cleanup"`
- line 953577 — `"Undefined"`
- line 953579 — `"Undefined"`
- line 971812 — `"relax"`
- line 971818 — `"tension"`
- line 971824 — `"fight"`
- line 971830 — `"nightmare"`
- line 973288 — `"relax"`
- line 973294 — `"tension"`
- line 973300 — `"fight"`
- line 973306 — `"nightmare"`
- line 973447 — `"CMusicManager"`
- line 973469 — `"GetInstance"`
- line 976007 — `"heal_counter"`
- line 985820 — `"FCXEditor"`
- line 992748 — `"FCXEditor"`
- line 993232 — `"CGRGenericEventWithParam"`
- line 993234 — `"EntityId"`
- line 995456 — `"SpawnedPickupEntity"`
- line 998781 — `"GrenadeExplode"`
- line 998792 — `"detonate"`
- line 998803 — `"FallToDeath"`
- line 1000765 — `"FinalFinisher"`
- line 1003228 — `"CFact"`
- line 1003230 — `"ndAngle3F"`
- line 1004664 — `"HMRStartShooting"`
- line 1004675 — `"HMRStopShooting"`
- line 1004686 — `"HMRCallForHelp"`
- line 1004697 — `"finish_carry_drop"`
- line 1004708 — `"hmr_finish_heal"`
- line 1004719 — `"reset_fall_counter"`
- line 1004730 — `"check_fall"`
- line 1004741 — `"shot_fired"`
- line 1004752 — `"HMRAttachVictim"`
- line 1004763 — `"HMRDetachVictim"`
- line 1006019 — `"grab_object"`
- line 1011150 — `"call_picked"`
- line 1011293 — `"pickCall"`
- line 1011304 — `"hangupCall"`
- line 1011315 — `"startVoice"`
- line 1011326 — `"checkEquip"`
- line 1016838 — `"flip_side"`
- line 1016849 — `"equip_monocular"`
- line 1016860 — `"unequip_monocular"`
- line 1016871 — `"restore_fov"`
- line 1016882 — `"new_owner"`
- line 1031835 — `"TAGPOINT_NOACTION"`
- line 1036928 — `"A1SM02"`
- line 1037453 — `"is_map_loaded"`
- line 1037485 — `"is_map_loaded"`
- line 1038416 — `"begin_take_flag"`
- line 1038492 — `"end_take_flag"`
- line 1038568 — `"take_flag_cleanup"`
- line 1043570 — `"default"`
- line 1043711 — `"summon_"`
- line 1049338 — `"Event_SkillUsed"`
- line 1051335 — `"MissionComplete"`
- line 1051651 — `"StepComplete"`
- line 1051854 — `"StepComplete"`
- line 1051864 — `"MissionComplete"`
- line 1052471 — `"MissionFailed"`
- line 1052763 — `"MissionEvent"`
- line 1056947 — `"_L_WIN32"`
- line 1057255 — `"_FemalePlayer"`
- line 1057639 — `"_Desc"`
- line 1057666 — `"_Desc02"`
- line 1057693 — `"_Desc03"`
- line 1057720 — `"_Desc01"`
- line 1067378 — `"default"`
- line 1070626 — `"CWeaponStims"`
- line 1070628 — `"CPhysBulletHitStim"`
- line 1073748 — `"_lvl_"`
- line 1075636 — `"_lvl_"`
- line 1075755 — `"_lvl_"`
- line 1077909 — `"tipsloadingscreen"`
- line 1080112 — `"CGRGenericEventWithParam"`
- line 1080157 — `"vehicle_weapon"`
- line 1081910 — `"cheat_set_pillar"`
- line 1082283 — `"cheat_set_pillar"`
- line 1085337 — `"CFact"`
- line 1093125 — `"ASSW1"`
- line 1093131 — `"ASSW2"`
- line 1093137 — `"ASSBUDDY"`
- line 1094273 — `"SAVE_BUDDY"`
- line 1094287 — `"RESCUE_REUBEN"`
- line 1094290 — `"HOUSE_CLEANING1_BASE"`
- line 1094298 — `"HOUSE_CLEANING2_BASE"`
- line 1109739 — `"cheat_add_playerweapon"`
- line 1110060 — `"cheat_add_playerweapon"`
- line 1112948 — `"A3SM15"`
- line 1119419 — `"PrepareUnloadWorld"`
- line 1119874 — `"epilepsy_calibration"`
- line 1119939 — `"intro_lightstorm"`
- line 1119971 — `"intro_fox"`
- line 1120650 — `"loadworld"`
- line 1121058 — `"unloadworld"`
- line 1121324 — `"NetEngineEvent"`
- line 1128823 — `"Warren_Clyde"`
- line 1128880 — `"GREventGameOver"`
- line 1133747 — `"Normal"`
- line 1135560 — `"net_GetCurrentMapName"`
- line 1135575 — `"net_GetCurrentGameMode"`
- line 1135590 — `"net_GetHostAddress"`
- line 1135605 — `"net_GetHostName"`
- line 1135620 — `"net_GetCurrentSessionMaxPlayer"`
- line 1135635 — `"net_GetPlayerList"`
- line 1135650 — `"net_GetPlayerListByTeam"`
- line 1135665 — `"net_GetGameScoreStats"`
- line 1135681 — `"net_EndMatch"`
- line 1135696 — `"net_ExtendMatch"`
- line 1135711 — `"net_KickClient"`
- line 1135726 — `"net_KickBanClient"`
- line 1136429 — `"net_endmatch"`
- line 1136438 — `"net_restartmatch"`
- line 1136441 — `"net_extendmatch"`
- line 1136552 — `"net_GetCurrentMapName"`
- line 1136585 — `"net_GetCurrentGameModeName"`
- line 1136618 — `"net_GetHostAddress"`
- line 1136651 — `"net_GetHostName"`
- line 1136684 — `"net_GetCurrentSessionMaxPlayer"`
- line 1136717 — `"net_GetPlayerList"`
- line 1136750 — `"net_GetPlayerListByTeam"`
- line 1136783 — `"net_GetGameScoreStats"`
- line 1136817 — `"net_EndMatch"`
- line 1139976 — `"CFCXGameSetting"`
- line 1140521 — `"default"`
- line 1140536 — `"ranked"`
- line 1140712 — `"default"`
- line 1140727 — `"ranked"`
- line 1140939 — `"ranked"`
- line 1141494 — `"CFCXOnlineGenericConversionHelper"`
- line 1141527 — `"CFCXOnlineGenericConversionHelper"`
- line 1141560 — `"CFCXOnlineGenericConversionHelper"`
- line 1141646 — `"MatchInfo"`
- line 1142429 — `"statBonus"`
- line 1147719 — `"GREventEndMatch"`
- line 1153973 — `"GREventAccountSignInChanged"`
- line 1154140 — `"GREventNextState"`
- line 1154603 — `"CGameDataValue"`
- line 1154605 — `"CStringID"`
- line 1157229 — `"int32"`
- line 1157242 — `"uint32"`
- line 1157250 — `"int64"`
- line 1157258 — `"uint64"`
- line 1164071 — `"GREventAccountLoggedOutConfirmed"`
- line 1164411 — `"GREventPlayerJoin"`
- line 1164846 — `"GREventPlayerJoin"`
- line 1190434 — `"CWeaponStims"`
- line 1190436 — `"CEntityEventStims"`
- line 1194463 — `"CANCEL"`
- line 1194470 — `"Generic"`
- line 1197168 — `"CGRGenericEventWithParam"`
- line 1197170 — `"CTerminalPTR"`
- line 1197886 — `"CGameMessageBoxSpinner"`
- line 1198615 — `"ePT_Avatar"`
- line 1198629 — `"eGENDER_Female"`
- line 1199629 — `"GREventPlayerJoinGame"`
- line 1199646 — `"GREventPlayerJoin"`
- line 1201867 — `"GREventPlayerJoin"`
- line 1201933 — `"GREventPlayerJoin"`
- line 1213619 — `"driving"`
- line 1213626 — `"driving_skillring"`
- line 1213633 — `"passenger_skillring"`
- line 1218159 — `"CVehicle"`
- line 1218181 — `"GetCurrentVehicle"`
- line 1220191 — `"GREventPlayerJoinGame"`
- line 1220512 — `"default"`
- line 1229418 — `"CDynamicEnvironmentManager"`
- line 1229440 — `"GetInstance"`
- line 1231670 — `"CGameMissionMgr"`
- line 1231692 — `"GetInstance"`
- line 1233247 — `"GREventAccountLoggedOut"`
- line 1238276 — `"launchprojectile"`
- line 1238287 — `"exploded"`
- line 1242004 — `"Difficulty"`
- line 1242076 — `"Context"`
- line 1242202 — `"LvlType"`
- line 1242209 — `"Campaign"`
- line 1242270 — `"LvlSequence"`
- line 1242338 — `"LvlDifficulty"`
- line 1242406 — `"IsLoad"`
- line 1242474 — `"IsComplete"`
- line 1242542 — `"AwdName"`
- line 1242549 — `"Placeholder"`
- line 1242612 — `"MpType"`
- line 1242623 — `"Adversarial"`
- line 1242627 — `"TeamAdversarial"`
- line 1242698 — `"Ranked"`
- line 1242795 — `"MpMode"`
- line 1242868 — `"Class"`
- line 1242893 — `"Corpo"`
- line 1242983 — `"WonLost"`
- line 1243082 — `"IsDedicated"`
- line 1243160 — `"Language"`
- line 1243229 — `"PlayMode"`
- line 1243302 — `"PROGRESS"`
- line 1243491 — `"SessionId"`
- line 1250146 — `"CGameDataValue"`
- line 1250148 — `"CNoCaseStringID"`
- line 1250179 — `"CGameDataValue"`
- line 1250212 — `"CGameDataValue"`
- line 1250214 — `"CMapId"`
- line 1250245 — `"CGameDataValue"`
- line 1250247 — `"EntityId"`
- line 1250278 — `"CGameDataValue"`
- line 1250280 — `"CryString"`
- line 1251455 — `"Invalid"`
- line 1251469 — `"Invalid"`
- line 1251533 — `"Invalid"`
- line 1251548 — `"Invalid"`
- line 1251683 — `"WonLost"`
- line 1253088 — `"Invalid"`
- line 1259859 — `"using_mounted_weapon_skillring"`
- line 1273498 — `"HIGH_"`
- line 1279117 — `"new_owner"`
- line 1281193 — `"CGenericEntityEvent"`
- line 1281195 — `"CryString"`
- line 1281582 — `"detonate"`
- line 1282038 — `"start_switch_ied_mode"`
- line 1282049 — `"switch_ied_mode"`
- line 1282082 — `"detonate"`
- line 1282093 — `"checkMode"`
- line 1283321 — `"mortar"`
- line 1286042 — `"grab_object"`
- line 1286387 — `"DominoCallbackPickupPicked"`
- line 1298743 — `"stop_shoot"`
- line 1299314 — `"cannot_use"`
- line 1315313 — `"attach_projectile"`
- line 1315324 — `"detach_projectile"`
- line 1315335 — `"explode_projectiles"`
- line 1315346 — `"cannot_use"`
- line 1319403 — `"shootbullet"`
- line 1319416 — `"cannot_use"`
- line 1319433 — `"shine_lens"`
- line 1319447 — `"shootmainhand"`
- line 1319460 — `"shootoffhand"`
- line 1319730 — `"start_shoot"`
- line 1324576 — `"player"`
- line 1325412 — `"GREventNextState"`
- line 1334132 — `"item_drawn"`
- line 1338352 — `"MultiMenu"`
- line 1338401 — `"MultiMenu"`
- line 1338834 — `"MAPINFO_UBISOFT_MONTREAL"`
- line 1338841 — `"MultiMenu"`
- line 1346155 — `"GREventPlayerJoinGame"`
- line 1346938 — `"GREventNextState"`
- line 1347243 — `"GREventPlayerJoinGame"`
- line 1347314 — `"GREventPlayerLeft"`
- line 1348404 — `"GREventNextState"`
- line 1348459 — `"GREventNextState"`
- line 1349556 — `"GREventNextState"`
- line 1349749 — `"GREventPlayerJoinGame"`
- line 1349804 — `"GREventPlayerLeft"`
- line 1353194 — `"CWeaponStims"`
- line 1353196 — `"CPhysExplosionStim"`
- line 1353227 — `"CWeaponStims"`
- line 1353229 — `"CBTZDamageStim"`
- line 1355328 — `"CGameMessageBox"`
- line 1355360 — `"WarningDialogue_Hide"`
- line 1355528 — `"WarningDialogue_Set"`
- line 1355652 — `"CGameMessageBoxEvent"`
- line 1364917 — `"CFact"`
- line 1364919 — `"ndQuat"`
- line 1369336 — `"CFact"`
- line 1369677 — `"SpawnedPickupEntity"`
- line 1376236 — `"stop_sliding"`
- line 1378801 — `"reset_vertical_look"`
- line 1379168 — `"new_owner"`
- line 1383026 — `"mounted_weapon_spawned"`
- line 1384643 — `"exploded"`
- line 1384654 — `"launchprojectile"`
- line 1389970 — `"Invalid"`
- line 1389974 — `"Offline"`
- line 1389978 — `"Online"`
- line 1389986 — `"Split"`
- line 1389990 — `"Single"`
- line 1390563 — `"CEntitySystemService"`
- line 1390576 — `"CDlcService"`
- line 1390589 — `"CConsoleService"`
- line 1396948 — `"detonate"`
- line 1397231 — `"activate"`
- line 1401650 — `"CFact"`
- line 1402552 — `"smartterrain_moveStateID"`
- line 1427606 — `"Metagame_Actions_Navi_MoveTroops"`
- line 1427608 — `"Metagame_Actions_Navi_MoveTroops"`
- line 1427628 — `"Metagame_Actions_RDA_MoveTroops"`
- line 1427630 — `"Metagame_Actions_RDA_MoveTroops"`
- line 1433001 — `"Metagame_Actions_Navi_BuildFactory"`
- line 1433003 — `"Metagame_Actions_Navi_BuildFactory"`
- line 1433023 — `"Metagame_Actions_RDA_BuildFactory"`
- line 1433025 — `"Metagame_Actions_RDA_BuildFactory"`
- line 1433047 — `"Metagame_Actions_Navi_Def_Soldier"`
- line 1433049 — `"Metagame_Actions_Navi_Def_Soldier"`
- line 1433076 — `"Metagame_Actions_Navi_Def_Tank"`
- line 1433078 — `"Metagame_Actions_Navi_Def_Tank"`
- line 1433105 — `"Metagame_Actions_Navi_Def_Plane"`
- line 1433107 — `"Metagame_Actions_Navi_Def_Plane"`
- line 1433134 — `"Metagame_Actions_RDA_Def_Soldier"`
- line 1433136 — `"Metagame_Actions_RDA_Def_Soldier"`
- line 1433163 — `"Metagame_Actions_RDA_Def_Tank"`
- line 1433165 — `"Metagame_Actions_RDA_Def_Tank"`
- line 1433192 — `"Metagame_Actions_RDA_Def_Plane"`
- line 1433194 — `"Metagame_Actions_RDA_Def_Plane"`
- line 1433335 — `"Metagame_Actions_Navi_AddTroops"`
- line 1433337 — `"Metagame_Actions_Navi_AddTroops"`
- line 1433357 — `"Metagame_Actions_RDA_AddTroops"`
- line 1433359 — `"Metagame_Actions_RDA_AddTroops"`
- line 1433398 — `"Metagame_Actions_Navi_AirStrike"`
- line 1433400 — `"Metagame_Actions_Navi_AirStrike"`
- line 1433434 — `"Metagame_Actions_RDA_AirStrike"`
- line 1433436 — `"Metagame_Actions_RDA_AirStrike"`
- line 1437035 — `"cinematic"`
- line 1442824 — `"invalid"`
- line 1442846 — `"Loot_Gear_Item"`
- line 1444227 — `"TITLE_GAME"`
- line 1444229 — `"TITLE_DISPLAY"`
- line 1444231 — `"TITLE_CONTROLS"`
- line 1444233 — `"TITLE_AUDIO"`
- line 1444834 — `"BACK_TEXT"`
- line 1444841 — `"OptionMenu"`
- line 1444857 — `"TITLE_GAME"`
- line 1444864 — `"OptionMenu"`
- line 1445096 — `"TITLE_LOOK"`
- line 1445103 — `"OptionMenu"`
- line 1445159 — `"GAME_INVERTYAXIS"`
- line 1445166 — `"OptionMenu"`
- line 1445234 — `"GAME_ROTATERADAR"`
- line 1445241 — `"OptionMenu"`
- line 1445309 — `"GAME_LOOKSENSITIVITY"`
- line 1445316 — `"OptionMenu"`
- line 1445381 — `"GAME_USEAUTOTARGETING_TOOLTIP"`
- line 1445388 — `"OptionMenu"`
- line 1445398 — `"GAME_USEAUTOTARGETING"`
- line 1445405 — `"OptionMenu"`
- line 1445846 — `"medium"`
- line 1446400 — `"STEREO_TVDIAGONAL_METRIC"`
- line 1446407 — `"OptionMenu"`
- line 1446439 — `"STEREO_TVDISTANCE_METRIC"`
- line 1446478 — `"STEREO_TVDIAGONAL"`
- line 1446485 — `"OptionMenu"`
- line 1446517 — `"STEREO_TVDISTANCE"`
- line 1446526 — `"OptionMenu"`
- line 1446617 — `"DISPLAY_NEEDRELOAD"`
- line 1446624 — `"OptionMenu"`
- line 1446655 — `"BACK_TEXT"`
- line 1446662 — `"OptionMenu"`
- line 1446710 — `"TITLE_DISPLAY"`
- line 1446717 — `"OptionMenu"`
- line 1447080 — `"DISPLAY_CONFIRMSETTINGS"`
- line 1447087 — `"OptionMenu"`
- line 1447439 — `"DISPLAY_NONE"`
- line 1447443 — `"OptionMenu"`
- line 1447957 — `"SetViewportInfos"`
- line 1449268 — `"UNSET"`
- line 1449275 — `"Input"`
- line 1449410 — `"BACK_TEXT"`
- line 1449417 — `"OptionMenu"`
- line 1449433 — `"TITLE_CONTROLS"`
- line 1449440 — `"OptionMenu"`
- line 1449593 — `"OptionMenu"`
- line 1449680 — `"OptionMenu"`
- line 1450117 — `"BACK_TEXT"`
- line 1450124 — `"OptionMenu"`
- line 1450140 — `"TITLE_AUDIO"`
- line 1450147 — `"OptionMenu"`
- line 1450258 — `"TITLE_VOLUME"`
- line 1450265 — `"OptionMenu"`
- line 1450318 — `"AUDIO_MUSICVOLUME"`
- line 1450325 — `"OptionMenu"`
- line 1450393 — `"AUDIO_SOUNDVOLUME"`
- line 1450400 — `"OptionMenu"`
- line 1450459 — `"AUDIO_VOICEVOLUME"`
- line 1450466 — `"OptionMenu"`
- line 1450553 — `"setMute"`
- line 1455730 — `"showhud"`
- line 1459362 — `"CharacterPortrait_defaultNavi"`
- line 1462724 — `"setTimer"`
- line 1463835 — `"forcevsync"`
- line 1463864 — `"LocDebug"`
- line 1463893 — `"showhud"`
- line 1463922 — `"StartFlashClip"`
- line 1463951 — `"blurgame"`
- line 1463980 — `"blendframes"`
- line 1464009 — `"fadetoblack"`
- line 1464166 — `"Suicide"`
- line 1465013 — `"InGame_SetMode"`
- line 1467792 — `"CAvatarFriendsNotificationServiceNative"`
- line 1468427 — `"CurrentSelection"`
- line 1468456 — `"ActivateCommand"`
- line 1468485 — `"Close"`
- line 1468830 — `"Close"`
- line 1468939 — `"setPrivate"`
- line 1470113 — `"Close"`
- line 1470375 — `"SCOREBOARD_CTF"`
- line 1470382 — `"MultiMenu"`
- line 1470436 — `"SCOREBOARD_TDM"`
- line 1470443 — `"MultiMenu"`
- line 1470512 — `"SCOREBOARD_CNH"`
- line 1470519 — `"MultiMenu"`
- line 1470573 — `"SCOREBOARD_KTH"`
- line 1470580 — `"MultiMenu"`
- line 1470635 — `"SCOREBOARD_FINALBATTLE"`
- line 1470642 — `"MultiMenu"`
- line 1470697 — `"SCOREBOARD_HORDE"`
- line 1470704 — `"MultiMenu"`
- line 1470962 — `"ActivateCommand"`
- line 1471032 — `"ActivateCommand"`
- line 1471737 — `"updateDisplay"`
- line 1472757 — `"Multi_MainProgress"`
- line 1473158 — `"Multi_ModeCF_Navi_Points"`
- line 1473183 — `"Multi_ModeCF_Corp_Points"`
- line 1473224 — `"Multi_Update"`
- line 1473522 — `"Multi_UpdateMode"`
- line 1477037 — `"LOGIN_CONFIRM_LOGOUT"`
- line 1477043 — `"MultiMenu"`
- line 1477121 — `"Generic"`
- line 1477149 — `"CANCEL"`
- line 1477155 — `"Generic"`
- line 1477292 — `"_PreGameMenu"`
- line 1477561 — `"Avatar_Male_02"`
- line 1477563 — `"Avatar_Female_02"`
- line 1477565 — `"Avatar_Male_03"`
- line 1477567 — `"Avatar_Female_03"`
- line 1477569 — `"Avatar_Male_01"`
- line 1477571 — `"Avatar_Female_01"`
- line 1477573 — `"Avatar_Male_00"`
- line 1477575 — `"Avatar_Female_02"`
- line 1477577 — `"Avatar_Male_00"`
- line 1477579 — `"Avatar_Female_01"`
- line 1477581 — `"Avatar_Male_02"`
- line 1477583 — `"Avatar_Female_01"`
- line 1477585 — `"Avatar_Male_01"`
- line 1477587 — `"Avatar_Female_02"`
- line 1477589 — `"Avatar_Male_02"`
- line 1477591 — `"Avatar_Female_03"`
- line 1477593 — `"Avatar_Male_03"`
- line 1477595 — `"Avatar_Female_00"`
- line 1477597 — `"Avatar_Male_00"`
- line 1477599 — `"Avatar_Female_00"`
- line 1477601 — `"Avatar_Male_01"`
- line 1477603 — `"Avatar_Female_03"`
- line 1477605 — `"Avatar_Male_03"`
- line 1477607 — `"Avatar_Female_00"`
- line 1477987 — `"LOGIN_LOGOUT"`
- line 1477993 — `"MultiMenu"`
- line 1479963 — `"_GearMenu"`
- line 1480100 — `"_MetapodMenu"`
- line 1480427 — `"_StartMenuMulti"`
- line 1480567 — `"_StartMenu"`
- line 1481427 — `"Close"`
- line 1481504 — `"setApply"`
- line 1488194 — `"TITLE_GAME"`
- line 1488201 — `"OptionMenu"`
- line 1488226 — `"TITLE_DISPLAY"`
- line 1488233 — `"OptionMenu"`
- line 1488258 — `"TITLE_CONTROLS"`
- line 1488265 — `"OptionMenu"`
- line 1488290 — `"TITLE_AUDIO"`
- line 1488297 — `"OptionMenu"`
- line 1488480 — `"OptionsPanel"`
- line 1493014 — `"Menus_Panels_Pandorapedia_Completion"`
- line 1493021 — `"FlashUI"`
- line 1495824 — `"Territory_Name"`
- line 1495908 — `"Planet_Navi_Control"`
- line 1496142 — `"Tutorial_setHighlight"`
- line 1497935 — `"Reward_Territory_Show"`
- line 1498165 — `"setViewMode"`
- line 1498470 — `"CurrentMenu"`
- line 1498510 — `"Metagame_ActivateCommand"`
- line 1498543 — `"Metagame_ActivateCommand"`
- line 1498617 — `"setEPBar"`
- line 1498692 — `"setPlanetViewMode"`
- line 1498761 — `"AvailableEP"`
- line 1508361 — `"CFact"`
- line 1508363 — `"ESpecialStrategy"`
- line 1508394 — `"CFact"`
- line 1508396 — `"AIObjectId"`
- line 1508427 — `"CFact"`
- line 1508429 — `"CSmartPosition"`
- line 1508460 — `"CFact"`
- line 1508462 — `"EFireRange"`
- line 1508493 — `"CFact"`
- line 1508495 — `"EFireStrategy"`
- line 1508526 — `"CFact"`
- line 1508528 — `"ELookStrategy"`
- line 1508559 — `"CFact"`
- line 1508561 — `"EEmotionStrategy"`
- line 1508592 — `"CFact"`
- line 1508594 — `"EAimStrategy"`
- line 1508625 — `"CFact"`
- line 1508627 — `"ESpeed"`
- line 1508658 — `"CFact"`
- line 1508660 — `"EPatrolType"`
- line 1508691 — `"CFact"`
- line 1508693 — `"ENeedType"`
- line 1508724 — `"CFact"`
- line 1508726 — `"ESocialBehaviorType"`
- line 1508757 — `"CFact"`
- line 1508759 — `"EOccupation"`
- line 1508790 — `"CFact"`
- line 1508792 — `"EIdleBehavior"`
- line 1525102 — `"SuccessfulConvoy"`
- line 1525134 — `"FailedConvoy"`
- line 1535876 — `"A1SM01"`
- line 1535879 — `"A2LM09"`
- line 1535882 — `"A3SM12"`
- line 1535894 — `"A1SM01"`
- line 1535899 — `"A2LM09"`
- line 1535904 — `"A3SM12"`
- line 1535907 — `"A3SM13"`
- line 1535915 — `"A3SM15"`
- line 1543141 — `"CFact"`
- line 1543143 — `"CNoCaseStringID"`
- line 1543174 — `"CFact"`
- line 1543176 — `"CStringID"`
- line 1572079 — `"Sprint"`
- line 1572909 — `"Stopped"`
- line 1572945 — `"Ended"`
- line 1573176 — `"PathFind"`
- line 1575007 — `"Roads"`
- line 1575020 — `"Rivers"`
- line 1575211 — `"Roads"`
- line 1575224 — `"Rivers"`
- line 1575400 — `"Roads"`
- line 1575412 — `"Rivers"`
- line 1576717 — `"Stopped"`
- line 1577106 — `"FindCover"`
- line 1577250 — `"BabyStep"`
- line 1577345 — `"Sprint"`
- line 1578526 — `"DefenceReversal_MikePlace"`
- line 1578545 — `"DefenceReversal_Church"`
- line 1578564 — `"Assassination_Initmidation"`
- line 1578583 — `"BuddyBetrayal"`
- line 1578602 — `"BargeAssault"`
- line 1578621 — `"TownEscape"`
- line 1578640 — `"DentalPlan"`
- line 1578659 — `"JacksBuddy"`
- line 1580261 — `"Grenade"`
- line 1580280 — `"GrenadeAndBuilding"`
- line 1580299 — `"ChasingMerc"`
- line 1580318 — `"VehicleReachSniper"`
- line 1580337 — `"MountedWeapon"`
- line 1580356 — `"ShootFlare"`
- line 1580375 — `"ShootInterestingObject"`
- line 1580394 — `"RescueVictim"`
- line 1580413 — `"RangeWeapon"`
- line 1580432 — `"VehicleChaseLevel2"`
- line 1580451 — `"VehicleChaseLevel3"`
- line 1580470 — `"LongRangeVehicle"`
- line 1580552 — `"Social"`
- line 1580592 — `"Alert"`
- line 1580611 — `"Active"`
- line 1580630 — `"Passive"`
- line 1580649 — `"Defensive"`
- line 1580687 — `"Briefing"`
- line 1580914 — `"Invalid"`
- line 1580935 — `"SubSilentSniperKiller"`
- line 1580954 — `"SubSniperSneeker"`
- line 1580973 — `"SubMortarSeeker"`
- line 1581085 — `"Invalid"`
- line 1581104 — `"SmartTerrain"`
- line 1581123 — `"LayeredSmartTerrain"`
- line 1581441 — `"Invalid"`
- line 1581455 — `"AddAttachement"`
- line 1581468 — `"RemoveAttachement"`
- line 1582643 — `"CVariantTypedParameter"`
- line 1582676 — `"CVariantTypedParameter"`
- line 1582709 — `"CVariantTypedParameter"`
- line 1582711 — `"CStringID"`
- line 1583806 — `"AllSeen"`
- line 1583819 — `"KnowledgeBase"`
- line 1585367 — `"StopUse"`
- line 1585377 — `"Reserve"`
- line 1585387 — `"Unreserve"`
- line 1586991 — `"StartShooting"`
- line 1587012 — `"StopShooting"`
- line 1587031 — `"SitAtCover"`
- line 1587050 — `"CallForHelp"`
- line 1587688 — `"Normal"`
- line 1587709 — `"BarricadedEntrance"`
- line 1587728 — `"BuildingExteriorObject"`
- line 1587747 — `"BuildingInteriorObject"`
- line 1587766 — `"BargeObject"`
- line 1588098 — `"CFact"`
- line 1588347 — `"FromDiscretionaryToFreeFire"`
- line 1588368 — `"FromFreeFireToDiscretionary"`
- line 1588465 — `"Primary"`
- line 1588485 — `"Secondary"`
- line 1588806 — `"MercTargetLost"`
- line 1588827 — `"MercTargetSeen"`
- line 1588846 — `"ProjectileSeen"`
- line 1588865 — `"DestinationReached"`
- line 1588884 — `"UnreachableDestination"`
- line 1588903 — `"DriveRenewReservation"`
- line 1588922 — `"DriveEvacuationRequest"`
- line 1588941 — `"VehicleSTPRequest"`
- line 1588960 — `"ReadyForSTP"`
- line 1588979 — `"DoneWithSTP"`
- line 1588998 — `"DriveDoneWithStrategy"`
- line 1589017 — `"MercSuspiciousBuilding"`
- line 1589036 — `"MercLaunchingProjectile"`
- line 1589055 — `"DriveGunnerScanPos"`
- line 1589074 — `"ReinforcementConfirmation"`
- line 1589093 — `"ReinforcementConfirmationFailure"`
- line 1589112 — `"DriveReadyForStrategy"`
- line 1589792 — `"Unchanged"`
- line 1589856 — `"Neutral"`
- line 1589877 — `"RunCoverUnderFire"`
- line 1589896 — `"SprintCoverUnderFire"`
- line 1589915 — `"RunCoverNotUnderFire"`
- line 1589934 — `"SprintCoverNotUnderFire"`
- line 1589953 — `"CloseTarget"`
- line 1596376 — `"Molotov"`
- line 1597345 — `"AimAlways_LookAlways"`
- line 1597366 — `"AimNever_LookNever"`
- line 1597385 — `"AimSometimes_LookSometimes"`
- line 1597404 — `"Machete"`
- line 1597423 — `"SprayAimOnLookOn"`
- line 1597442 — `"Special"`
- line 1597461 — `"CombatFireNotMoving"`
- line 1597480 — `"CombatFireMoving"`
- line 1597499 — `"FireWhenVisible"`
- line 1597518 — `"AimInFrontNoShoot"`
- line 1597537 — `"NoShooting"`
- line 1597556 — `"BlindFire"`
- line 1597788 — `"SearchLookLeftRight"`
- line 1597811 — `"LookLeftRightFast"`
- line 1597834 — `"LookLeftRightSlow"`
- line 1597857 — `"QuickLookAtPos"`
- line 1597880 — `"LookTarget"`
- line 1597903 — `"LookTargetQuickLookLeftRight"`
- line 1597926 — `"LookSmartPos"`
- line 1597949 — `"LookPath"`
- line 1597975 — `"LookPatrol"`
- line 1597998 — `"LookGuard"`
- line 1598021 — `"LookIdle"`
- line 1598044 — `"LookAroundTarget"`
- line 1598067 — `"Invalid"`
- line 1598090 — `"LookAroundSmartPos"`
- line 1598113 — `"LookAtVehicle"`
- line 1598136 — `"LookRiskPoints"`
- line 1598159 — `"LookSocial"`
- line 1598306 — `"Invalid"`
- line 1598325 — `"Neutral"`
- line 1598344 — `"Worried"`
- line 1598363 — `"Annoyed"`
- line 1598382 — `"Scared"`
- line 1598401 — `"Angry"`
- line 1598420 — `"AimedAt"`
- line 1598439 — `"DelayedNeutral"`
- line 1598605 — `"AimTarget"`
- line 1598631 — `"AimSmartPos"`
- line 1598654 — `"AimAtPath"`
- line 1598677 — `"AimAtPredictedPos"`
- line 1598700 — `"AimAtRiskPoints"`
- line 1598723 — `"AimTargetSensorySystem"`
- line 1598746 — `"Invalid"`
- line 1598769 — `"AimSmartTarget"`
- line 1598792 — `"AimAround"`
- line 1598912 — `"LaunchGrenadeInBuilding"`
- line 1600741 — `"ValidatePosition"`
- line 1600755 — `"TeleportPawn"`
- line 1601583 — `"Defensive"`
- line 1601594 — `"Offensive"`
- line 1601605 — `"Assault"`
- line 1601618 — `"Suppress"`
- line 1601629 — `"FollowLeader"`
- line 1602842 — `"Engage"`
- line 1602871 — `"Disengage"`
- line 1604733 — `"Random"`
- line 1605701 — `"PushedToCombat"`
- line 1606286 — `"Reserve"`
- line 1606308 — `"Release"`
- line 1606524 — `"ExecuteSTP"`
- line 1606550 — `"SearchThreat"`
- line 1606576 — `"SearchTarget"`
- line 1606602 — `"CombatTarget"`
- line 1606628 — `"Reinforce"`
- line 1606918 — `"CFact"`
- line 1611999 — `"Invalid"`
- line 1612013 — `"TitanBash"`
- line 1612135 — `"CanBackStabTarget"`
- line 1612161 — `"LookingTarget"`
- line 1612184 — `"CanBackStabTarget"`
- line 1612207 — `"TargetSpeed"`
- line 1613205 — `"LeanFOV"`
- line 1613222 — `"VisionFOV"`
- line 1613627 — `"Distant"`
- line 1613645 — `"Medium"`
- line 1613661 — `"Personal"`
- line 1613677 — `"Intimate"`
- line 1614395 — `"Floating"`
- line 1614406 — `"Wheeled"`
- line 1614811 — `"Buddy"`
- line 1615359 — `"Normal"`
- line 1615378 — `"BarricadedEntrance"`
- line 1615395 — `"BuildingExteriorObject"`
- line 1615412 — `"BuildingInteriorObject"`
- line 1616298 — `"CoverFOV"`
- line 1616319 — `"LeanFOV"`
- line 1616340 — `"VisionFOV"`
- line 1616620 — `"IsInInteractionBehavior"`
- line 1617465 — `"BuddyRescue_Entry"`
- line 1617478 — `"BuddyRescue_Event"`
- line 1617491 — `"BuddyRescue_Exit"`
- line 1618879 — `"IgnoreNavi"`
- line 1618898 — `"DontIgnoreNavi"`
- line 1618917 — `"SetMountable"`
- line 1618936 — `"SetNotMountable"`
- line 1619022 — `"OnKilled"`
- line 1619039 — `"OnScared"`
- line 1619056 — `"OnHitTarget"`
- line 1619073 — `"OnHurtBy"`
- line 1619090 — `"OnSelf"`
- line 1621903 — `"Player"`
- line 1622114 — `"CFact"`
- line 1622116 — `"CPathID"`
- line 1622704 — `"Warning"`
- line 1622723 — `"Trace"`
- line 1623931 — `"Behind"`
- line 1623944 — `"Front"`
- line 1626476 — `"Second"`
- line 1626503 — `"First"`
- line 1626902 — `"TakeOff"`
- line 1626956 — `"Attack"`
- line 1626983 — `"FlyWander"`
- line 1627010 — `"BackHome"`
- line 1630721 — `"Deploy"`
- line 1630740 — `"Alert"`
- line 1630759 — `"Combat"`
- line 1630778 — `"Break"`
- line 1636396 — `"GREventEndOfGame"`
- line 1643124 — `"_tofemale"`
- line 1665870 — `"Detected"`
- line 1665899 — `"NotDetected"`
- line 1666070 — `"Outside"`
- line 1666517 — `"SomeoneElse"`
- line 1667576 — `"Distance"`
- line 1667682 — `"Angle"`
- line 1668103 — `"PawnSampling"`
- line 1668169 — `"Occlusion"`
- line 1668203 — `"Vegetation"`
- line 1668433 — `"Grass"`
- line 1668511 — `"Stance"`
- line 1668546 — `"Speed"`
- line 1668715 — `"AvatarSkill"`
- line 2382815 — `"engine_status"`
- line 2384560 — `"CFact"`
- line 2384562 — `"ndVec2"`
- line 2398372 — `"DefSessionName"`
- line 2418942 — `"E_SESSION_PARTICIPATION_TYPE_OPEN"`
- line 2425328 — `"dutch"`
- line 2425335 — `"french"`
- line 2436238 — `"float"`
- line 2436287 — `"POSITION0"`
- line 2490532 — `"setInfos"`
- line 2490595 — `"setLine"`
- line 2490684 — `"ClearDataProvider"`
- line 2490729 — `"setInfosFinish"`
- line 2594793 — `"Rotate"`
- line 2594800 — `"RotateStop"`
- line 2594807 — `"ChangePitch"`
- line 2594814 — `"ChangePitchStop"`
- line 2594821 — `"ShellPlacedFP"`
- line 2594828 — `"ShellPlacedTP"`
- line 2594835 — `"TracerPlacedFP"`
- line 2594842 — `"TracerPlacedTP"`
- line 2594849 — `"LaunchFP"`
- line 2594856 — `"LaunchTP"`

---

## Session Wrap-Up

**Coverage summary** (~2,930 unique `FUN_<addr>` labeled, ~6.6% of 44,511 total):

- **Deep coverage**: Terrain init sequence + CTerrain script binding (manual), Audio (CSoundSystem
  fully traced, `.spk` package format cracked), Asset Loading/World (sector streaming grid,
  landmark priority, resource-container machinery), Networking (Quazal RDV SDK identified + Plaza
  service layer), Rendering/Graphics (shader-parameter system, texture streaming, instanced
  cluster/foliage draw calls), Physics/Collision (Havok SDK identified, vehicle physics, collision
  filters), AI/Scripting (Lua/Domino binding primitives, AI event dispatch, navmesh volumes,
  landmark/faction/alert systems).
- **Shallow/sampled coverage**: Math/Utility (huge, generic — only ~90 of probably several
  thousand vector/matrix/string/container helpers sampled).
- **Mechanical only**: 1,532 class RTTI getters (identify the class, not its behavior).
- **Corrected negative result**: the ~531-function cluster at `FUN_10ac0000`-`FUN_10adffff`,
  initially suspected (from one `"Vegetation"`-tagged log call) to be a vegetation-placement
  system, was fully swept and found to actually be a grab-bag of an AI consideration/scoring
  framework, a 2D steering/avoidance subsystem, CRT/ATL runtime glue, and a generic
  reflection/property-tree runtime. A real vegetation placement/scattering system, if present in
  this DLL, was not located this session — see that section for leads (`RegisterVegetationZoneProperties`/
  `FUN_102f3050`, globals `DAT_11224e68`/`DAT_11234f50`).
- **Not attempted this session**: a sizable "Domino" scripted mission/quest-trigger framework was
  discovered (`CDominoManager`, `CDominoWaterLevelManager`, `CDominoConsoleCommandManager`, etc. —
  see the Scripting/Lua Class-Registration Idiom section and the Appendix string index) but not
  swept in depth; UI/HUD (Flash UI, `flashopen`/`flashclose`/... string family) and a full pass over
  the remaining ~110 shader-parameter-provider registration functions (pattern documented, not
  individually named) are also open for a future session.

**Notable discoveries relevant to prior terrain/texture reverse-engineering work** (see
`AGENTS.md`): the engine's own terrain LOD system independently confirms the 65×65 (0x41-stride)
sector grid; `RegisterTerrainDataChannels` confirms exactly 3 terrain data channels
(`TerrainHeights`/`TerrainNormals`/`TerrainParams`) as named, first-class concepts; and the
`CDominoWaterLevelManager` script-registration function confirms water level is a dynamic,
scriptable concept in the engine (though this specific manager reads as a gameplay/cutscene
trigger, not the terrain byte[3] data path itself). No GPU shader bytecode is present in this
CPU-code Ghidra dump, so the terrain layer-blend algorithm and byte[3]'s dry-land sub-variation
remain unresolved by this artifact, consistent with prior sessions' conclusions.
