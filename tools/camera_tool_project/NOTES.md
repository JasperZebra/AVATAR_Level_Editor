# Avatar Free Camera — findings ledger

Started 2026-07-25. Goal: a free camera / noclip mod for *James Cameron's
AVATAR — THE GAME* (PC, 2009, Dunia engine), usable alongside the level editor
for inspecting world geometry against editor coordinates.

## READ-ONLY POLICY

Inherited from `Avatar_FC2_CrossReference_NOTES.txt`. This file is the **only**
place findings get written. The source captures are never edited:

- `tools/Avatar_Dunia_Retail_1.02_decrypted.dll_FULL_DECOMPILE.txt`
  (Avatar's Dunia.dll, Ghidra decompile, 2,614,715 lines, `FUN_xxxxxxxx` names)
- `Downloads/Far cry 2 and Avatar/FarCry2_LinuxServer_Symbols.txt`
  (FC2 dedicated server ELF, real demangled symbols — the naming oracle)
- `Downloads/Far cry 2 and Avatar/Avatar_FC2_AUTO_VTABLE_MATCHES.txt`
  (FC2 Linux vtable layouts, per-slot method names)

Everything below is additive, so a wrong guess never corrupts a source of truth.

## KEY INSIGHT

Dunia ships a **fully implemented free camera**. This is not a mod to be built
from scratch — it is engine functionality to be re-enabled. Confirmed present in
Avatar's own `Dunia.dll`, not just Far Cry 2's.

## [CONFIRMED] Camera components present in Avatar

Extracted as literal strings from the shipped `bin/Dunia.dll` (the DRM-stripped
copy the game actually loads, so this is what runs):

```
CCameraFreeComponent          CCameraEditorComponent
CCameraFreeOrbitalComponent   CCameraMarketingComponent
CCameraGhostComponent         CCameraSpectatorComponent
CCameraPlanetComponent        CCameraThirdComponent
CCameraBoneComponent          CCameraPawnComponent
CCameraGameComponent          CCameraNetworkComponent
CCameraParamVehicleComponent  CCameraShakeAndPadRumbleComponent
```

Avatar has **more** camera types than FC2. `CCameraMarketingComponent`,
`CCameraFreeOrbitalComponent`, `CCameraPlanetComponent` and
`CCameraParamVehicleComponent` have no FC2 equivalent.
`CCameraMarketingComponent` is worth special attention — a "marketing camera" is
by convention a beauty-shot flycam built for capturing promo footage.

## [CONFIRMED] Component descriptor registration (Avatar)

Same lazy `ms_descriptor` accessor pattern as FC2. From the decompile at
line 831328:

| Class | Accessor | Descriptor global |
|---|---|---|
| `CCameraNetworkComponent` | `FUN_104cac00` | `DAT_11221b18` |
| `CCameraFreeComponent`    | `FUN_104cac80` | `DAT_11221b30` |
| `CCameraGhostComponent`   | `FUN_104cace0` | `DAT_11221b64` |

`FUN_104cace0` calls `FUN_104cac80` before registering, which means
**`CCameraGhostComponent` derives from `CCameraFreeComponent`**. Ghidra cannot
recover inheritance on its own; this fell out of the registration order.

`FUN_1051bb30` is the `SafeCast<CCameraFreeComponent>` helper — takes a
component pointer, checks its type id against `DAT_11221b48`, returns the
pointer or null. Useful for identifying a free-cam component at runtime given
any entity component.

## [CONFIRMED] CCameraFreeComponent vtable layout

From FC2's Linux vtable (`_ZTV20CCameraFreeComponent`, 44 slots / 176 bytes).
Assumed to carry over to Avatar — **not yet verified against Avatar's binary**,
see open questions.

```
slot 25 (+0x64)  Update(float, EEntityUpdateFlags)
slot 35 (+0x8c)  SetFocus(TEntityHandle<CEntity>)
slot 36 (+0x90)  Activate()
slot 37 (+0x94)  DeActivate()
```

`Activate()` at vtable **+0x90** is the switch we ultimately want to throw.

## [CONFIRMED] Script API — SwitchCamera call chain

`FUN_10a8ac70` registers 85 Domino script actions via registrar `FUN_100de5f0`.
Independently corroborated: the prior cross-reference session matched this
function to FC2-Windows `FUN_109fc830` at score 67 on shared script-action
strings.

Camera / position primitives in that table:

| Script name | Thunk |
|---|---|
| `SwitchCamera` | `LAB_10a89720` |
| `TeleportEntity` | `LAB_10a8a520` |
| `AvtSetEntityPos` | `LAB_10a86750` |
| `CameraShakeAndGamePadRumble` | `LAB_10a893f0` |

`AvtSetEntityPos` is Avatar-specific (`Avt` prefix) and is the obvious noclip
primitive. Full list: `analysis/out/avatar_lua_api.txt`.

The thunks are **not** in the decompile — Ghidra never promoted them to
functions. Disassembled directly (`analysis/disasm_at.py`):

```asm
; LAB_10a89720 — Lua thunk, 6 instructions
10a89720  mov  eax, [esp+4]        ; lua_State*
10a89724  push 0x10a88680          ; &SwitchCamera  (in .text, so it's code)
10a89729  push eax
10a8972a  call FUN_10a85eb0        ; generic arg-marshalling dispatcher
10a8972f  add  esp, 8
10a89732  ret
```

So the real function is **`SwitchCamera` @ `0x10a88680`**, signature
`(int cameraType, EntityId entity)` per the FC2 symbol.

Its body branches on the first argument:

- **`cameraType == 0`** → `FUN_104d9370` on global `[0x112225d8]`, then
  `FUN_101a3290`. Reads as *restore default / player camera*.
- **`cameraType != 0`** → pushes both args plus global `[0x111e634c]`, calls
  `FUN_100468e0`, then `FUN_101a32c0`. Reads as *switch to camera type N on
  this entity*.

### [CONFIRMED] What SwitchCamera's `int` actually is — NOT a camera-type enum

Traced the whole chain. The initial guess (that `cameraType` indexes a table of
camera components) is **wrong**. What the arguments really are:

- `FUN_100468e0(&out, lo, hi)` is an **entity lookup**, not a camera-type map.
  Its lazy initializer `FUN_100461b0` registers `"CEntity"` — so `DAT_111c21b8`
  is CEntity's descriptor and this resolves an `EntityId` (passed as two dwords,
  `[esp+0x14]` / `[esp+0x18]`) into a `TEntityHandle<CEntity>`.
