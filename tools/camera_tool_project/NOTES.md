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
