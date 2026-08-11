# Far Cry 2 (Dunia Engine) DLL — Function Reference (Best-Effort Partial Sweep)

Source file: `Dunia_FarCry2.dll_FULL_DECOMPILE.txt` (Ghidra decompile, ~2.6 million lines).

## Scope / methodology

- Total `FUN_<addr>`-style unresolved function definitions in this dump: **~54,700** (regex count of
  function-signature lines matching `^(void|undefined4|...) (__thiscall|__cdecl|__fastcall)? ?FUN_[0-9a-f]+`).
- This document is a **partial, best-effort sweep**, not an exhaustive one. Given the file's size, full manual
  coverage of all 54,700 functions is not achievable in one pass. Entries below were prioritized by relevance to
  this editor project (terrain/.sdat, FCB serialization, XBT/texture atlases, world/level document export,
  object/entity/inventory system) with a lighter, breadth-first sweep of other subsystems.
- **Key discovery**: unlike the Avatar-side DLL (which is almost entirely `FUN_*` placeholders), this Far Cry 2
  DLL retains a large number of **real exported symbol names** recovered by Ghidra — notably ~312 `FCE_*`
  ("Far Cry Editor") functions and ~27 `FCS_*` ("Far Cry Server") functions, plus core entry points
  (`InitDuniaEngine`, `TickDuniaEngine`, `RunDuniaEngine`, etc.). These are the **actual public Editor SDK API**
  this level editor's `FCE_*` C API surface would have bound against historically. They are not `FUN_*` so are
  outside this doc's literal naming task, but they are documented here (see "Named Editor API" section) because
  they are massively useful anchors: many `FUN_*` helper functions sit immediately adjacent to them in address
  order, or are called directly by them, which is how most high-confidence labels below were derived.
- Method used per labeled `FUN_*`: locate via (a) proximity/call graph from a named `FCE_*`/`FCS_*` export,
  (b) nearby string literals (asserts, file-path format strings, debug labels), (c) recognizable constants
  (e.g. FCB magic `0x4643626e` "nbCF"), or (d) structural/API-call pattern recognition (CRT calls, container
  push_back shapes, etc.) when nothing more specific was available. Each entry's justification says which.
- Thin one-call trampolines/thunks are generally skipped unless the single call target is itself informative.
- Navigation note for future passes: function signature lines can be re-enumerated with:
  `^(void|undefined4|undefined8|undefined2|undefined1|int|float|double|char|bool|uint|ulong|longlong|undefined|short|byte|CONCAT[0-9]+) (__thiscall|__cdecl|__fastcall)? ?FUN_[0-9a-f]+`
  Named (non-`FUN_`) function headers are lines matching `^### [A-Za-z_][A-Za-z0-9_]* +@ [0-9a-f]+`.

---

## Named Editor API (already resolved by Ghidra — reference, not `FUN_*`)

These are NOT part of the "name the FUN_ functions" task (they already have real names) but are recorded here
because they are the load-bearing map of what this DLL's Editor SDK actually exposes, and they anchor the
`FUN_*` clusters labeled in later sections.

### Core engine entry points
- `InitDuniaEngine` @ 10004900, `TickDuniaEngine` @ 10001ba0, `RunDuniaEngine` @ 10001bb0,
  `CloseDuniaEngine` @ 10001bd0, `ShutdownDuniaEngine` @ 10001be0 — engine lifecycle, called by the host EXE
  (editor or game). `SwitchContext` @ 10002a90, `RegisterGameFunctionProvider` @ 10001cc0,
  `AddFunctionCB` @ 10001cd0, `PrintToConsole` @ 10001c90, `GetExePath` @ 10002220, `LocalizeText` @ 10006050,
  `RunGame` @ 10006510.
- `CThreadInformer` class (`GetLastLine`, `GetLastThread`, `GetLastFile` @ 0xd6a0a0) — thread-local error/status
  info object threaded through nearly every FCB/file-load call in this DLL (seen constantly below as `this`).

### `FCE_*` — Far Cry Editor public API (~312 functions, `10310420`–`10a21200` range)
Grouped by prefix as they appear in the dump (all real Ghidra-recovered names, addresses omitted here for
brevity — grep `### FCE_` in the source file for exact addresses):
- **Engine/Editor lifecycle**: `FCE_Engine_UpdateViewport`, `FCE_Engine_AutoAcquireInput`, `FCE_Engine_GetTimeOfDay`,
  `FCE_Engine_SetTimeOfDay`, `FCE_Engine_GetStormFactor/SetStormFactor`, `FCE_Engine_IsConsoleOpen`,
  `FCE_Engine_GetPersonalPath`, `FCE_Editor_IsInitialized`, `FCE_Editor_Update_Callback`, `FCE_Editor_Event_Callback`,
  `FCE_Editor_LoadCompleted_Callback`, `FCE_Editor_SaveCompleted_Callback`, `FCE_Editor_EnableUI_Callback`,
  `FCE_Editor_IsLoadPending`, `FCE_Editor_GetFrameTime`, `FCE_Editor_ValidateIngame`, `FCE_Editor_ToggleIngame`,
  `FCE_Editor_IsIngame`, `FCE_Editor_GetScreenPointFromWorldPos`, `FCE_Editor_GetWorldRayFromScreenPoint`,
  `FCE_Editor_RayCastTerrain`, `FCE_Editor_RayCastPhysics` / `RayCastPhysics2`.
- **Document (level/map) management**: `FCE_Document_Reset/Load/Save/Validate/Export`,
  `FCE_Document_GetBattlefieldSize/SetBattlefieldSize`, `FCE_Document_GetPlayerSize/SetPlayerSize`,
  `FCE_Document_IsSnapshotSet/ClearSnapshot/TakeSnapshot`, `FCE_Document_FinalizeMap`,
  `FCE_Document_GetMapName/SetMapName`, `FCE_Document_GetCreatorName/SetCreatorName`,
  `FCE_Document_GetAuthorName/SetAuthorName`, `FCE_Document_GetSnapshotPos/SetSnapshotPos`,
  `FCE_Document_GetSnapshotAngle/SetSnapshotAngle` — this is the "save/load/finalize/export a level" surface;
  `FCE_Document_FinalizeMap` and `FCE_Document_Export` are the most likely public entry points into the large
  FCB-writer cluster documented under "Asset Loading (FCB/XBT)" below.
- **Editor settings/visibility toggles**: `FCE_EditorSettings_Is*/Show*` for collections, fog, shadows, water,
  icons, sound, grid, snapping (to terrain/objects/rotation), camera clipping, engine quality, kill-distance.