- The two downstream wrappers are thin:
  - `FUN_101a3290(x)` → `FUN_10249d00(x, 0)` then `FUN_101a2f50()`  — reset path
  - `FUN_101a32c0(x)` → `FUN_10249540(x)` then `FUN_101a2f50()`     — switch path
- **`FUN_10249540(manager, &entityHandle)` is a camera stack.** Layout of the
  manager object:

  | Offset | Meaning |
  |---|---|
  | `+0x10` | current/active index |
  | `+0x18` | array base, entries are `0x18` bytes |
  | `+0x1c` | entry count |

  It walks the array comparing entity handles (fields `[0]`, `[1]`, `[3]` — a
  3-dword handle identity check), activates the entry if already present,
  otherwise appends a new one.

**Consequence:** you do not select a camera by passing a type index. You select
a camera by pointing `SwitchCamera` at **an entity that carries the camera
component you want**. The `int` argument is a mode/flag — zero reverts to the
default player camera, non-zero switches to the named entity's camera.

So the real question becomes: *how do we obtain an entity carrying a
`CCameraFreeComponent`?* Two ways, and the first fits existing tooling
unusually well:

1. **Place one from the level editor.** The editor already authors entities into
   the level. If a camera entity with a free-camera component can be authored
   as data, `SwitchCamera` picks it up with no code injection at all — and the
   editor becomes the freecam's placement UI. Strongest lead.
2. **Find or construct one at runtime.** `FUN_1051bb30` (the
   `SafeCast<CCameraFreeComponent>` helper) identifies such a component given
   any component pointer, so a runtime walk of entity components can locate one
   if the level already spawns it.

## [CONFIRMED] The camera entities ship as authored data — with fixed IDs

The decisive find. Avatar's own `entitylibrary.fcb` (2,733 prototypes, already
converted at `__GameFilesPC/xml_cracking_test/fcb_file/entitylibrary.fcb.converted/`)
contains a complete, contiguous block of **camera entity prototypes**:

| Entity | ID | Component |
|---|---|---|
| `Camera.AnimatedCameraToken` | 255 | — |
| `Camera.Bone` | 256 | `CCameraBoneComponent` |
| `Camera.Cinematic` | 257 | `CCameraBoneComponent` |
| `Camera.Editor` | 258 | `CCameraEditorComponent` |
| `Camera.First` | 259 | `CCameraPawnComponent` |
| `Camera.FirstAvatar` | 260 | `CCameraPawnComponent` |
| `Camera.FirstCorp` | 261 | `CCameraPawnComponent` |
| **`Camera.Free`** | **262** | **`CCameraFreeComponent`** |
| `Camera.FreeOrbital` | 263 | `CCameraFreeOrbitalComponent` |
| `Camera.Ghost` | 264 | `CCameraGhostComponent` |
| `Camera.Marketing` | 265 | `CCameraMarketingComponent` |
| `Camera.Planet` | 266 | `CCameraPlanetComponent` |
| `Camera.Spectator` | 267 | `CCameraSpectatorComponent` |
| `Camera.Third` | 268 | `CCameraThirdComponent` |
| `Camera.ThirdAvatar` | 269 | `CCameraThirdComponent` |
| `Camera.ThirdCorp` | 270 | `CCameraThirdComponent` |

`Camera.Third*` being in this list is the important corroboration — that's the
*normal gameplay camera*. The game switches between all of these by entity, so
the free camera is not a special case; it sits in the same table as the camera
you look through every second of play.

`Camera.Free` in full (`hidName` = `cameras.Camera.Free`, class `CEntity`):

```xml
<object name="CCameraFreeComponent">
  <field name="fCameraBlendTime" value-Float32="0"    />
  <field name="fNearDistance"    value-Float32="0.1"  />
  <field name="fFarDistance"     value-Float32="5000" />
  <field name="fFOV"             value-Float32="70"   />
  <field name="fSpeed"           value-Float32="5"    />   <!-- flight speed -->
</object>
<object name="CPersistComponent"> ... </object>
```

The developers' own free camera, with tunable flight speed, FOV and clip planes,
shipped in the retail data.

## [DERIVED] SwitchCamera calling convention

`disEntityId` is `Id64`, so `EntityId` is 64-bit. Tracing the stack through the
prologue at `0x10a88680` (`sub esp,8` → `push esi` → `push edi` → … → `pop edi`)
puts the arguments at `[esp+0x10]` = `cameraType` and `[esp+0x14]`/`[esp+0x18]`
= the low/high dwords of `EntityId`. So, cdecl:

```asm
push entityId_hi
push entityId_lo
push cameraType
call 0x10a88680
add  esp, 0xC
```

**Working hypothesis, not yet tested:** `SwitchCamera(1, 262)` activates the
free camera. Implemented in `runtime/switch_camera.py`.

Caveat to settle by experiment: 255–270 are *entity library prototype* IDs. It
is not yet established that the runtime `EntityId` matches. If it does not, the
fallback is to locate the live camera entity by walking components with the
`SafeCast<CCameraFreeComponent>` helper `FUN_1051bb30`.

## LIVE TEST 2026-07-25 — call executed, no visible effect

Game running, level loaded. `runtime/switch_camera.py free` executed
`SwitchCamera(1, 262)` twice. Both times: remote thread returned exit code 0,
**game did not crash**, and no visible camera change.

Established during the session:

- **Dunia.dll loads at its preferred base `0x10000000` — ASLR slide is zero.**
  Every static address in this file is directly valid at runtime as-is.
- **The DRM-stripped `bin/Dunia.dll` matches the analysed retail-decrypted DLL
  byte-for-byte at `SwitchCamera`** (`a1 f8 61 1e 11 83 ec 08`). The two copies
  are interchangeable for analysis.
- **SwitchCamera does not bail at its first gate.** Both early-exit guards pass
  live (`[0x111e61f8]+8` = 1, and the inner object is non-null), and
  `FUN_10a86f50`'s condition — `[[[esi+4]+8]+0xc] != 0` — evaluates true. So
  execution reaches the switch path. Why nothing happens is still unknown; the
  next suspect is the post-resolve check `cmp [eax+0xc],0 / je` that skips the
  switch when the entity handle fails to resolve.

## [CONFIRMED] Component descriptor object layout

`DAT_11221b30` and friends are the descriptor **objects themselves**, not
pointers to them — the accessor returns `&DAT_...`. Layout:

```
+0x00  char*  class name        -> "CCameraFreeComponent"
+0x04  uint32 hash count        = 5
+0x08  uint32[count] hierarchy hashes, last entry is the class's own hash
```

| Class | count | own hash |
|---|---|---|
| `CCameraFreeComponent` | 5 | `005A5087` |
| `CCameraThirdComponent` | 5 | `54042A27` |
| `CCameraPawnComponent` | 6 | `61449071` |

Shared prefix `48AD6F22 F320EEF0 6D1A6418 496E8EE4` is the inherited chain;
`496E8EE4` is common to all three and is therefore `CCameraComponent`.

**`005A5087` is exactly the hash used in the entity library data** —
`Camera.Free_1.xml` declares `<object hash="005A5087" name="CCameraFreeComponent">`.
Runtime class identity and FCB data hash are the same value. This is strong
evidence that a component authored into level data instantiates as the real
runtime class, which is what the data route depends on.

Descriptor objects are laid out contiguously: `CCameraEditorComponent`'s
descriptor begins at `0x11221b30+0x1c`, immediately after Free's.

## [FALSE LEAD, CAUGHT] Two wrong turns worth not repeating

1. **The camera manager is NOT `[[[0x111e61f8]+4]]`.** Read live, that object's
   `+0x1c` "entry count" came back as `0x7FFFFFC1` and `+0x10` as garbage. `esi`
   in `SwitchCamera` is the script/game object, not the camera stack manager.
   The manager `FUN_10249540` operates on is reached further along; re-derive it
   before trusting any camera-stack read.

2. **Scanning memory for descriptor pointers does not find component
   instances.** `GetDescriptor()` is *virtual* (vtable slot 6), so instances
   store a vtable pointer and never a descriptor pointer. Confirmed by control:
   `CCameraThirdComponent` and `CCameraPawnComponent` — which must be live
   during normal gameplay — scanned as zero heap references, identically to
   `CCameraFreeComponent`. **A zero result from this technique proves nothing.**
   `runtime/find_camera_components.py` retains the controls precisely so this
   cannot be misread again. To find instances, scan for the *vtable* address —
   which means Avatar's vtable must be located first (see open question 2).

## [CONFIRMED] Why SwitchCamera(1, 262) did nothing — no Camera.Free instance

Found with `runtime/memscan.py`, which was first validated against four
searches whose answers were already known (descriptor read, class-name string
location, `SwitchCamera` prologue AOB, and pointers-to the name string — all
landed exactly on the predicted addresses).

Searching the heap for `cameras.Camera` finds the **live** camera entities:

| Live on heap | Address |
|---|---|
| `cameras.Camera.ThirdCorp` | `0x18dbfae0` |
| `cameras.Camera.First` | `0x191afa60` |
| `cameras.Camera.AnimatedCameraToken` | ×4, `0x18f10ea0` … |

**`cameras.Camera.Free` is absent from the heap.** Its only matches are in the
`0x3275xxxx` region, which is not live objects — it is the entity library
itself, parsed in memory. The FCB field hashes are visible inline there:

```
38 d1 11 fe  0c  "Camera.Free\0"           <- FE11D138 = "Name"
c7 5c 29 b9  14  "cameras.Camera.Free\0"   <- B9295CC7 = "hidName"
```

which matches `Camera.Free_1.xml` field-for-field.

**Conclusion:** the level instantiates only the cameras gameplay needs
(Third/First/AnimatedCameraToken). `Camera.Free` exists as a *prototype* —
loaded, parsed and resident — but is never turned into an entity. So
`SwitchCamera(1, 262)` resolves entity 262, finds nothing, and takes the
`cmp [eax+0xc],0 / je` branch that skips the switch. The function worked
correctly; there was simply nothing to switch to.

This supersedes the withdrawn scan result above — same conclusion, but now
with evidence rather than a technique that couldn't distinguish "absent" from
"undetectable".

### Consequence for the plan

Route 3 (inject and call `SwitchCamera`) cannot work on its own. The camera
entity has to exist first. That leaves:

- **Instantiate the prototype at runtime** — find the engine's spawn-from-
  prototype path and call it with `Camera.Free`, then `SwitchCamera` to the
  resulting entity. Needs more RE but is self-contained.
- **Author it into level data** — place a `Camera.Free` entity into a
  worldsector so the level instantiates it on load. The matching hashes
  (`005A5087` in both the live descriptor and the FCB) mean it should
  instantiate as the genuine runtime class. This is the level editor's home
  turf and needs no injection.

## [FOUND] Live camera transform matrices — 2026-07-25

Located empirically with `memscan.py` plus known editor coordinates, which is
far faster than unknown-value scanning alone. **Ground-truthing against the
level editor's coordinates is the single biggest accelerator available on this
project — use it first, every time.**

Method that worked, in order:

1. Unknown-value f32 snapshot, then alternating `refine --changed` (while
   moving) and `refine --unchanged` (while still): 7.4M → 2.4M → 890K → 240K.
2. Alternation stalled around 139K, so switched to **known coordinates**. User
   reported standing near `(594, 288, 31)` in editor space; scanning for that
   triple in any axis order found `(592.13, 290.11, 33.68)`. **The game's axis
   order matches the editor's directly — no permutation or sign flip needed.**
3. Moved to `(647, 281, 31)` and kept only sites that both *changed* and now
   held the new position: 6,455 → 5,700 tracking sites.
4. Rotation-only test (mouse turn, no walking) to separate camera from player,
   then filtered to orthonormal 4×4s whose *rotation rows* changed: 166 → 75.

### Result

A group of five matrices, evenly spaced ~0xE00 apart, rotating together and
sitting ~2.3 m from the player and slightly above — a ring of per-frame camera
transforms:

```
0x0c3cc950  0x0c3cd750  0x0c3ce550  0x0c3cf350  0x0c9175e0
```

`0x0c3cc950` read live:

```
right   -0.9510  -0.3093  -0.0016   0.0000
up       0.3028  -0.9300  -0.2085   0.0000
fwd      0.0631  -0.1988   0.9780   0.0000
POS    646.3718 282.3441  33.4197   1.0000
```

Perfectly orthonormal (all three basis rows measure exactly 1.0000) with a
canonical `0,0,0,1` last column. Row-major, translation in **row 3**.

**These are heap addresses and will not survive a level reload or restart.**
They are for experimentation only; the durable target is the code that *writes*
them, per the AFOP approach below.

### Two matrix conventions exist here too

Earlier in the same scan, a static (non-tracking) transform pair appeared in
both layouts simultaneously — `0x0c5dc370` with translation in row 3, and
`0x0c5dbc90` holding its exact transpose with translation in the 4th column.
This is the same trap the AFOP tool's README documents. Any code reading or
writing a Dunia matrix must re-verify which layout it has rather than assume.

## Reference implementation: the AFOP camera tool

`C:\Users\sambe\Desktop\AFOP_TESTING\CAMERA_TOOL` is a complete, working
external freecam for *Avatar: Frontiers of Pandora* — pure ctypes, no DLL
injection, verified live. It is the architectural template for this project:

1. AOB-scan for the camera-matrix-**write** routine.
2. Displace its first instructions into an allocated **code cave** that (a)
   captures the camera object pointer from a register every time the game
   writes, and (b) on a freeze flag jumps straight to the routine's `ret`,
   skipping every matrix store.
3. Drive the camera from outside the process.

Critical lesson recorded in its notes, expected to apply here as well:
**writing the destination matrix from outside was measured NOT to move the
rendered view — the SOURCE matrix being copied is the thing to control.**

Its AOB does not transfer: it matches a `movups`-based 4×4 copy, and scanning
Dunia for that shape returns hits only in the AMD driver and `combase`, none in
Dunia itself. Expected — AFOP is a 2023 x64 build, Avatar is 2009 x86. Avatar's
write site must be found independently.

Porting the hook to x86 means a 5-byte `E9 rel32` patch rather than AFOP's
14-byte absolute `jmp [rip]`, and 32-bit registers throughout.

## [KEY INSIGHT] The render camera is CSceneCamera, and it is DOUBLE-BUFFERED

This is why writing the matrix did nothing, and it reframes the whole approach.
Recovered from the FC2 Linux symbols, which name the entire path:

```
CCameraComponent::ReadSceneCamera() const      46 bytes   read-only access
CCameraComponent::ModifySceneCamera()          48 bytes   writable access
CCameraComponent::UpdateSceneCamera()          64 bytes   pushes component -> scene
CCameraComponent::SetFOVInDeg(float)
CCameraComponent::GetFOVInDeg() const
CCameraComponent::SetPositionFractions(ndVec_tpl<float,3> const&)
CCameraComponent::BlendWithPreviousCamera(ndVec_tpl<float,3>*, ndAngle3<float>*, float)
```