- **Object/Inventory system**: `FCE_Object_Create_FromEntry`, `FCE_Object_Destroy/AddRef/Release/Clone`,
  `FCE_Object_IsLoaded/IsVisible/SetVisible/SetHighlight/SetFreeze`, `FCE_Object_GetPos/SetPos/GetAngles/SetAngles`,
  `FCE_Object_GetBounds/GetPivot/GetClosestPivot`, `FCE_Object_DropToGround/SnapToClosestObject`,
  `FCE_Object_ComputeAutoOrientation`, `FCE_Object_GetPhysEntities`, `FCE_Inventory_Object_*` /
  `FCE_Inventory_Collection_*` / `FCE_Inventory_Texture_*` / `FCE_Inventory_Spline_*` /
  `FCE_Inventory_Wilderness_*` (Get Root/Child/ChildCount/Display — these walk a tree-view style asset browser
  matching this editor's own entity-tree concept), `FCE_ObjectManager_GetObjectsFromScreenRect/MagicWand`,
  `FCE_ObjectSelection_*` (Create/Clear/Add/Toggle/Clone/Delete/Rotate/RotateGimbal/DropToGround/SnapToPivot/
  MoveTo/GetWorldBounds/LoadState/SaveState) — a full multi-select gizmo-driven selection system.
- **Terrain editing tools**: `FCE_Terrain_Bump`, `FCE_Terrain_RaiseLower`, `FCE_Terrain_SetHeight`,
  `FCE_Terrain_Grab_Begin/Grab/Grab_End`, `FCE_Terrain_Smooth`, `FCE_Terrain_Ramp`, `FCE_Terrain_Terrace`,
  `FCE_Terrain_Noise_Begin/Noise/Noise_End`, `FCE_Terrain_Erosion`, each with a `_Begin`/`_End` stroke-session
  pair — this is the in-editor sculpting toolset (brush-stroke begin/update/end pattern), analogous to the
  Avatar-side terrain tool functions. `FCE_TerrainManager_GetHeightAt`, `FCE_TerrainManager_GetTextureEntryFromId/
  AssignTextureId/ClearTextureId`, `FCE_TerrainManager_GetWaterLevel/SetWaterLevel`.
- **Texture/collection painting**: `FCE_Texture_Paint/Paint_End`, `FCE_Texture_PaintConstraints_Begin/End`,
  `FCE_Collection_Paint/Paint_End`, `FCE_CollectionManager_GetCollectionEntryFromId/AssignCollectionId/
  WriteMaskCircle/WriteMaskSquare/ClearMaskId/UpdateCollections` — the mask-painting system for terrain texture
  layers and vegetation/prop "collections", i.e. the FC2 analogue of this editor's texture-painter and
  vegetation-density tools.
- **Spline/road system**: `FCE_Spline_Create/Clear/AddPoint/InsertPoint/RemovePoint/GetPoint/SetPoint/
  RemoveSimilarPoints/OptimizePoint/UpdateSpline/UpdateSplineHeight/FinalizeSpline/Draw/HitTestPoints/
  HitTestSegments`, `FCE_SplineRoad_GetEntry/SetEntry/GetWidth/SetWidth`, `FCE_SplineZone_Reset`,
  `FCE_SplineController_*` (Create/SetSpline/ClearSelection/IsSelected/SetSelected/DeleteSelection/
  MoveSelection/SelectFromScreenRect), `FCE_SplineManager_CreateRoad/DestroyRoad/GetRoadFromId/
  GetPlayableZone` — FC2's road/path spline editor (roads + playable-zone boundary splines).
- **Gizmo/camera/drawing**: `FCE_Gizmo_Create/Destroy/GetActive/SetActive/Redraw/Hide/GetPos/SetPos/GetAxis/
  SetAxis/HitTest`, `FCE_Camera_GetPos/SetPos/GetAngles/SetAngles/Rotate/GetFrontVector/GetRightVector/
  GetUpVector/GetFOV/GetSpeed/SetSpeed/SetSpeedFactor/Input_Forward/Input_Lateral`,
  `FCE_Draw_BeginGroup/EndGroup/Arrow/Dot/SegmentedLineSegment/WireBoxFromBottomZ/ScreenCircleOutlined/
  ScreenRectangleOutlined/Terrain_Circle/Terrain_Square/WireRegionFromTerrain`.
- **Undo/Validation/Misc**: `FCE_UndoManager_Undo/Redo/RecordUndo/CommitUndo/GetUndoCount/GetRedoCount`,
  `FCE_Validation_Game/GameMode`, `FCE_ValidationReport_GetCount/GetRecord`,
  `FCE_ValidationRecord_GetFlags/GetObject/GetMessage`, `FCE_Wilderness_Script/ScriptBuffer/ScriptEntry`,
  `FCE_Script_GetFunction/GetNumFunctions`, `FCE_ScriptFunction_GetName/GetDescription`,
  `FCE_ImageMap_GetSize/ConvertTo24bit/Clone`, `FCE_BudgetManager_GetMemoryUsage/GetObjectUsage`,
  `FCE_Snapshot_Create/Destroy/GetData`, `FCE_Core_GetAnglesFromDir/GetAxisFromAngles/GetAnglesFromAxis/
  Points_Create/Points_Destroy`, `FCE_Brush_Create/Destroy`, `FCE_PhysEntityVector_Destroy`.

### `FCS_*` — Far Cry Server API (~27 functions, `10803120`–`10abb8e0` range)
Multiplayer server/console management: `FCS_Server_Console_Callback`, `FCS_Server_Message_Callback`,
`FCS_Server_GetPlayerStats_{Suicides,Revives,Losses,Xp,Wins}`, `FCS_Server_EnablePunkbuster`,
`FCS_Server_{Create,Delete}ConsoleObserver`, `FCS_Server_ConsoleAutoComplete`, `FCS_Server_ExecuteConsole`,
`FCS_Server_CanCallVote`, `FCS_Server_{Create,Delete}MatchStats`, `FCS_Server_{Create,Delete}PlayerStats`,
`FCS_Server_GetMatchStats_{PlayerId,PlayerScore,PlayerVIP,TeamScore,PlayersCount,PlayerName,PlayerTeam,
TeamsCount,TeamName,Map,Mode}`.

### Networking layer (Ubi.com / GameSpy-style backend SDK, string-literal-identified, not individually labeled)
A large embedded third-party networking SDK is present, identified purely by embedded `.cpp` source-path debug
strings (assert/log messages retain their original file path): `PRUDPEndPoint.cpp`, `BackEndServices.cpp`,
`Tracking.cpp`, `JobCreateAccount.cpp`, `AccountManagementClient.cpp`, `StationURL.cpp`, `UDPTransport.cpp`,
`SecureStream.cpp`, `QueuingSocket.cpp`, `UbiAuthenticationClient.cpp`, `AuthenticationClient.cpp`,
`PrivilegesClient.cpp`, `HTTPClient.cpp`, `TicketManager.cpp`, `IOCompletionNotifier.cpp`, `ZLibCompression.cpp`,
`RC4Encryption.cpp`, `TransportSignatureGenerator.cpp`, etc. This is Ubisoft's online/matchmaking middleware
(account login, secure UDP transport "PRUDP", tracking/telemetry) — not relevant to the level-editor project's
terrain/asset work, so it was **not** swept function-by-function; flagged here so future passes don't waste time
misclassifying it as gameplay code.

---

## Asset Loading (FCB Serialization)

**Major finding**: this DLL contains a complete, self-contained in-memory "property tree" object model that backs
the FCB (`.fcb`) format — a node class (vtable at `PTR_FUN_10e2e180`, ~40-byte/`0x28` instance) with a
name (string+CRC32 hash pair), a dynamic array of typed attribute values (small-buffer-optimized: values
`<=4` bytes stored inline, larger heap-allocated), and a dynamic array of child node pointers. This matches
(and adds concrete implementation detail to) the FCB format already verified against the Avatar-side DLL in
`AGENTS.md` (magic `0x4643626e` 'nbCF', version 2, varint/escaped-size attribute values, CRC-32 name hashing).
All functions below are in the `0x1022_8000`–`0x1024_8xxx` address range, i.e. one contiguous subsystem.

- `FUN_10229400` (line 411447) — **FCB_CRC32_String** — classic reflected CRC-32 (init `0xffffffff`, table
  `DAT_10f95388`, final `~uVar3`) over a NUL-terminated C-string. This is the FCB property-name hash function;
  matches `fcb_names.csv`/`fcb_names_build.py`'s hashing approach used elsewhere in this project.
- `FUN_10229440` (line 411480) — **FCB_CRC32_StringLower** — identical CRC-32 but calls `tolower()` on each byte
  first; the case-insensitive hash variant AGENTS.md's FCB notes mention.
- `FUN_10228380` (line 410544) — **FCB_HashPropertyName** — dispatcher: returns `0xffffffff` for a null/empty
  string, else calls `FUN_10229400` or the case-insensitive `FUN_10229440` depending on a bool flag.
- `FUN_102463e0` (line 432143) — **FCB_ReadEscapedSize** — reads 1 byte; if `>=0xFE` treats it as an escape
  (`0xFE`/`0xFF` sentinel) and reads a following 4-byte real size, else uses the byte itself as the size —
  this is the exact "1-byte attr size with `0xFE`/`0xFF` escape" format AGENTS.md documents for the Avatar-side
  reader; here is the FC2-side twin.
- `FUN_10246200` (line 432047) — **FCB_GetMagicConstant** — returns literal `0x4643626e` ('nbCF').
- `FUN_10246210` (line 432058) — **FCB_GetVersionConstant** — returns literal `2`.
- `FUN_102393b0` (line 422581) — **FCB_ValidateStreamHeader** — reads magic (compares to `0x4643626e`) then a
  2-byte version field (must equal `2`), then 3 more 4-byte fields; returns pass/fail bool. Direct FCB-header
  validator, FC2's equivalent of the Avatar DLL's `FUN_10111af0`.
- `FUN_10246f10` (line 432505) — **FCBNode_FindOrCreateAttribute** — linear-scans the node's attribute array
  (12-byte entries: `[hash:4, size:4, inlineDataOrPtr:4]`) for a matching CRC32 key; inserts a new zeroed slot
  if not found. The core "get-or-add attribute slot by name hash" primitive every attribute setter below calls.
- `FUN_10246260` (line 432089) / `FUN_102462e0` (line 432117) — **FCBAttr_SetRawBytes / FCBAttr_SetRawBytesInPlace**
  — small-buffer-optimized raw byte assign for an attribute value: frees any existing heap block if the old size
  was `>4`, then either `memcpy`s inline (`<=4` bytes) or heap-allocates (`>4` bytes) via the pool allocator.
- `FUN_102470d0` (line 432601) — **FCBAttr_SetString** — `strlen` + `FUN_10246f10` + `FUN_10246260`: sets a
  string-typed attribute value (e.g. entity/collection names, texture paths).
- `FUN_10247170` (line 432644) — **FCBAttr_SetValue8** (8-byte value, e.g. `int64`/`double`).
- `FUN_102471d0` (line 432667) — **FCBAttr_SetValue12** (12-byte value, e.g. `Vector3`).
- `FUN_10247230` (line 432691) / `FUN_102472c0` (line 432719) — **FCBAttr_SetValue16 (variants A/B)** — 16-byte
  value setters (e.g. `Quaternion`/`Vector4`/RGBA color).
- `FUN_10247320` (line 432743) — **FCBAttr_SetValue64** — 64-byte value setter (e.g. a 4x4 transform matrix).
- `FUN_10247a30` (line 433036) — **FCBAttr_SetInt32** — direct (non-SBO-branching) 4-byte value setter; this is
  the one used constantly by the sector/map exporter cluster below (`FUN_10247a30(&key, sectorIndex)` etc.).
- `FUN_10246eb0` (line 432474) — **FCBNode_AddChild** — allocates a new node (heap, `0x28` bytes, sets vtable,
  copies the given name+hash key pair), then `push_back`s it into the parent's children-pointer array
  (via `FUN_10075b80`). Matches the `local_170="SectorDesc"; FUN_10246eb0(&local_170)` call pattern seen in the
  sector exporter (adds a "SectorDesc" child node under the map root).
- `FUN_10246c20` (line 432394) — **FCBNode_ConstructKeyToken (stack, in-place)** — initializes an in-place
  (stack-allocated) node/key object from a `(name-ptr, hash)` pair; the ubiquitous
  `local_x = "SomeName"; local_y = 0x<crc32>; FUN_10246c20(&local_x)` pattern is how this DLL builds property
  keys everywhere — the CRC32 is precomputed at compile time and the original name string is kept only for
  debug/tooling purposes.
- `FUN_102475d0` (line 432798) — **FCBNode_CopyConstructInPlace** — in-place copy-construct of a node from a
  source node's key, then deep-copies attributes/children via `FUN_10246f80`.
- `FUN_10247610` (line 432821) — **FCBNode_CloneNew** — heap-allocated version of the above (`new` + copy).
- `FUN_10246f80` (line 432542) — **FCBNode_DeepCopyAttributesAndChildren** — copies every attribute (respecting
  SBO) and recursively clones every child node (`FUN_102475d0`) into the destination node.
- `FUN_10247c00` (line 433055) — **FCBNode_AddChildClone** — clones a node (`FUN_10247610`) then overwrites its
  key with a caller-supplied name+hash and appends it as a child; used to duplicate a template/prototype subtree
  under a new name.
- `FUN_10246620` (line 432227) — **FCBNode_CountSubtreeNodesRecursive** — `1 + Σ` over children; total node
  count for a subtree (likely used to size the write buffer or progress bar before an FCB export).
- `FUN_10246650` (line 432250) — **FCBNode_DestroyChildrenAndAttributes** — frees any heap-backed (`>4` byte)
  attribute values, then calls the vtable destructor (`vtable[0]`, i.e. `(*)(1)` = "delete this") on every child
  node pointer. Node/tree teardown.
- `FUN_102469f0` (line 432282) — **FCBNode_FindAttributeValue4** — attribute lookup by CRC32 key returning a
  4-dword (16-byte-max) copy (handles both inline and heap-backed storage).
- `FUN_10246ad0` (line 432330) — **FCBNode_FindAttributeValue16** — same lookup but copies a 16-dword (64-byte)
  block — the read-side counterpart of `FCBAttr_SetValue64` (matrix-sized attributes).
- `FUN_10246440` (line 432168) — **FCBNode_WriteRecursive** — the FCB tree **writer**: writes name hash (4
  bytes), attribute count, each attribute's hash+escaped-size+bytes, child count, then recurses into each child.
  This is the low-level stream writer that everything in the "World/Level Document Export" section below feeds.
- `FUN_10247670` (line 432849) — **FCBNode_ReadRecursive** — the FCB tree **reader**: mirror of the writer —
  reads the header/attribute-count/attributes (via `FCB_ReadEscapedSize`) and recurses for `"newchild"` nodes.
  This is the FC2-side deserializer counterpart to the Avatar DLL's known `FUN_10112430`.
- `FUN_10247c60` (line 433074) — **FCBNode_FindChildByHash** (helper wrapping `FUN_10246440`/`FUN_10237410`/
  `FUN_10236d50` — a hash-lookup into the writer's child-name cache) — read with lower confidence, not fully
  traced.
- `FUN_10231ae0` (line 416620) — **OpenFileHandle_Win32** — thin `CreateFile`-style wrapper: maps a small mode
  bitmask (`&1`=read/OPEN_EXISTING, `&0x20`=read+write, `&2`=write/CREATE_ALWAYS or OPEN_ALWAYS combo) to
  Win32 `dwDesiredAccess`/`dwCreationDisposition`, returns a `HANDLE`. Used to open every `.fcb`/`.sdat` file.
- `FUN_10228f30` (line 411201) — **PoolAlloc_SizeClassRounded** — the DLL's general-purpose small-block
  allocator: rounds requested size up to an alignment/size-class boundary, then routes to a fixed-size-class
  pool allocator (`FUN_1023b840`) for blocks `<=0x100` bytes or a fallback general allocator (`FUN_1023baa0`)
  otherwise. Called by nearly every FCB attribute/node allocation above.
- `FUN_10228ad0` — **PoolFree** (freed via consistent pairing with `FUN_10228f30` throughout the FCB code;
  not separately read, but its call sites unambiguously identify it as the matching free/deallocate call).
- `FUN_10248660` (line 433377) — **SafeReleaseObject** — null-checked call through `vtable[0]` (destructor-slot
  convention used with `CThreadInformer*` and similar handle objects across the FCB open/close paths).

### World/Level Document Export (Sector/Map → FCB) cluster
Found via the string literals `"%ssector%d.desc.fcb"`, `"%sworldsector%d.data.fcb"`, `"%s%s.sectorsdep.fcb"` —
this is the in-editor "write the whole level out to disk" pass, almost certainly what `FCE_Document_Export` /
`FCE_Document_FinalizeMap` ultimately call into. Confirms the on-disk sector-grid property naming scheme
(`"Sector"`, `"SectorDesc"`, `"SectorId"`, `"HasMainSectorData"`, `"Flags"`, `"DetailTexMask"` are all FCB
property-key names embedded as literals here) used by this project's own `.fcb`/sector tooling.
- `FUN_107e1cc0` (line 1485671) — **ExportSectorDescFCB** — iterates an 8x8 sector grid (`local_1a8`/`local_1b0`
  0..7, i.e. one region), builds a `"SectorDesc"` FCB node per sector containing `"Sector"`/`"DetailTexMask"`
  attributes plus a `"Flags"` attribute (constant `0x3f`) for every *other* sector in the region (adjacency/
  visibility flags?), then `sprintf`s the path `"%ssector%d.desc.fcb"` and opens/writes it via the
  `CThreadInformer`-guarded open path (`FUN_10231ae0` + `FUN_1024b310`/`FUN_1024bd50`).
- `FUN_107e1ff0` (line 1485815) — **ExportSectorsDepFCB** — builds a `"sectorsDep"` → `"ige_map"` node tree with
  `"SectorId"`/`"HasMainSectorData"` per sector, writes `"%s%s.sectorsdep.fcb"` — the cross-sector dependency
  file (which neighboring sectors must be resident together).
- `FUN_107e22b0` (line 1485930, not read this pass) — next function in the same cluster; by address/position
  almost certainly **ExportWorldSectorDataFCB** (writer for `"%sworldsector%d.data.fcb"`, the actual per-sector
  entity/geometry payload) or a sibling exporter — flagged for a future deeper pass.
- `FUN_1024b310` (line 435864) / `FUN_1024bd50` (line 436382) — **OpenFCBStreamForRead / OpenFCBStreamForWrite**
  (inferred from call-site branching on a "write mode" flag immediately after `FUN_10231ae0`; bodies not fully
  traced this pass).
- `FUN_10249dc0` (line 434717) — **ReportFCBIOError** — called only on failure paths (line/error-code from
  `CThreadInformer::GetLastLine`), forwards to a logging/error-report sink; matches the `this`-based error
  object threaded through every export function above.

---

## Editor API Implementation Bodies (`FUN_*` called directly by named `FCE_*`/`FCS_*` exports)

Methodology: every `FCE_*`/`FCS_*` export in this DLL is a thin thunk (see examples in the "Named Editor API"
section above) whose body is essentially `/* ordinal comment */ FUN_xxxxxxxx(args); return;`. This section was
built by mechanically extracting every such call target across all 339 named exports (a `FUN_*` called by
exactly one export is named `<StrippedExportName>_Impl`; a `FUN_*` called by more than one export — usually a
small allocator, destructor, or a `_Begin`/`_End` stroke-session helper shared across several terrain/paint
tools — is named `Shared_<FirstCallerName>_Helper` and lists every caller). This is **mechanical, high-confidence
call-graph evidence** (not body-reading) — the exact behavior still needs verification for anything beyond "this
is what implements editor feature X", but the *what it's for* mapping is solid since it comes directly from the
DLL's own exported, human-named API surface. 187 unique `FUN_*` addresses were resolved this way.


### Editor Core/Settings (30 functions)

- `FUN_100026e0` (line 1445) — **Engine_GetPersonalPath_Impl** — direct (sole) implementation body called by the exported `FCE_Engine_GetPersonalPath` editor API function.
- `FUN_10002d30` (line 1854) — **Shared_Engine_GetPersonalPath_Helper** — shared helper called by 2 exported API functions: FCE_Engine_GetPersonalPath, FCE_Document_SetMapName.
- `FUN_10124770` (line 211579) — **Engine_GetTimeOfDay_Impl** — direct (sole) implementation body called by the exported `FCE_Engine_GetTimeOfDay` editor API function.
- `FUN_10124bd0` (line 211787) — **Engine_SetTimeOfDay_Impl** — direct (sole) implementation body called by the exported `FCE_Engine_SetTimeOfDay` editor API function.
- `FUN_10298120` (line 494296) — **Editor_ToggleIngame_Impl** — direct (sole) implementation body called by the exported `FCE_Editor_ToggleIngame` editor API function.
- `FUN_10298130` (line 494311) — **Editor_ToggleIngame_Impl** — direct (sole) implementation body called by the exported `FCE_Editor_ToggleIngame` editor API function.
- `FUN_10298140` (line 494326) — **Engine_AutoAcquireInput_Impl** — direct (sole) implementation body called by the exported `FCE_Engine_AutoAcquireInput` editor API function.
- `FUN_103f8ab0` (line 768486) — **Engine_UpdateViewport_Impl** — direct (sole) implementation body called by the exported `FCE_Engine_UpdateViewport` editor API function.
- `FUN_10759ca0` (line 1400008) — **Engine_SetTimeOfDay_Impl** — direct (sole) implementation body called by the exported `FCE_Engine_SetTimeOfDay` editor API function.
- `FUN_10759cc0` (line 1400021) — **Engine_SetStormFactor_Impl** — direct (sole) implementation body called by the exported `FCE_Engine_SetStormFactor` editor API function.
- `FUN_107e5e10` (line 1488534) — **EditorSettings_ShowCollections_Impl** — direct (sole) implementation body called by the exported `FCE_EditorSettings_ShowCollections` editor API function.
- `FUN_107e5e20` (line 1488545) — **EditorSettings_ShowFog_Impl** — direct (sole) implementation body called by the exported `FCE_EditorSettings_ShowFog` editor API function.
- `FUN_107e5e50` (line 1488561) — **EditorSettings_ShowShadow_Impl** — direct (sole) implementation body called by the exported `FCE_EditorSettings_ShowShadow` editor API function.
- `FUN_107e5e80` (line 1488575) — **EditorSettings_ShowWater_Impl** — direct (sole) implementation body called by the exported `FCE_EditorSettings_ShowWater` editor API function.
- `FUN_107e5ea0` (line 1488588) — **EditorSettings_ShowIcons_Impl** — direct (sole) implementation body called by the exported `FCE_EditorSettings_ShowIcons` editor API function.
- `FUN_107e5eb0` (line 1488599) — **EditorSettings_SetSoundEnabled_Impl** — direct (sole) implementation body called by the exported `FCE_EditorSettings_SetSoundEnabled` editor API function.
- `FUN_107e5ee0` (line 1488617) — **Shared_EditorSettings_ShowGrid_Helper** — shared helper called by 2 exported API functions: FCE_EditorSettings_ShowGrid, FCE_EditorSettings_SetGridResolution.
- `FUN_107e5f10` (line 1488634) — **EditorSettings_SetCameraClipTerrain_Impl** — direct (sole) implementation body called by the exported `FCE_EditorSettings_SetCameraClipTerrain` editor API function.
- `FUN_107e5f40` (line 1488658) — **EditorSettings_SetKillDistanceOverride_Impl** — direct (sole) implementation body called by the exported `FCE_EditorSettings_SetKillDistanceOverride` editor API function.
- `FUN_107e66d0` (line 1488791) — **EditorSettings_GetEngineQuality_Impl** — direct (sole) implementation body called by the exported `FCE_EditorSettings_GetEngineQuality` editor API function.
- `FUN_107e66f0` (line 1488803) — **EditorSettings_SetEngineQuality_Impl** — direct (sole) implementation body called by the exported `FCE_EditorSettings_SetEngineQuality` editor API function.
- `FUN_108311c0` (line 1538511) — **Editor_IsLoadPending_Impl** — direct (sole) implementation body called by the exported `FCE_Editor_IsLoadPending` editor API function.
- `FUN_10831a60` (line 1539036) — **Editor_RayCastTerrain_Impl** — direct (sole) implementation body called by the exported `FCE_Editor_RayCastTerrain` editor API function.
- `FUN_10831e00` (line 1539188) — **Editor_RayCastPhysics_Impl** — direct (sole) implementation body called by the exported `FCE_Editor_RayCastPhysics` editor API function.
- `FUN_10831ea0` (line 1539226) — **Editor_RayCastPhysics2_Impl** — direct (sole) implementation body called by the exported `FCE_Editor_RayCastPhysics2` editor API function.
- `FUN_108320c0` (line 1539333) — **Editor_ValidateIngame_Impl** — direct (sole) implementation body called by the exported `FCE_Editor_ValidateIngame` editor API function.
- `FUN_10835bc0` (line 1541807) — **Editor_ToggleIngame_Impl** — direct (sole) implementation body called by the exported `FCE_Editor_ToggleIngame` editor API function.
- `FUN_10837840` (line 1543069) — **Editor_GetScreenPointFromWorldPos_Impl** — direct (sole) implementation body called by the exported `FCE_Editor_GetScreenPointFromWorldPos` editor API function.
- `FUN_108378e0` (line 1543092) — **Editor_GetWorldRayFromScreenPoint_Impl** — direct (sole) implementation body called by the exported `FCE_Editor_GetWorldRayFromScreenPoint` editor API function.
- `FUN_10a2e457` (line 1847339) — **Engine_GetPersonalPath_Impl** — direct (sole) implementation body called by the exported `FCE_Engine_GetPersonalPath` editor API function.

### Math/Utility/Misc Editor (19 functions)

- `FUN_10ea0034` (line line unknown) — **Shared_ImageMap_Clone_Helper** — shared helper called by 2 exported API functions: FCE_ImageMap_Clone, FCE_Brush_Create.
- `FUN_100506f0` (line 58952) — **Core_GetAnglesFromDir_Impl** — direct (sole) implementation body called by the exported `FCE_Core_GetAnglesFromDir` editor API function.
- `FUN_10050990` (line 59080) — **Core_GetAxisFromAngles_Impl** — direct (sole) implementation body called by the exported `FCE_Core_GetAxisFromAngles` editor API function.
- `FUN_1006aee0` (line 78853) — **Core_GetAnglesFromAxis_Impl** — direct (sole) implementation body called by the exported `FCE_Core_GetAnglesFromAxis` editor API function.
- `FUN_10228810` (line 410789) — **Shared_Core_Points_Destroy_Helper** — shared helper called by 3 exported API functions: FCE_Core_Points_Destroy, FCE_PhysEntityVector_Destroy, FCE_Snapshot_Destroy.
- `FUN_10228ad0` (line 410983) — **Shared_Server_DeleteMatchStats_Helper** — shared helper called by 8 exported API functions: FCS_Server_DeleteMatchStats, FCE_ObjectSelection_Destroy, FCE_Gizmo_Destroy, FCE_Brush_Create, FCE_Core_Points_Destroy, FCE_PhysEntityVector_Destroy, FCE_Snapshot_Destroy, FCE_Terrain_Grab_Begin.
- `FUN_10228f30` (line 411201) — **Shared_Server_CreateConsoleObserver_Helper** — shared helper called by 15 exported API functions: FCS_Server_CreateConsoleObserver, FCS_Server_CreatePlayerStats, FCS_Server_CreateMatchStats, FCE_ObjectSelection_Create, FCE_Gizmo_Create, FCE_Validation_Game, FCE_Spline_Create, FCE_SplineController_Create, FCE_Validation_GameMode, FCE_ImageMap_Clone, FCE_Object_Create_FromEntry, FCE_Core_Points_Create, FCE_Brush_Create, FCE_Terrain_Erosion, FCE_Snapshot_Create.
- `FUN_1075cef0` (line 1402040) — **Shared_Brush_Create_Helper** — shared helper called by 2 exported API functions: FCE_Brush_Create, FCE_Terrain_Noise_Begin.
- `FUN_10836f50` (line 1542533) — **BudgetManager_GetMemoryUsage_Impl** — direct (sole) implementation body called by the exported `FCE_BudgetManager_GetMemoryUsage` editor API function.
- `FUN_1088a3d0` (line 1596527) — **Shared_Wilderness_Script_Helper** — shared helper called by 2 exported API functions: FCE_Wilderness_Script, FCE_Wilderness_ScriptEntry.
- `FUN_1088a400` (line 1596544) — **Wilderness_ScriptBuffer_Impl** — direct (sole) implementation body called by the exported `FCE_Wilderness_ScriptBuffer` editor API function.
- `FUN_1088e060` (line 1600660) — **Brush_Create_Impl** — direct (sole) implementation body called by the exported `FCE_Brush_Create` editor API function.
- `FUN_1088e150` (line 1600692) — **Brush_Create_Impl** — direct (sole) implementation body called by the exported `FCE_Brush_Create` editor API function.
- `FUN_1088e310` (line 1600761) — **Brush_Create_Impl** — direct (sole) implementation body called by the exported `FCE_Brush_Create` editor API function.
- `FUN_1088fd70` (line 1602385) — **Brush_Create_Impl** — direct (sole) implementation body called by the exported `FCE_Brush_Create` editor API function.
- `FUN_108e5a90` (line 1650721) — **Brush_Create_Impl** — direct (sole) implementation body called by the exported `FCE_Brush_Create` editor API function.
- `FUN_108e6b80` (line 1651703) — **Brush_Create_Impl** — direct (sole) implementation body called by the exported `FCE_Brush_Create` editor API function.
- `FUN_108e71d0` (line 1651948) — **Brush_Create_Impl** — direct (sole) implementation body called by the exported `FCE_Brush_Create` editor API function.
- `FUN_10cefaa0` (line 2428393) — **Shared_ImageMap_Clone_Helper** — shared helper called by 2 exported API functions: FCE_ImageMap_Clone, FCE_Brush_Create.

### Networking/Multiplayer Server (21 functions)

- `FUN_10002df0` (line 1905) — **Server_ExecuteConsole_Impl** — direct (sole) implementation body called by the exported `FCS_Server_ExecuteConsole` editor API function.
- `FUN_100032e0` (line 2207) — **Shared_Server_CanCallVote_Helper** — shared helper called by 2 exported API functions: FCS_Server_CanCallVote, FCE_Engine_GetPersonalPath.
- `FUN_101b7fa0` (line 321756) — **Server_EnablePunkbuster_Impl** — direct (sole) implementation body called by the exported `FCS_Server_EnablePunkbuster` editor API function.
- `FUN_101b8000` (line 321790) — **Server_EnablePunkbuster_Impl** — direct (sole) implementation body called by the exported `FCS_Server_EnablePunkbuster` editor API function.
- `FUN_101b8060` (line 321818) — **Server_EnablePunkbuster_Impl** — direct (sole) implementation body called by the exported `FCS_Server_EnablePunkbuster` editor API function.
- `FUN_101b9210` (line 322546) — **Server_EnablePunkbuster_Impl** — direct (sole) implementation body called by the exported `FCS_Server_EnablePunkbuster` editor API function.
- `FUN_101b9270` (line 322580) — **Server_EnablePunkbuster_Impl** — direct (sole) implementation body called by the exported `FCS_Server_EnablePunkbuster` editor API function.
- `FUN_101b92c0` (line 322608) — **Server_EnablePunkbuster_Impl** — direct (sole) implementation body called by the exported `FCS_Server_EnablePunkbuster` editor API function.
- `FUN_102295b0` (line 411573) — **Shared_Server_ExecuteConsole_Helper** — shared helper called by 4 exported API functions: FCS_Server_ExecuteConsole, FCS_Server_CanCallVote, FCE_Engine_GetPersonalPath, FCE_Document_SetMapName.
- `FUN_10291f90` (line 489214) — **Server_DeleteConsoleObserver_Impl** — direct (sole) implementation body called by the exported `FCS_Server_DeleteConsoleObserver` editor API function.
- `FUN_10292500` (line 489577) — **Server_CreateConsoleObserver_Impl** — direct (sole) implementation body called by the exported `FCS_Server_CreateConsoleObserver` editor API function.
- `FUN_10293020` (line 490258) — **Server_ConsoleAutoComplete_Impl** — direct (sole) implementation body called by the exported `FCS_Server_ConsoleAutoComplete` editor API function.
- `FUN_10293210` (line 490363) — **Server_ConsoleAutoComplete_Impl** — direct (sole) implementation body called by the exported `FCS_Server_ConsoleAutoComplete` editor API function.
- `FUN_102973c0` (line 493623) — **Server_ExecuteConsole_Impl** — direct (sole) implementation body called by the exported `FCS_Server_ExecuteConsole` editor API function.
- `FUN_104dbb80` (line 931071) — **Shared_Server_CreatePlayerStats_Helper** — shared helper called by 3 exported API functions: FCS_Server_CreatePlayerStats, FCS_Server_CanCallVote, FCS_Server_CreateMatchStats.
- `FUN_107be0a0` (line 1463028) — **Shared_Server_CreatePlayerStats_Helper** — shared helper called by 3 exported API functions: FCS_Server_CreatePlayerStats, FCS_Server_CanCallVote, FCS_Server_CreateMatchStats.
- `FUN_107be7c0` (line 1463209) — **Server_CreatePlayerStats_Impl** — direct (sole) implementation body called by the exported `FCS_Server_CreatePlayerStats` editor API function.
- `FUN_107c1be0` (line 1465205) — **Server_CanCallVote_Impl** — direct (sole) implementation body called by the exported `FCS_Server_CanCallVote` editor API function.
- `FUN_107c3790` (line 1465556) — **Server_CreateMatchStats_Impl** — direct (sole) implementation body called by the exported `FCS_Server_CreateMatchStats` editor API function.
- `FUN_108034d0` (line 1509650) — **Server_DeleteMatchStats_Impl** — direct (sole) implementation body called by the exported `FCS_Server_DeleteMatchStats` editor API function.
- `FUN_108035c0` (line 1509711) — **Server_CreateMatchStats_Impl** — direct (sole) implementation body called by the exported `FCS_Server_CreateMatchStats` editor API function.

### Object/Entity System (56 functions)

- `FUN_10612770` (line 1171372) — **ObjectRenderer_RenderObject_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectRenderer_RenderObject` editor API function.
- `FUN_107ed1e0` (line 1493834) — **ObjectManager_UnfreezeObjects_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectManager_UnfreezeObjects` editor API function.
- `FUN_107ef150` (line 1495297) — **Object_Create_FromEntry_Impl** — direct (sole) implementation body called by the exported `FCE_Object_Create_FromEntry` editor API function.
- `FUN_107efa90` (line 1495786) — **ObjectManager_GetObjectsFromMagicWand_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectManager_GetObjectsFromMagicWand` editor API function.
- `FUN_107f0840` (line 1496264) — **Object_Destroy_Impl** — direct (sole) implementation body called by the exported `FCE_Object_Destroy` editor API function.
- `FUN_107f0920` (line 1496335) — **ObjectManager_GetObjectFromScreenPoint_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectManager_GetObjectFromScreenPoint` editor API function.
- `FUN_107f0e20` (line 1496507) — **ObjectManager_GetObjectsFromScreenRect_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectManager_GetObjectsFromScreenRect` editor API function.
- `FUN_1083c560` (line 1545707) — **Object_IsLoaded_Impl** — direct (sole) implementation body called by the exported `FCE_Object_IsLoaded` editor API function.
- `FUN_1083cac0` (line 1545982) — **Object_GetBounds_Impl** — direct (sole) implementation body called by the exported `FCE_Object_GetBounds` editor API function.
- `FUN_1083cc80` (line 1546067) — **Object_SetVisible_Impl** — direct (sole) implementation body called by the exported `FCE_Object_SetVisible` editor API function.
- `FUN_1083ce70` (line 1546178) — **Object_SetHighlight_Impl** — direct (sole) implementation body called by the exported `FCE_Object_SetHighlight` editor API function.
- `FUN_1083cec0` (line 1546200) — **Object_SetFreeze_Impl** — direct (sole) implementation body called by the exported `FCE_Object_SetFreeze` editor API function.
- `FUN_1083d740` (line 1546719) — **Object_Destroy_Impl** — direct (sole) implementation body called by the exported `FCE_Object_Destroy` editor API function.
- `FUN_1083da50` (line 1546874) — **Shared_Object_Create_FromEntry_Helper** — shared helper called by 2 exported API functions: FCE_Object_Create_FromEntry, FCE_Object_SetPos.
- `FUN_1083db10` (line 1546911) — **Object_SetAngles_Impl** — direct (sole) implementation body called by the exported `FCE_Object_SetAngles` editor API function.
- `FUN_1083e020` (line 1547114) — **Object_ComputeAutoOrientation_Impl** — direct (sole) implementation body called by the exported `FCE_Object_ComputeAutoOrientation` editor API function.
- `FUN_1083e0e0` (line 1547147) — **Object_GetPivot_Impl** — direct (sole) implementation body called by the exported `FCE_Object_GetPivot` editor API function.
- `FUN_1083e210` (line 1547207) — **Object_GetClosestPivot_Impl** — direct (sole) implementation body called by the exported `FCE_Object_GetClosestPivot` editor API function.
- `FUN_1083ec40` (line 1547518) — **Object_SnapToClosestObject_Impl** — direct (sole) implementation body called by the exported `FCE_Object_SnapToClosestObject` editor API function.
- `FUN_1083ee90` (line 1547694) — **Object_Create_FromEntry_Impl** — direct (sole) implementation body called by the exported `FCE_Object_Create_FromEntry` editor API function.
- `FUN_1083f120` (line 1547826) — **Object_GetPhysEntities_Impl** — direct (sole) implementation body called by the exported `FCE_Object_GetPhysEntities` editor API function.
- `FUN_1083f240` (line 1547888) — **Object_DropToGround_Impl** — direct (sole) implementation body called by the exported `FCE_Object_DropToGround` editor API function.
- `FUN_10840a50` (line 1548970) — **Object_Create_FromEntry_Impl** — direct (sole) implementation body called by the exported `FCE_Object_Create_FromEntry` editor API function.
- `FUN_10840ad0` (line 1549000) — **Object_Clone_Impl** — direct (sole) implementation body called by the exported `FCE_Object_Clone` editor API function.
- `FUN_10847360` (line 1552975) — **ObjectSelection_GetPhysEntities_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_GetPhysEntities` editor API function.
- `FUN_10847390` (line 1552995) — **ObjectSelection_LoadState_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_LoadState` editor API function.
- `FUN_108474f0` (line 1553075) — **ObjectSelection_GetWorldBounds_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_GetWorldBounds` editor API function.
- `FUN_10847660` (line 1553164) — **ObjectSelection_MoveTo_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_MoveTo` editor API function.
- `FUN_10847830` (line 1553232) — **ObjectSelection_ClearState_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_ClearState` editor API function.
- `FUN_10847b00` (line 1553445) — **ObjectSelection_Clear_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_Clear` editor API function.
- `FUN_10847be0` (line 1553490) — **ObjectSelection_GetComputeCenter_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_GetComputeCenter` editor API function.
- `FUN_10847c80` (line 1553524) — **ObjectSelection_ComputeCenter_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_ComputeCenter` editor API function.
- `FUN_10847cb0` (line 1553542) — **ObjectSelection_Delete_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_Delete` editor API function.
- `FUN_108480d0` (line 1553816) — **ObjectSelection_Add_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_Add` editor API function.
- `FUN_10848160` (line 1553851) — **ObjectSelection_AddSelection_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_AddSelection` editor API function.
- `FUN_108481d0` (line 1553890) — **ObjectSelection_GetValidObjects_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_GetValidObjects` editor API function.
- `FUN_10848540` (line 1554059) — **ObjectSelection_Rotate_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_Rotate` editor API function.
- `FUN_10848810` (line 1554213) — **ObjectSelection_RotateCenter_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_RotateCenter` editor API function.
- `FUN_10848960` (line 1554304) — **ObjectSelection_RotateLocal3_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_RotateLocal3` editor API function.
- `FUN_108489b0` (line 1554324) — **ObjectSelection_RotateGimbal_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_RotateGimbal` editor API function.
- `FUN_10848a20` (line 1554352) — **ObjectSelection_Clone_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_Clone` editor API function.
- `FUN_10848a80` (line 1554383) — **ObjectSelection_SnapToPivot_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_SnapToPivot` editor API function.
- `FUN_10848ea0` (line 1554498) — **ObjectSelection_SnapToClosestObjects_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_SnapToClosestObjects` editor API function.
- `FUN_108492f0` (line 1554723) — **ObjectSelection_ToggleObject_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_ToggleObject` editor API function.
- `FUN_10849340` (line 1554743) — **ObjectSelection_ToggleSelection_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_ToggleSelection` editor API function.
- `FUN_108493a0` (line 1554776) — **ObjectSelection_RemoveInvalidObjects_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_RemoveInvalidObjects` editor API function.
- `FUN_108493d0` (line 1554797) — **ObjectSelection_Rotate3_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_Rotate3` editor API function.
- `FUN_108495a0` (line 1554907) — **ObjectSelection_SaveState_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_SaveState` editor API function.
- `FUN_108497d0` (line 1555016) — **ObjectSelection_Destroy_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_Destroy` editor API function.
- `FUN_108498f0` (line 1555087) — **ObjectSelection_Create_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_Create` editor API function.
- `FUN_10849980` (line 1555118) — **ObjectSelection_DropToGround_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectSelection_DropToGround` editor API function.
- `FUN_108947d0` (line 1606406) — **ObjectRenderer_SetActive_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectRenderer_SetActive` editor API function.
- `FUN_10894820` (line 1606436) — **ObjectRenderer_Clear_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectRenderer_Clear` editor API function.
- `FUN_108948e0` (line 1606472) — **ObjectRenderer_ClearSnapshot_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectRenderer_ClearSnapshot` editor API function.
- `FUN_10895df0` (line 1607296) — **ObjectViewer_SetObject_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectViewer_SetObject` editor API function.
- `FUN_108960b0` (line 1607405) — **ObjectViewer_SetActive_Impl** — direct (sole) implementation body called by the exported `FCE_ObjectViewer_SetActive` editor API function.

### Rendering/Editor Viewport (19 functions)

- `FUN_1045bb90` (line 843696) — **Draw_EndGroup_Impl** — direct (sole) implementation body called by the exported `FCE_Draw_EndGroup` editor API function.
- `FUN_1045bfe0` (line 843952) — **Draw_BeginGroup_Impl** — direct (sole) implementation body called by the exported `FCE_Draw_BeginGroup` editor API function.
- `FUN_108313b0` (line 1538652) — **Shared_Draw_BeginGroup_Helper** — shared helper called by 2 exported API functions: FCE_Draw_BeginGroup, FCE_Draw_EndGroup.
- `FUN_108313d0` (line 1538665) — **Shared_Draw_ScreenCircleOutlined_Helper** — shared helper called by 9 exported API functions: FCE_Draw_ScreenCircleOutlined, FCE_Draw_ScreenRectangleOutlined, FCE_Draw_Terrain_Circle, FCE_Draw_Terrain_Square, FCE_Draw_WireRegionFromTerrain, FCE_Draw_Arrow, FCE_Draw_Dot, FCE_Draw_SegmentedLineSegment, FCE_Draw_WireBoxFromBottomZ.
- `FUN_10837a10` (line 1543138) — **Shared_Camera_SetPos_Helper** — shared helper called by 3 exported API functions: FCE_Camera_SetPos, FCE_Camera_SetAngles, FCE_Camera_Rotate.
- `FUN_108e8680` (line 1652734) — **Gizmo_Hide_Impl** — direct (sole) implementation body called by the exported `FCE_Gizmo_Hide` editor API function.
- `FUN_108e86a0` (line 1652748) — **Gizmo_Redraw_Impl** — direct (sole) implementation body called by the exported `FCE_Gizmo_Redraw` editor API function.
- `FUN_108e92b0` (line 1653028) — **Gizmo_Create_Impl** — direct (sole) implementation body called by the exported `FCE_Gizmo_Create` editor API function.
- `FUN_108e9320` (line 1653054) — **Gizmo_Destroy_Impl** — direct (sole) implementation body called by the exported `FCE_Gizmo_Destroy` editor API function.
- `FUN_108e9350` (line 1653068) — **Gizmo_HitTest_Impl** — direct (sole) implementation body called by the exported `FCE_Gizmo_HitTest` editor API function.
- `FUN_10d0b500` (line 2450075) — **Draw_ScreenCircleOutlined_Impl** — direct (sole) implementation body called by the exported `FCE_Draw_ScreenCircleOutlined` editor API function.
- `FUN_10d0bf30` (line 2450308) — **Draw_ScreenRectangleOutlined_Impl** — direct (sole) implementation body called by the exported `FCE_Draw_ScreenRectangleOutlined` editor API function.
- `FUN_10d0ce80` (line 2450687) — **Draw_Arrow_Impl** — direct (sole) implementation body called by the exported `FCE_Draw_Arrow` editor API function.
- `FUN_10d0cf60` (line 2450713) — **Draw_Terrain_Circle_Impl** — direct (sole) implementation body called by the exported `FCE_Draw_Terrain_Circle` editor API function.
- `FUN_10d0da40` (line 2451060) — **Draw_Terrain_Square_Impl** — direct (sole) implementation body called by the exported `FCE_Draw_Terrain_Square` editor API function.
- `FUN_10d0e540` (line 2451404) — **Draw_Dot_Impl** — direct (sole) implementation body called by the exported `FCE_Draw_Dot` editor API function.
- `FUN_10d0f0b0` (line 2451697) — **Draw_SegmentedLineSegment_Impl** — direct (sole) implementation body called by the exported `FCE_Draw_SegmentedLineSegment` editor API function.
- `FUN_10d0f1a0` (line 2451719) — **Draw_WireBoxFromBottomZ_Impl** — direct (sole) implementation body called by the exported `FCE_Draw_WireBoxFromBottomZ` editor API function.
- `FUN_10d0f7e0` (line 2451886) — **Draw_WireRegionFromTerrain_Impl** — direct (sole) implementation body called by the exported `FCE_Draw_WireRegionFromTerrain` editor API function.

### Spline/Road (24 functions)

- `FUN_107e67f0` (line 1488879) — **SplineManager_DestroyRoad_Impl** — direct (sole) implementation body called by the exported `FCE_SplineManager_DestroyRoad` editor API function.
- `FUN_107e6900` (line 1488973) — **SplineManager_CreateRoad_Impl** — direct (sole) implementation body called by the exported `FCE_SplineManager_CreateRoad` editor API function.
- `FUN_10840e80` (line 1549028) — **SplineRoad_SetWidth_Impl** — direct (sole) implementation body called by the exported `FCE_SplineRoad_SetWidth` editor API function.
- `FUN_10841610` (line 1549361) — **SplineRoad_SetEntry_Impl** — direct (sole) implementation body called by the exported `FCE_SplineRoad_SetEntry` editor API function.
- `FUN_10843ca0` (line 1550391) — **Spline_SetPoint_Impl** — direct (sole) implementation body called by the exported `FCE_Spline_SetPoint` editor API function.
- `FUN_10843f30` (line 1550536) — **Spline_Clear_Impl** — direct (sole) implementation body called by the exported `FCE_Spline_Clear` editor API function.
- `FUN_10844450` (line 1550738) — **Spline_HitTestPoints_Impl** — direct (sole) implementation body called by the exported `FCE_Spline_HitTestPoints` editor API function.
- `FUN_10844640` (line 1550805) — **SplineController_MoveSelection_Impl** — direct (sole) implementation body called by the exported `FCE_SplineController_MoveSelection` editor API function.
- `FUN_10844970` (line 1550924) — **Spline_Create_Impl** — direct (sole) implementation body called by the exported `FCE_Spline_Create` editor API function.
- `FUN_10844a20` (line 1550961) — **Spline_RemovePoint_Impl** — direct (sole) implementation body called by the exported `FCE_Spline_RemovePoint` editor API function.
- `FUN_10844a80` (line 1550975) — **Spline_RemoveSimilarPoints_Impl** — direct (sole) implementation body called by the exported `FCE_Spline_RemoveSimilarPoints` editor API function.
- `FUN_10844bb0` (line 1551017) — **Spline_OptimizePoint_Impl** — direct (sole) implementation body called by the exported `FCE_Spline_OptimizePoint` editor API function.
- `FUN_10844cb0` (line 1551055) — **Spline_HitTestSegments_Impl** — direct (sole) implementation body called by the exported `FCE_Spline_HitTestSegments` editor API function.
- `FUN_10844e20` (line 1551117) — **SplineController_Create_Impl** — direct (sole) implementation body called by the exported `FCE_SplineController_Create` editor API function.
- `FUN_10844ec0` (line 1551172) — **Spline_AddPoint_Impl** — direct (sole) implementation body called by the exported `FCE_Spline_AddPoint` editor API function.
- `FUN_10844f70` (line 1551211) — **Spline_InsertPoint_Impl** — direct (sole) implementation body called by the exported `FCE_Spline_InsertPoint` editor API function.
- `FUN_10845120` (line 1551310) — **SplineController_SetSpline_Impl** — direct (sole) implementation body called by the exported `FCE_SplineController_SetSpline` editor API function.
- `FUN_10845130` (line 1551324) — **SplineController_ClearSelection_Impl** — direct (sole) implementation body called by the exported `FCE_SplineController_ClearSelection` editor API function.
- `FUN_10845140` (line 1551367) — **SplineController_IsSelected_Impl** — direct (sole) implementation body called by the exported `FCE_SplineController_IsSelected` editor API function.
- `FUN_10845170` (line 1551383) — **SplineController_SetSelected_Impl** — direct (sole) implementation body called by the exported `FCE_SplineController_SetSelected` editor API function.
- `FUN_108451a0` (line 1551401) — **SplineController_SelectFromScreenRect_Impl** — direct (sole) implementation body called by the exported `FCE_SplineController_SelectFromScreenRect` editor API function.
- `FUN_108453f0` (line 1551517) — **SplineController_DeleteSelection_Impl** — direct (sole) implementation body called by the exported `FCE_SplineController_DeleteSelection` editor API function.
- `FUN_10845630` (line 1551620) — **Spline_Draw_Impl** — direct (sole) implementation body called by the exported `FCE_Spline_Draw` editor API function.
- `FUN_10845ac0` (line 1551752) — **SplineZone_Reset_Impl** — direct (sole) implementation body called by the exported `FCE_SplineZone_Reset` editor API function.

### Terrain (22 functions)

- `FUN_10ea0210` (line line unknown) — **Terrain_Erosion_Impl** — direct (sole) implementation body called by the exported `FCE_Terrain_Erosion` editor API function.
- `FUN_10336ab0` (line 626442) — **TerrainManager_GetHeightAt_Impl** — direct (sole) implementation body called by the exported `FCE_TerrainManager_GetHeightAt` editor API function.
- `FUN_1075b490` (line 1400952) — **Terrain_Erosion_Impl** — direct (sole) implementation body called by the exported `FCE_Terrain_Erosion` editor API function.
- `FUN_1075b6a0` (line 1401039) — **Shared_Terrain_RaiseLower_End_Helper** — shared helper called by 6 exported API functions: FCE_Terrain_RaiseLower_End, FCE_Terrain_Terrace_End, FCE_Terrain_Noise_End, FCE_Terrain_Erosion_End, FCE_Texture_PaintConstraints_End, FCE_Terrain_Grab_Begin.
- `FUN_1075c150` (line 1401449) — **TerrainManager_AssignTextureId_Impl** — direct (sole) implementation body called by the exported `FCE_TerrainManager_AssignTextureId` editor API function.
- `FUN_1075fc00` (line 1404089) — **TerrainManager_SetWaterLevel_Impl** — direct (sole) implementation body called by the exported `FCE_TerrainManager_SetWaterLevel` editor API function.
- `FUN_10760550` (line 1404615) — **TerrainManager_ClearTextureId_Impl** — direct (sole) implementation body called by the exported `FCE_TerrainManager_ClearTextureId` editor API function.
- `FUN_10762f30` (line 1406405) — **TerrainManager_AssignTextureId_Impl** — direct (sole) implementation body called by the exported `FCE_TerrainManager_AssignTextureId` editor API function.
- `FUN_1088dbd0` (line 1600417) — **Terrain_Grab_Begin_Impl** — direct (sole) implementation body called by the exported `FCE_Terrain_Grab_Begin` editor API function.
- `FUN_1088f870` (line 1602167) — **Shared_Terrain_Bump_End_Helper** — shared helper called by 7 exported API functions: FCE_Terrain_Bump_End, FCE_Terrain_RaiseLower_End, FCE_Terrain_SetHeight_End, FCE_Terrain_Grab_End, FCE_Terrain_Smooth_End, FCE_Terrain_Terrace_End, FCE_Terrain_Noise_End.
- `FUN_1088f8f0` (line 1602190) — **Terrain_Ramp_Impl** — direct (sole) implementation body called by the exported `FCE_Terrain_Ramp` editor API function.
- `FUN_10892c00` (line 1604850) — **Terrain_Grab_Begin_Impl** — direct (sole) implementation body called by the exported `FCE_Terrain_Grab_Begin` editor API function.
- `FUN_108932e0` (line 1604898) — **Terrain_Bump_Impl** — direct (sole) implementation body called by the exported `FCE_Terrain_Bump` editor API function.
- `FUN_10893390` (line 1604964) — **Terrain_RaiseLower_Impl** — direct (sole) implementation body called by the exported `FCE_Terrain_RaiseLower` editor API function.
- `FUN_10893440` (line 1605030) — **Terrain_SetHeight_Impl** — direct (sole) implementation body called by the exported `FCE_Terrain_SetHeight` editor API function.
- `FUN_108934f0` (line 1605096) — **Terrain_Grab_Begin_Impl** — direct (sole) implementation body called by the exported `FCE_Terrain_Grab_Begin` editor API function.
- `FUN_108935a0` (line 1605162) — **Terrain_Grab_Impl** — direct (sole) implementation body called by the exported `FCE_Terrain_Grab` editor API function.
- `FUN_10893650` (line 1605228) — **Terrain_Smooth_Impl** — direct (sole) implementation body called by the exported `FCE_Terrain_Smooth` editor API function.
- `FUN_10893700` (line 1605294) — **Terrain_Ramp_Impl** — direct (sole) implementation body called by the exported `FCE_Terrain_Ramp` editor API function.
- `FUN_108937d0` (line 1605352) — **Terrain_Terrace_Impl** — direct (sole) implementation body called by the exported `FCE_Terrain_Terrace` editor API function.
- `FUN_108944a0` (line 1606165) — **Terrain_Noise_Impl** — direct (sole) implementation body called by the exported `FCE_Terrain_Noise` editor API function.
- `FUN_108e7d20` (line 1652357) — **Terrain_Erosion_Impl** — direct (sole) implementation body called by the exported `FCE_Terrain_Erosion` editor API function.

### Texture/Collection Painting (13 functions)

- `FUN_10233d20` (line 418391) — **Shared_CollectionManager_AssignCollectionId_Helper** — shared helper called by 2 exported API functions: FCE_CollectionManager_AssignCollectionId, FCE_Brush_Create.
- `FUN_10761b00` (line 1405759) — **CollectionManager_UpdateCollections_Impl** — direct (sole) implementation body called by the exported `FCE_CollectionManager_UpdateCollections` editor API function.
- `FUN_107e8640` (line 1490545) — **CollectionManager_ClearMaskId_Impl** — direct (sole) implementation body called by the exported `FCE_CollectionManager_ClearMaskId` editor API function.
- `FUN_107ead60` (line 1492368) — **CollectionManager_AssignCollectionId_Impl** — direct (sole) implementation body called by the exported `FCE_CollectionManager_AssignCollectionId` editor API function.
- `FUN_107eb460` (line 1492668) — **CollectionManager_UpdateCollections_Impl** — direct (sole) implementation body called by the exported `FCE_CollectionManager_UpdateCollections` editor API function.
- `FUN_107ebed0` (line 1493085) — **CollectionManager_WriteMaskCircle_Impl** — direct (sole) implementation body called by the exported `FCE_CollectionManager_WriteMaskCircle` editor API function.
- `FUN_107ec170` (line 1493206) — **CollectionManager_WriteMaskSquare_Impl** — direct (sole) implementation body called by the exported `FCE_CollectionManager_WriteMaskSquare` editor API function.
- `FUN_107ec370` (line 1493295) — **CollectionManager_AssignCollectionId_Impl** — direct (sole) implementation body called by the exported `FCE_CollectionManager_AssignCollectionId` editor API function.
- `FUN_1088dc80` (line 1600443) — **Collection_Paint_End_Impl** — direct (sole) implementation body called by the exported `FCE_Collection_Paint_End` editor API function.
- `FUN_10890460` (line 1602840) — **Shared_Texture_Paint_End_Helper** — shared helper called by 2 exported API functions: FCE_Texture_Paint_End, FCE_Texture_PaintConstraints_End.
- `FUN_10893880` (line 1605418) — **Collection_Paint_Impl** — direct (sole) implementation body called by the exported `FCE_Collection_Paint` editor API function.
- `FUN_10893930` (line 1605506) — **Texture_Paint_Impl** — direct (sole) implementation body called by the exported `FCE_Texture_Paint` editor API function.
- `FUN_108939e0` (line 1605572) — **Texture_PaintConstraints_Impl** — direct (sole) implementation body called by the exported `FCE_Texture_PaintConstraints` editor API function.

### Undo System (4 functions)

- `FUN_1029bb40` (line 497835) — **UndoManager_RecordUndo_Impl** — direct (sole) implementation body called by the exported `FCE_UndoManager_RecordUndo` editor API function.
- `FUN_107e0090` (line 1484430) — **UndoManager_CommitUndo_Impl** — direct (sole) implementation body called by the exported `FCE_UndoManager_CommitUndo` editor API function.
- `FUN_107e0250` (line 1484538) — **UndoManager_Undo_Impl** — direct (sole) implementation body called by the exported `FCE_UndoManager_Undo` editor API function.
- `FUN_107e03a0` (line 1484606) — **UndoManager_Redo_Impl** — direct (sole) implementation body called by the exported `FCE_UndoManager_Redo` editor API function.

### Validation (8 functions)

- `FUN_107ef270` (line 1495385) — **ValidationRecord_GetObject_Impl** — direct (sole) implementation body called by the exported `FCE_ValidationRecord_GetObject` editor API function.
- `FUN_10838a60` (line 1543627) — **Validation_GameMode_Impl** — direct (sole) implementation body called by the exported `FCE_Validation_GameMode` editor API function.
- `FUN_10838b40` (line 1543672) — **Validation_GameMode_Impl** — direct (sole) implementation body called by the exported `FCE_Validation_GameMode` editor API function.
- `FUN_10838c20` (line 1543719) — **Validation_GameMode_Impl** — direct (sole) implementation body called by the exported `FCE_Validation_GameMode` editor API function.
- `FUN_10838d00` (line 1543766) — **Validation_GameMode_Impl** — direct (sole) implementation body called by the exported `FCE_Validation_GameMode` editor API function.
- `FUN_1083b200` (line 1544892) — **Validation_Game_Impl** — direct (sole) implementation body called by the exported `FCE_Validation_Game` editor API function.
- `FUN_10cdac40` (line 2412135) — **Shared_Validation_Game_Helper** — shared helper called by 2 exported API functions: FCE_Validation_Game, FCE_Validation_GameMode.
- `FUN_10cdde10` (line 2414827) — **Shared_Validation_Game_Helper** — shared helper called by 2 exported API functions: FCE_Validation_Game, FCE_Validation_GameMode.

### World/Level Document (9 functions)

- `FUN_101c1ba0` (line 329801) — **Document_SetMapName_Impl** — direct (sole) implementation body called by the exported `FCE_Document_SetMapName` editor API function.
- `FUN_107e2cf0` (line 1486316) — **Document_Validate_Impl** — direct (sole) implementation body called by the exported `FCE_Document_Validate` editor API function.
- `FUN_107e3e60` (line 1487149) — **Document_SetAuthorName_Impl** — direct (sole) implementation body called by the exported `FCE_Document_SetAuthorName` editor API function.
- `FUN_107e4270` (line 1487321) — **Document_TakeSnapshot_Impl** — direct (sole) implementation body called by the exported `FCE_Document_TakeSnapshot` editor API function.
- `FUN_107e4480` (line 1487414) — **Document_FinalizeMap_Impl** — direct (sole) implementation body called by the exported `FCE_Document_FinalizeMap` editor API function.
- `FUN_107e52f0` (line 1488056) — **Document_Reset_Impl** — direct (sole) implementation body called by the exported `FCE_Document_Reset` editor API function.
- `FUN_10832670` (line 1539616) — **Document_Save_Impl** — direct (sole) implementation body called by the exported `FCE_Document_Save` editor API function.
- `FUN_10833ef0` (line 1540551) — **Document_Load_Impl** — direct (sole) implementation body called by the exported `FCE_Document_Load` editor API function.
- `FUN_10893c10` (line 1605702) — **Document_SetCreatorName_Impl** — direct (sole) implementation body called by the exported `FCE_Document_SetCreatorName` editor API function.

---

## Resource Path / File-ID Hashing (generalizes the FCB CRC32 system to all asset lookups)

Found while tracing an `"ingameeditor\object_icons.xbt"` reference (`Object_Create_FromEntry`-adjacent code,
line 1494100). This is a small, tightly-coupled cluster confirming that the same case-insensitive CRC32
(`FUN_10229440`, see FCB section above) is reused as the general **resource-path-to-ID** hash for the whole
engine, not just FCB attribute names — i.e. `.xbt` texture atlases, `.fcb` files, and any other mounted asset
are all looked up by the CRC32 of their normalized path.
- `FUN_10233b80` (line 418267) — **ResolvePathToResourceId** — normalizes a path (case-folds, converts slashes,
  strips via `FUN_102356d0`), resolves it against a mount/alias table (`FUN_10245640`, returns non-zero if the
  path matched a registered mount point, in which case the matched suffix is used instead of the raw path via
  `FUN_10233b10`), then hashes the final normalized path with the case-insensitive CRC32 (`FUN_10229440`) —
  this is the actual "give me a path, get back a resource ID" entry point used to look up any mounted asset
  (textures, FCBs, etc.) in the resource system.
- `FUN_10233c20` (line 418312) — **ResolvePathToResourceId_CI** — thin forwarder to `FUN_10233b80` (always
  case-insensitive); this is the one called with the literal `"ingameeditor\object_icons.xbt"` path.
- `FUN_10233c40` (line 418323) — **ResolvePathToResourceId_CaseFlag** — same hashing, but takes an explicit
  case-sensitivity flag instead of always normalizing through the mount table.

## Terrain (internals beyond the `FCE_Terrain_*` tool-implementation table above)

- `FUN_10064a20` (line ~211387, called from `FUN_10336ab0`) — **FindTerrainSectorAtWorldPos** — looks up the
  terrain sector object containing a given world `(x, y)`; returns 0/null if outside the loaded terrain.
- `FUN_1036a2d0` (called from `FUN_10336ab0`) — **SampleTerrainHeightBilinear** — takes **sector-local**
  coordinates (world pos minus the sector origin stored at that sector object's `+0x44`/`+0x48` fields) and
  returns an interpolated height; this is the low-level heightmap sampler underneath
  `FCE_TerrainManager_GetHeightAt`/`FCE_Editor_RayCastTerrain`.
- `DAT_1164d594` — (not a function, but worth recording) global pointer to the **singleton `TerrainManager`**
  instance; `+0x68` holds the per-ID texture-entry array (`FCE_TerrainManager_GetTextureEntryFromId` indexes it
  directly: `*(DAT_1164d594 + 0x68 + id*4)`), `+0xd0` holds the current water-level `float`
  (`FCE_TerrainManager_GetWaterLevel` reads it directly). Useful anchor for any future deep dive into FC2's
  terrain/water runtime layout — note this is the **live runtime** object layout, not the on-disk `.sdat`
  layout already reverse-engineered elsewhere in this project.

## Physics/Collision — engine is Havok-based

String evidence only (not function-level, flagged for a future pass): embedded version strings
`"Havok-3.0.0"`, `"Havok-4.0.0-b1"`, `"Havok-5.5.0-r1"` and a debug path
`"...external\havok\Source\Animation\Animation\Animation\hkaSkeletalAnimation.inl"` (~line 2037753-2204867)
confirm Far Cry 2's Dunia engine uses **Havok** for physics and skeletal animation (multiple linked Havok
versions suggests either a staged upgrade across the game's development or separate physics-vs-animation Havok
modules). `FCE_Editor_RayCastPhysics`/`RayCastPhysics2` (`FUN_10831e00`/`FUN_10831ea0`, see table above) are
almost certainly thin wrappers over `hkpWorld::castRay`-style Havok queries. Not swept further this pass.

## Audio

Only 6 `SND_*` named exports were found, all low-level CPU-feature-detection probes for the software audio
mixer, not the mixer itself: `SND_Is_SSE_Supported` (line 1903770), `SND_fn_bTestSnd_Pentium` (1903824),
`SND_fn_bTestSnd_MMX` (1903839), `SND_fn_bTestSnd_WinMM` (1903857), `SND_fn_bTestSnd_Win32` (1903914),
`SND_fn_bTestSnd_WinNT4` (1903933) — CPU/OS capability checks used to pick an audio backend/codepath at startup.
The actual audio subsystem (likely Ubisoft's in-house or a licensed middleware, judging by the `packed_codebooks_
aoTuV_603.bin`/`ww2ogg`/`revorb` OGG-Vorbis tooling already present elsewhere in this project's `tools/` folder)
was not sweepable in the time available — flagged for a future pass.

---

## Summary / coverage assessment

- **Total `FUN_*` functions in the dump**: ~54,700 (regex-counted function-definition headers).
- **Total labeled in this pass**: ~275 unique `FUN_*` addresses given specific names/justifications (grep
  `` `FUN_[0-9a-f]+` `` occurrences in this document for the exact count as it grows in future passes), plus the
  ~339 already-named `FCE_*`/`FCS_*` exports documented for context (not counted toward the `FUN_*` total since
  they weren't unresolved to begin with).
- **Deep coverage**: FCB serialization/property-tree object model (read/write/hash/allocate — essentially the
  whole subsystem), the Editor SDK call-graph (one call-depth resolution for all 339 `FCE_*`/`FCS_*` exports —
  Terrain tools, Object/Selection system, Spline/Road system, Document load/save/export, Undo, Validation,
  Gizmo/Camera/Draw, Texture/Collection painting), and the sector/map FCB export cluster.
- **Shallow / string-evidence-only coverage**: Networking (Ubi.com online SDK — large, clearly out of scope for
  this editor project, intentionally not swept function-by-function), Physics (confirmed Havok-based via version
  strings, no function-level tracing), Audio (only CPU-capability-probe exports found; the actual mixer/decoder
  was not located this pass).
- **Not reached at all this pass**: AI/Scripting (a Lua-like `"Wilderness_Script"` binding system exists —
  `FCE_Wilderness_Script`/`ScriptBuffer`/`ScriptEntry` and `FCE_Script_GetFunction`/`GetNumFunctions` are the
  only entry points found; the underlying Lua VM or script-command dispatch was not traced), general
  Math/Utility (beyond the CRC32/hashing/pool-allocator primitives pulled in by the FCB work), and the bulk of
  Rendering (only the small "editor gizmo/debug-draw" surface reachable from `FCE_Draw_*`/`FCE_Gizmo_*` was
  covered — the actual D3D/shader rendering pipeline is untouched).

## Architectural notes vs. the Avatar-side DLL (per `AGENTS.md`)

- **This DLL retains real exported symbol names** for its Editor SDK (`FCE_*`/`FCS_*`, ~339 functions) and a
  handful of core engine entry points (`InitDuniaEngine`, `TickDuniaEngine`, etc.) — the Avatar-side DLL
  documented in `AGENTS.md` appears to be almost entirely `FUN_*` by contrast (no equivalent `FCE_*`-style table
  was mentioned there). This made the FC2 sweep considerably more tractable: one call-graph hop from a named
  export gives an immediate, high-confidence label, which is not available on the Avatar side.
- **FCB implementation is a concrete, traceable in-memory object model here** (a node class with vtable
  `PTR_FUN_10e2e180`, SBO-optimized attribute storage, recursive read/write) — this fleshes out (with actual
  data-structure detail) the FCB format that was previously verified only via magic/version/varint-pattern
  matching against the Avatar DLL's `FUN_10111af0`/`FUN_10112430`. The CRC32 hashing (plain + case-insensitive
  variants) is confirmed byte-for-byte the same *algorithm* as the assumption already encoded in this project's
  `fcb_names_build.py`.
- **No RTTI class-name strings were found** in this dump (`grep -c '@@'` returns only 12 unrelated C++ mangled
  function names, no `.?AV`-style class descriptors) — unlike what the task brief hoped for as a scouting
  strategy. Class/struct identification here had to come entirely from string literals (`"CTerrain"`,
  `"CSmartTerrain"`, `"CFCXEditorTerrainManager"`, etc. — all found as plain debug-label strings, not RTTI) and
  from the `FCE_*` call-graph instead.
- **Terrain "tool" architecture is a `_Begin`/action/`_End` stroke-session pattern** (e.g.
  `FCE_Terrain_Grab_Begin` → `FCE_Terrain_Grab` (repeatable per-frame) → `FCE_Terrain_Grab_End`, all sharing a
  single `Shared_Terrain_Bump_End_Helper`/`FUN_1088f870` finalize-stroke routine and a
  `Shared_Terrain_RaiseLower_End_Helper`/`FUN_1075b6a0` commit-to-undo routine) — this is a clean, generalized
  brush-stroke framework across all terrain sculpting tools (Bump/RaiseLower/SetHeight/Grab/Smooth/Terrace/
  Noise/Erosion) and the texture/collection painting tools reuse the same `_End` helper
  (`FCE_Texture_PaintConstraints_End` also calls `Shared_Terrain_RaiseLower_End_Helper`). Whether the Avatar
  engine shares this exact `_Begin`/action/`_End` shape for its terrain tools was not previously documented in
  `AGENTS.md` and would be a good cross-check for whoever runs the parallel Avatar-side labeling pass.
- **Engine confirmed to use Havok physics/animation** (version strings for 3.0.0/4.0.0-b1/5.5.0-r1) — this
  wasn't previously documented for either DLL in `AGENTS.md` and is useful context if collision/ragdoll data in
  `.fcb`/entity files ever needs interpreting.
- **Resource lookup is uniformly CRC32-hash-of-normalized-path** across FCB properties *and* general asset
  paths (`.xbt` atlases confirmed via the `ingameeditor\object_icons.xbt` trace) — i.e. this project's existing
  `fcb_names.csv`/CRC32 approach is validated as the right general-purpose hashing strategy for FC2 asset IDs
  too, not just FCB property names.

---