The gameplay-side `CCameraComponent` does **not** own the rendered view. It
pushes its transform into a separate render-scene object, `CSceneCamera`, and
that object is managed by a double-buffered container:

```
CSceneObjectContainer<CSceneCamera>::ReadOriginal(handle)
CSceneObjectContainer<CSceneCamera>::ReadCopy(handle)
CSceneObjectContainer<CSceneCamera>::GetOriginalSingleton()
CSceneObjectContainer<CSceneCamera>::SyncForRendering()
CSceneObjectContainer<CSceneCamera>::CNodeData::SetBackup(CSceneCamera*, uint)
CSceneObjectContainer<CSceneCamera>::CNodeData::UseBackup()
CSceneObjectContainer<CSceneCamera>::FreeBackups()
```

**This explains the failed write test.** 58,740 writes to the five matrices at
`0x0c3cc950`… changed nothing on screen because those were *copies*. The
renderer reads a different buffer, and `SyncForRendering()` overwrites the copy
from the original every frame. The ring of five matrices spaced `0xE00` apart
is exactly what a copy/backup ring looks like.

It also explains why `find_writers` caught nothing there — a stale backup node
isn't written every frame, so a 5-second watch on one can legitimately see zero
writes. That result was never evidence the tool is broken (still unvalidated
either way — validate against a known-hot address before trusting it).

### CSceneCamera is confirmed present in Avatar

The string `CSceneCamera` exists in Avatar's `Dunia.dll` at VA `0x110172d8`
(.rdata), with exactly one pointer to it at `0x110172e8` — a type-info record.
Neither is cross-referenced in the decompile, so Ghidra reached it indirectly.

Critically, it sits inside the **scene-object type-name table**, whose
neighbours are already familiar territory for this project:

```
CSceneFogOfWar   CSceneGodRay   CSceneFakeAOPrimitive   CScenePostFxMotionBlur
CSceneMaterialContainer   CScenePostFxAtmosphericFog   CSceneOffscreenViewport
>>> CSceneCamera <<<   CSceneSky   CSceneSun
```

The editor already handles `CSceneSky` and `CSceneSun` (sky/sun/night sharing
and god rays). **`CSceneCamera` is the same kind of object, in the same table.**
Whatever pattern the editor already uses to reach sky/sun applies here.

### There is a built-in scene-camera OVERRIDE

FC2's editor camera exposes precisely the API a freecam needs:

```
CFCXEditorCamera::OverrideSceneCamera()      15 bytes
CFCXEditorCamera::ReleaseSceneCamera()       15 bytes
CFCXEditorCamera::SetCamera(ndVec_tpl<float,3> const& pos,
                            ndAngle3<float> const& angles, bool, bool)   567 bytes
CFCXEditorCamera::GetSceneCamera()
CFCXEditorCamera::ModifySceneCamera()
CFCXEditorCamera::UpdateSceneCamera()
CFCXEditorCamera::ApplyConstraints(...)
CFCXEditorCamera::CenterToPosition(...)  /  ScrollToPosition(...)  /  UpdateBlend(float)
```

`OverrideSceneCamera()` being only 15 bytes means it is a trivial setter — it
flips a flag or stores a pointer that makes the scene camera follow the editor
camera instead of gameplay. That is a freecam switch built into the engine.

### Revised targets, in priority order

1. **`UpdateSceneCamera` / `ModifySceneCamera`** — hook the write, don't fight
   the double buffer. This is the correct analogue of what the AFOP tool hooks.
2. **The `CSceneCamera` original singleton** — writing the original rather than
   a copy may stick where writing copies did not.
3. **The override flag** — if Avatar retains `OverrideSceneCamera`'s mechanism,
   setting it is a single write.

Note the earlier `SwitchCamera` work is *not* wasted: it operates one level up
(which entity owns the camera). But the rendered view is decided here.

## [CONFIRMED] Static anchors for CSceneCamera — survive restarts

Dunia.dll loads at its preferred base every time observed, so these are usable
as-is with no slide:

| What | Address |
|---|---|
| `"CSceneCamera"` string | `0x110172d8` (.rdata) |
| type-info name-pointer field | `0x110172e8` |
| **`CSceneObjectTypeInfo<CSceneCamera>` vtable** | **`0x110172f4`** |
| **static type-info instance** | **`0x11178368`** |
| container sub-object (instance + 0x20) | `0x11178388` |
| scene-object size | `0x40` (64 bytes = one 4×4 matrix) |

The type-info record layout at `0x110172e8`:

```
+0x00  char*  "CSceneCamera"
+0x04  char*  "CSceneOffscreenViewport"   (parent type name)
+0x08  float  45.0                        (default FOV?)
+0x0c  vtable[7] -> 0x1007d8f0, 0x10061170, 0x10086500, 0x10084760,
                    0x10087490, 0x10084960, 0x1007d8e0
```

`0x1007d8f0` is the ctor/dtor (`mov [esi], 0x110172f4`). The other six are
adjustor thunks of the form `add ecx, 0x20 ; jmp <generic>` — confirming the
container sub-object sits at **+0x20** and that container code is shared
generically across every scene-object type.

`FUN_1007cce0(&DAT_11178368, param_1)` registers it, in a long run of identical
calls for every other `CScene*` type — this is Dunia's `InitGraphicsDatabase`
(the FC2 symbols name a `InitGraphicsDatabase.cpp` translation unit, matching).

**Dead end warning:** walking the container from `0x11178388` did not reach
camera data. Its list head at `+0x00` points to itself+4 (an empty intrusive
list), and the two node pointers at `+0x28`/`+0x2c` lead into a generic
allocator pool holding unrelated data (`gfx_Draw_Sectors` strings). Either the
camera is reached via `GetOriginalSingleton()` rather than the list, or the
layout differs from the FC2 build. Do not sink more time into hand-walking this
structure without a reason to think it changed.

## [DANGER] find_writers.py is suspected of crashing the game

Two runs on 2026-07-25, two dead games — one closed moments after a "clean"
detach, one outright crash. **Both runs also caught zero writes, including on a
player-position address that is written every frame.** That combination says
the debug registers were probably never armed at all, so the risk bought
nothing.

Do not run it against the game again until DR0/DR7 readback is verified (a
readback check is now in the script) and it has been proven against a throwaway
process. Hardware-breakpoint debugging may simply not be viable on this target.

**Prefer static analysis of the decompile.** It is free, safe, repeatable, and
this project has a 68 MB decompile plus a naming oracle sitting right there.

## [BREAKTHROUGH] Class field offsets are literally in the binary

Dunia registers every serialisable field through a per-class
`RegisterProperties` routine that writes the field's **byte offset as an
immediate**. The compiled binary therefore contains an exact field map for
every reflected class — recoverable offline, no debugger, no scanning:

```asm
push 0x14                     ; sizeof(property record)
call operator_new
mov  [esi],     0x11014c1c    ; record vtable
push 0x1103d6f8               ; -> "fCameraBlendTime"
mov  [esi+4],   0x1103d6f8    ; name pointer
call hash_name
mov  [esi],     0x110d8a2c    ; TYPE descriptor (0x110d8a2c = float)
mov  [esi+0xc], 0x54          ; <<< BYTE OFFSET OF THE FIELD
push esi
push 0x111e8804               ; the class's property-list global
call add_property
```

`analysis/dump_properties.py` recovers this for the whole DLL —
**530 class property tables**, dumped to
`analysis/out/dunia_class_properties.txt`. This is broadly useful beyond the
camera; it is an exact field map for every reflected Dunia class.

### CCameraComponent layout (property list `0x111e8804`)

Verified twice: by the tool, and by reading the disassembly at `0x1024b860`
by hand.

| Offset | Field | Type |
|---|---|---|
| `+0x54` | `fCameraBlendTime` | float |
| **`+0x58` … `+0x73`** | **28 unregistered bytes** | **← the transform** |
| `+0x74` | `fNearDistance` | float |
| `+0x78` | `fFarDistance` | float |

`fFOV` is absent from the table because it is a **method-backed** property —
its registration stores a register rather than a literal offset, matching
`CCameraComponent::SetFOVInDeg` / `GetFOVInDeg` in the FC2 symbols. That is
consistent behaviour, not a gap in the tool.

### Hypothesis: the camera transform lives at +0x58..+0x73

28 bytes is exactly 7 floats, and FC2's signature
`CCameraGameComponent::BlendLookAnglesWithLookAt(ndVec_tpl<float,3> const&, Gear::Quaternion4<float>&)`
pairs a vec3 with a quaternion — 3 + 4 = **7 floats = 28 bytes**. The runtime
transform is not serialised (it is live state, not a saved property), which is
exactly why it appears as a hole in an otherwise contiguous property map.

Candidate layouts, to be settled by reading a live instance:

```
+0x58  vec3 position (3f)   +0x64  quaternion (4f)
        -- or --
+0x58  quaternion (4f)      +0x68  vec3 position (3f)
```

**Test when the game is next up:** find a live `CCameraComponent` instance,
read `+0x58`..`+0x73`, and check whether three of those floats match the
player's editor coordinates. That single read settles the layout.

### Tool accuracy caveat

`dump_properties.py` associates a property with the *next* property-list global
it sees, which sometimes merges adjacent classes into one list (e.g.
`0x11010a5c` is visibly several classes concatenated, with impossible 700-byte
gaps). Treat a single class's table as reliable only when its fields are
contiguous and plausible. The camera table was hand-verified.

### Ruled out as an asset

`FC2Windows_RTTI_Vtables.txt` (6.7 MB) is not worth reading. All 396 classes in
it are Demonware (`bd*`) and `magma` middleware; Dunia's own classes were
compiled without RTTI. No `CCamera*` anything. Do not open it again.

## [CONFIRMED] A developer console exists in the binary

`CDominoConsoleCommandManager`, `CFCXConsole`, `CConsoleService`,
`CFCXConsoleService`, `AVLogDeviceConsole`, plus a full glyph set
`console_char_a` … `console_char_Z` — a console that *renders on screen*, not
just command plumbing. cvar-style names also present: `camera_enableSlomo`,
`debug_showWeatherInfo`, `debug_set`, `render_menu`, `debug_machetetest`.

A prior Cheat Engine session found `DAT_11233978`, a ~28 MB live command
registry holding names like `InventoryHack`, `FlashCommand`, `FadeToBlack`.
Per the existing notes it is **not** a `CConsoleService` instance (its vtable
has 70+ slots vs `CConsoleService`'s 27) — it's a generic name→handler map
referenced *by* the console service. If a camera command lives in that table,
the console route becomes much more attractive than injection.

## Binary provenance

`bin/Dunia.dll` and friends are DRM-stripped (`.bak` files are the originals;
`Dunia.dll.bak` is ~12 KB larger). The wrapper came *out*, so the shipped DLL is
unpacked, non-self-modifying, and clean for static analysis.

Per the earlier session's section audit, `Dunia_LIVE_DECRYPTED.dll` and
`Dunia_Retail_1.02_decrypted.dll` are the **same build** (identical PE
TimeDateStamp `0x4b3449eb`), differing only in capture completeness. Retail's
`.text` is 99.98% intact, which is why the decompile taken from it is sound.
`Dunia_LIVE_DECRYPTED.dll` is strictly more complete and is the file to re-dump
from if anything ever looks truncated.

**Addresses in this file assume the preferred image base `0x10000000`.** At
runtime the loaded module base must be read and the ASLR slide applied. Nothing
gets hardcoded.

## OPEN QUESTIONS / NEXT STEPS

1. **Read `FUN_100468e0`** to recover the `cameraType` int → camera component
   mapping. This is the single highest-value unknown: it turns `SwitchCamera`
   from "a function we found" into "a function we can call correctly".
2. **Verify the vtable layout on Avatar's binary.** Avatar has four camera
   components FC2 lacks, so slot indices may have shifted. Do not trust +0x90
   until it is confirmed against Avatar's own vtable construction code.
3. **Search `DAT_11233978`'s command registry for camera entries** — decides
   whether the console route is viable.
4. **Find how the console is gated.** If it can be summoned, the whole debug
   command set comes with it, which is independently valuable for level-editor
   work.
5. Establish whether Avatar loads `.lua` from the `.pak` archives, which would
   allow shipping the freecam as data with no injection at all.

## ROUTES, RANKED

1. **Console unlock** — biggest payoff (whole debug command set), least certain.
2. **Lua via data files** — cleanest deliverable if the paks load scripts.
3. **DLL injection calling `SwitchCamera` @ `0x10a88680`** — least elegant,
   but works regardless of 1 and 2. This is the guaranteed floor, so the
   project cannot fail outright; only its elegance is in question.
