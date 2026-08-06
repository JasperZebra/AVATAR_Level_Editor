# CONSOLE_AUDIT — `DevAccess/console_dll/avatar_console.c`

A read-through audit of the injected console DLL for *James Cameron's Avatar: The
Game* (PC retail 1.02, Dunia). Covers the whole file: the top-level console
commands, the editor-link verbs, the hotkeys, the per-frame detour, the D3D
overlay, the input thread and the picker window.

**The game was not run.** Every finding here was derived by reading, and every
fix was proved only by the compiler. §7 is the runtime test plan, and §6 is the
list of things that cannot be settled any other way. Where a claim is inference
rather than evidence, it says so.

> **⚠ FRESHNESS — re-verified 2026-08-04. Three counts in this document have
> moved on, and one warning is no longer true.**
>
> | Claim as written | State on 2026-08-04 | Where |
> |---|---|---|
> | "68 top-level console commands" | **78 dispatch arms** (77 completable — `check_cmds.py` discards `?` and adds `warp`). `players` and `admin_gui` added 2026-08-05. | §1.1 |
> | "8 editor-link verbs" | **11** — `bones`, `addr` and `cvar` were added after this was written | §1.2 |
> | "16,263 lines" (in `CONSOLE_INPUT_BUG.md`) | **19,615 lines** | — |
> | **"the shipped `avatar_console.dll` is STALE"** | **FALSE now.** The DLL links at 2026-08-04 14:43 UTC against a source last touched 07:42 local — the binary is current. `check_cmds.py` passes (75/75), `dist\avatar_console.dll` and `dist\dinput8.dll` are byte-identical (md5 `a44d4d35e81c01937a6e27c8b030c442`), machine `0x014C` (x86), image base `0x2A000000`. | §9.3 |
>
> **Do not act on the STALE warning below.** It described a real condition on the
> day it was written — the game held the DLL and `LNK1104` blocked the link — and
> that condition has since been cleared. §9.3 is kept for the method, not the
> state. The counts are corrected in place in §1.1 and §1.2.
>
> Everything else in this document was spot-checked and still holds. In
> particular the fix in `CONSOLE_INPUT_BUG.md` **is** present in the current
> source (the stale-`GetAsyncKeyState`-bit drain runs at both the console-open
> and picker-open edges), and the `+0x38` and Scaleform-health-bar negative
> results stand.

---

## 1. Command inventory

### 1.1 Top-level console commands (78 dispatch arms — was 68 when written)

Order is dispatch order in `TryModCommand`. `E` = consumed by the editor,
`D` = described in `DevAccess/*.md`, `K` = also reachable from a hotkey.

**Five commands were added after this table and are appended at the end of it**
(`picktrace`, `speedinfo`, `driveturn`, `drivelock`, `mkpawn`). Verified
2026-08-04 by diffing the `_stricmp`/`_strnicmp` arms of `TryModCommand` against
this table: no other drift in either direction.

| Command | Args | What it does | Class |
|---|---|---|---|
| `modhelp` | — | Print the DLL's own command list (`?` only knows engine commands) | D |
| `?` | — | Run the engine's `?`, then append `modhelp` | D |
| `fixinput` | — | Rebuild the input mapper and reload action-map bindings | D |
| `editorlink` | `[on\|off]` | Status of / switch for the named-pipe link to the GUI editor | **E** D |
| `ingame` | — | Toggle drawing the console inside the game's frame vs. an overlay window | — |
| `fixcam` | — | Put the active camera back on the player pawn | D |
| `save` | `[force]` | Ask the game to autosave; refuses after a warp unless forced | D |
| `planets` | — | Dump the sky-planet registry | D |
| `mountinfo` | — | Is the last spawned/selected thing rideable? | D |
| `beastinfo` | — | Can this creature be driven — does it carry a `CAIComponent`? | — |
| `drive` | — | Take over the selected creature: velocity hook, chase camera, key bindings | D |
| `anchor` | `[on\|off]` | Who anchors sector streaming, and is the ground under you resident | D |
| `aisignal` | `<name>` | Send exactly one raw AI signal — no unlock, no follow-up | D |
| `attack` | `[signal]` | Send an attack signal **through the unlock gate**, like a number key | D |
| `drivesignal` | `<name>` | Which signal left mouse sends while driving | D |
| `facinginfo` | — | Read-only dump of the driven creature's focus/facing state | D |
| `agentinfo` | — | What steers the selection, and can we take it over | — |
| `vehinfo` | — | Does the selected vehicle actually have seats | D |
| `rcprobe` | `[range] [flags]` | Cast a physics ray from the camera and report the hit | D |
| `facing` | `[probe\|off]` | Suppress (or just watch) the driven creature turning to face you | D |
| `driveai` | — | Toggle muting the driven creature's own signal requests | D |
| `drivecalm` | — | Toggle suspending its combat behaviour | D |
| `drivespeed` | `[n]` | Walk speed while driving | — |
| `drivecam` | `[h] [d]` | Chase-camera height and distance | — |
| `fixplayer` | `[force]` | Diagnose (and with `force`, repair) a stale player list after a warp | — |
| `streaming` | — | Read the dynamic-load kill switch — the byte that explains "AI but no mesh" | D |
| `drivewait` | `[ms]` | Gap between an unlock signal and the signal it unlocks | — |
| `resurrect` / `revive` | `[name]` | Put health back on a body through the sheet's own setter | D |
| `playerinfo` | — | Is the pawn alive, and can `respawn` run | D |
| `actmap` | — | What action maps are pushed on the player | D |
| `pick` | — | Select whatever the crosshair points at | D K |
| `pickfov` | `[deg]` | Tune cursor-picking FOV | — |
| `pickclick` | — | Toggle click-to-pick while the console is open | — |
| `kill` | — | Kill the selection, and say so if it refuses | D |
| `entbox` | — | Does the selection have a bounding box (read-only) | D |
| `ents` | — | Open the live-entity browser window | **E** D |
| `respawn` | `[x y z]` | Give the player a new body via `CPlayer::Spawn` | D |
| `allsectors` | `[n\|off]` | Raise the streaming radii; honest about being unproven | — |
| `timescale` | `<0..10>` | Time-manager scale — 1 normal, 0.25 slow, 0 stopped | D |
| `freeze` | — | Toggle time scale 0 while rendering and the console keep running | D |
| `spawnground` | — | Toggle sitting spawns on the floor vs. dropping them | — |
| `drivebind` | `[1-9] [sig]` | Bind a signal to a number key; bare form lists the pages | — |
| `attackhold` | `[ms]` | How long the creature's own movement wins after an attack | — |
| `delete` / `despawn` | — | Destroy the selection outright, components and all | D |
| `entlist` | `[text]` | List live entities — id, class, name, position | D |
| `animinfo` | — | Is the animation dependency graph still alive | D |
| `pawntype` | — | Switch between Avatar and RDA body (link-bed swap) | D |
| `entflag` | `[set\|clear <hex>\|undo]` | Read/poke the pawn's flag word at `entity+0x90` | — |
| `gamelog` | `[off]` | Mirror the engine's own console output to a file | — |
| `fixcontrol` | `[undo]` | Re-point the player object at its pawn | D |
| `trace` | `[now\|fast\|off]` | Log every resolvable pointer and every byte that changes | D |
| `vehenter` | `[seat]` | Board the selection — 1 driver (default), 3 passenger | D |
| `vehexit` | — | Get out | D |
| `vehstatus` | — | What am I in | D |
| `camspeed` | `[n]` | Free-camera speed | D K |
| `firstperson` | — | Toggle the game's own first-person camera | D |
| `verbose` | `[off]` | Mirror internal log lines into the console panel | D K |
| `fpdiag` | — | First-person diagnostic dump | — |
| `fpbody` | — | First-person body-visibility report | — |
| `fpaim` | `[off\|lookat\|body\|look\|yaw <d>\|pitch\|<n>]` | First-person aim coupling mode | D |
| `fpfov` | `[deg]` | First-person field of view (5..170) | — |
| `fpoffset` | `[x y z]` | Nudge the first-person camera off its bone | D |
| `freecam` | `[1]` | Detached camera; `1` makes sectors follow the camera | D K |
| `spawn_all` | — | Merge the full archetype library into this level | D |
| `mergelib` | `[!] <path>` | Merge one entity library (game-relative path) into the live table | — |
| `spawn_list` | `[text]` | Search what THIS level can spawn (live table) | D |
| `spawn` | `[!] [arch]` | Create an entity in front of you; bare form opens the search box | **E** D |
| `tp` | `[x y z]` | Move the player there, or to the active camera | D |
| `warp` | `<world>\|list\|?` | Change world through the engine's own loader | D |

**Added after this table was written (2026-08-04 verification):**

| Command | Args | What it does | Class |
|---|---|---|---|
| `picktrace` | `[off]` | One log line per click: raw screen position, backbuffer position, panel-local position, and the region it resolved to | — |
| `speedinfo` | — | Report the movement-speed literals found near the player speed code | — |
| `driveturn` | `[clamp] [v]` | Probe/clamp the driven creature's turn controller | — |
| `drivelock` | `[off\|last\|aim\|soft\|hard]` | How much of the driven creature's brain to stop — the `FACING.md` lever ladder (§12.6) | D |
| `mkpawn` | — | Build a pawn at a picked spawn point | — |

### 1.2 Editor-link verbs (`\\.\pipe\avatar_editor`, served on the main thread)

**11 verbs** (was 8 when this was written — `bones`, `addr` and `cvar` came
later). Consumed by `Editor/avedit_gui/live.py`, `linkworker.py` and
`Editor/tools/livelink.py`. **None of them was touched by this audit.**

Protocol: request is one plain-text line `verb arg arg…\n`; response is one or
more JSON Lines, always terminated by a line carrying `"end"`. One request
produces exactly one block, so a client reads until `end` and never guesses.
The pipe thread parses and transports only — every engine read and write happens
on the main thread in `LinkTick`.

| Verb | Args | Reply |
|---|---|---|
| `hello` / `ping` | — | proto, DLL build stamp, pid, world, frame, current selection |
| `list` | `[cap]` | one JSON line per entity: id, name, class, position |
| `listx` | `[cap]` | `list` plus the transform's forward row and the world AABB |
| `poslist` | `[cap]` | the hot path: one header line, then `HI:LO x y z` — not JSON, on purpose |
| `bones` | `<HI:LO>[,…]\|sel [A\|B]` | per entity, one `{"i","h","m":[16 floats]}` per bone, then `stat` and `end` |
| `addr` | — | publishes each entity's graphic-component **pointers** and decodes nothing, so the client explores with `ReadProcessMemory` instead of a DLL rebuild per guess |
| `cvar` | `<name> <value>` | **writes.** Sets one engine CVar through `CConsole::ExecuteLine` |
| `player` | — | player name, world, position and the three transform rows |
| `get` | `<HI:LO>` | that entity's current position |
| `select` | `<HI:LO>` | mirror the DLL's own selection, so `kill`/`delete`/`drive` agree |
| `move` | `<HI:LO> <x> <y> <z>` | move it, then read the transform back and report whether it took |

**`cvar` is deliberately not an `exec` verb**, and its own comment says why: an
`exec` would let anything through the pipe including level loads and quit. The
name must be a bare identifier and the value a number, so a second command
cannot be smuggled in behind either. Any client wanting a broader surface should
add a **named, individually-validated verb**, not relax this one.

### 1.3 Hotkeys

`F1` verbose echo · `F6` driving panel · `F7` overlay window · `F8` noclip
(`PgUp`/`PgDn` speed) · `F9` console (`Shift+F9` block game input while typing) ·
`F10` dump scrollback + refresh Tab list · `F11` run `console_cmds.txt` ·
`F12` smoke test · `Pause` panic (close + free cursor) · `End` unload.

While flying: `WASD` along the camera, `Space` up, `LCtrl` down.
While driving: `WASD` steer, `E`/`Q` up/down, `Shift` sprint, `Ctrl` slow,
`LMB` attack, `1`–`9` signals, `0` page, `=`/`-` camera distance, `[`/`]` camera
height. Console open: left-click picks, right-click cycles.

---

## 2. Classification

**Load-bearing for the editor (do not touch):** the eight link verbs, `ents`,
`spawn`, `editorlink`. Breaking any of these breaks the level editor, which is
the main product.

**Documented across the `DevAccess/*.md` files:** 38 of the 70 dispatch names
(68 commands plus the `revive` and `despawn` aliases) appear as an explicit
`` `command` `` reference in some other document. A documented command is not a
dead one even if nothing in `Editor/` calls it. The 32 that no document names are
overwhelmingly the tuning knobs and diagnostics listed below — not a list of
candidates for deletion.

**Experimental but live** — implemented, honest about their own uncertainty in
the text they print, undocumented elsewhere: `allsectors`, `facing`, `drivecalm`,
`entflag`, `fpaim`, `streaming`, `fixplayer`. These are the ones whose console
output says outright that the mechanism is unproven. That is the right shape;
leave them.

**Tuning knobs of a live feature** (not independently useful, not dead):
`drivespeed`, `drivecam`, `drivewait`, `drivebind`, `attackhold`, `camspeed`,
`pickfov`, `pickclick`, `spawnground`, `fpfov`, `fpoffset`.

**Demonstrably dead — and I could prove it, so it is gone:** see §4.3. Nothing
in the *command* set was dead. The dead code was all state and helpers.

**Broken, found and fixed:** `drivecam` (advertised in three places, dispatched
in none), `grab` (advertised in `modhelp`, implemented nowhere at all),
`entflag undo` (the block promised reversibility and had no restore path).

**Never advertised, so nobody could find them:** eleven implemented commands were
in neither Tab-completion list — `editorlink`, `agentinfo`, `vehinfo`, `facing`,
`facinginfo`, `driveai`, `rcprobe`, `respawn`, `resurrect`, `revive`, `mergelib`.
Fixed.

---

## 3. Bugs, ranked

Severity is about consequence, not about how hard it was to find.
**F** = fixed in this pass. **R** = reported only, see §5 for why.

### 3.1 Crash on unload — the class this project keeps paying for

A fault after `FreeLibrary` happens with the crash reporter already removed and
the DLL unmapped, so the log ends with a clean `---- detached ----` and the game
dies a frame later with nothing recorded. All five of these are that.

1. **F — `RemovePresentHook` nulled `g_rdPresent` before the `Sleep(120)` that
   exists to protect it.** `hkRDPresent` ends with an unconditional
   `((fnRDPresent)g_rdPresent)(self, hwnd)`. A render thread already inside the
   hook read the pointer after we zeroed it and called address 0. The sleep was
   one line too late to cover the very store it was guarding.
2. **F — `VerifyUnhooked`'s Present repair could never run.** It tests
   `if (g_rdPresent && ...)`, and `RemoveHook → RemovePresentHook` has already
   zeroed that by the time the sweep executes. It logged *"Present slot STILL
   ours — restoring"* and restored nothing — worse than a no-op, because the log
   claimed the opposite. Added `g_rdPresentEver`, saved at install, never cleared.
3. **F — the overlay thread freed `g_snap` and deleted `g_snapCs` while the
   Present hook was still installed.** `RemoveHook` runs long after the join, so
   every frame in between could enter the hook, pass the unsynchronised
   `if (!g_snapReady || !g_snap)`, and reach `EnterCriticalSection` on a deleted
   CS and a `memcpy` from freed memory. The console path was closed by the
   `g_ourPanel` clear, but the draw gate is `(g_ourPanel || (g_drive && g_hudOn))`
   — pressing `End` while **driving with the HUD on** walked straight into it.
   The hook now comes off before the join.
4. **F — the vtable sweep checked one slot on one vtable.** We patch three
   (`+0x128` velocity, `+0x148` signal, `+0x208` Update) across however many
   species vtables a session drives. `g_vtPatch[]` exists precisely so that
   number stops mattering, and then the safety net backing it up did not use it.
5. **F — `FirstPersonLookTick`'s exception handler zeroed `g_fpLookComp`.**
   `g_fpLookOn` and `g_fpLookComp` are the only record that a pointer to
   `g_fpLookArr` — DLL static memory — is sitting in an engine camera component.
   The unload sweep's test is literally `if (g_fpLookOn || g_fpLookComp)`, and
   `FirstPersonLookDetach` reads `g_fpLookComp` first thing. One faulting tick
   made the leak invisible to both. The address is kept now; the handler still
   writes no engine memory.
6. **F — `FirstPersonAimPatch(0)` cleared `g_fpAimOn` outside its
   `if (VirtualProtect(...))`.** A failed restore left our byte patched into
   Dunia's `.text` with the flag saying otherwise — and that flag is the sweep's
   only test. Now it fails loudly and leaves the flag set so the sweep retries.

### 3.2 Null calls into removed hooks

7. **F — all three AI hooks tail-called their saved original with no null
   check.** `DriveStop` runs from the console thread (this file establishes that
   is *not* the game thread) and nulls those globals; any restore that declined
   leaves the slot live with nothing behind it, and the next AI tick calls
   address 0. `g_faceOrig` is the worst of the three: it is **one** global while
   `+0x208` is genuinely per-species and `VtPatch` hooks several vtables — so a
   drive across two species also runs species A's agents through species B's
   `Update`. The null guard is fixed; **the wrong-function half is R** and needs
   a per-vtable original.

### 3.3 Wrong results

8. **F — the entity browser went blank whenever the editor polled.** `poslist`
   calls `EntSnapshotEx(0)`, which fills the **shared** `g_entRows` and blanks
   every name; `PickerRefill` skips rows with an empty name. Two features, one
   buffer, no flag saying who wrote it last. Added `g_entMetaValid`; the browser
   now keeps what is on screen and asks the main thread for a snapshot with
   names.
9. **F — `DeleteSelected` left `g_lastSpawn` pointing at the destroyed entity.**
   It cleared it only `if (!Readable(g_lastSpawn, 0x100))`, and this file states
   four separate times that `Readable` is not a liveness test — a freed heap
   block stays mapped. `PickSelect` sets `g_lastSpawn` unconditionally, so after
   any pick-then-delete `g_lastSpawn` *was* the dead entity and `Readable` said
   yes. `agentinfo`, `vehinfo`, `mountinfo`, `anchor on`, `drive` and `vehenter`
   all take it. Now compared by identity.
10. **F — `drivebind` left `g_driveAct[idx]` holding the previous species'
    action**, so binding over a slot that used to be a "combat" entry made that
    number key toggle combat instead of sending the signal. It also promoted the
    gap between the old count and the new index into the live list, carrying the
    previous species' signal names under the number keys.
11. **F — `DriveCamTick` followed `g_lastSpawn`, not `g_driveEnt`.** The file
    names this exact defect twice elsewhere. Clicking anything while driving made
    the chase camera orbit it — and worse, it kept reading the entity through a
    streaming freeze, after `DriveHoldPlayer` had deliberately dropped that
    pointer because the streamer may free it at any time.
12. **F — the noclip sanity guard tested `g_flyAcc` and printed `g_flyPos`**,
    which still held the last *good* value. The one line that had to show the bad
    numbers showed three valid ones, every time it fired.
13. **F — `PickSelect`'s truncation guard could not fire.** MSVC's `_snprintf`
    returns `-1` on truncation, so `used += _snprintf(...); if (used < 0) break;`
    decremented `used` by one and carried on writing at nearly the same offset,
    silently dropping candidate names.
14. **R — `DriveHoldPlayer`'s runaway/freeze/recovery chain is gated on
    `g_velSeen`, which only the velocity *hook* sets.** `DrivePush` steers every
    frame without the AI asking — the case the comments say is now normal — so
    for a calm creature `g_velSeen` stays 0 and none of the entity-gone
    detection, the sector freeze, or the id64 recovery ever runs. That is exactly
    the runaway the block exists to prevent. **Not fixed: it is a behavioural
    change to the drive safety net and wants a runtime session, not a guess.**
15. **R — `SigClipVerdict` mis-reports for any decorated archetype leaf.** It
    treats `species` as the needle in a pipe-list, while `DriveSigBuild` treats it
    as the haystack; `SpeciesKeyFor` only normalises three species, so e.g.
    `Thanator_Pet` falls through to "has NO branch for this species" for a signal
    that works. Log-only.

### 3.4 Guards that did not guard

16. **F — `GetPlayerObject` loaded the player list in its declaration and checked
    the slot on the next line**, making the guard dead as written.
17. **F — `RebuildInputMapper` read `*(void***)old` behind only `if (old)`.**
    Reading a pointer's vtable is a dereference; `Readable` exists because a guard
    that reads through an unvalidated pointer faults in the guard.
18. **F — `FreecamEnter` dereferenced `camStack+OFF_CS_LOCKED` with no
    `Readable`**, at the exact spot where its twin `FirstPersonEnter` has one and
    explains why (*"the stack can be mid-teardown and this deref lands in freed
    memory"*).
19. **R — `GetPlayerElem` and `GetPlayerObject` still read only `data[0]`.**
    `GetPlayerEntity` was fixed to walk every entry precisely because *"the live
    local player need not still be the first entry"* after a second `LoadWorld`.
    The two shallower resolvers never were, and `freecam`, `firstperson`,
    `respawn` and `playerinfo` all route through them.
20. **R — eight engine globals are dereferenced without `Readable` on the slot
    itself** (`ForEachPlayerInput`, `WorldName`, `ArchManager`, `GeneratedDir`,
    `GetPlayerElem`, `RestorePawnCamera`, `FirstPersonSetFlag`, `TraceSnapshot`).
    Low impact — those slots live in Dunia's always-mapped `.data` — but
    `FirstPersonSetFlag` is the one not inside a `__try`.

### 3.5 Buffers

21. **F — `QueuePop` copied a full `QLEN` with no terminator** while its twin
    `LogEchoPop` does `LEN-1` plus an explicit NUL. In bounds only by coincidence
    of the one caller's buffer size.
22. **F — three `_snprintf(path, sizeof(path), ...)` results were passed straight
    to `fopen`.** `_snprintf` does not terminate on truncation; siblings in the
    same file already use `sizeof-1` plus an explicit NUL.
23. **R — `g_cmds`/`g_cmdCount` are mutated from two threads with no lock.** The
    cap test and the write are separate, so two threads both seeing
    `g_cmdCount == CMDMAX-1` both pass and one writes `g_cmds[CMDMAX]` — one
    64-byte entry past a `char[1600][64]`. Needs a large `console_dump.txt` and a
    real race (F10 on the hotkey thread against Tab on the input thread) to reach.
24. **R — `InSubmit`'s two history branches are asymmetric**: the `< HISTN`
    branch forces a NUL, the wrap branch does not. Not reachable today because
    `InKey` caps the line below the buffer, but it is a copy-paste asymmetry that
    becomes real the moment that cap changes.
25. **R — `DriveHudLines` guards `if (max < 6)` and then writes seven rows
    unconditionally.** Cannot fire — the only caller passes 24 — but the guard is
    wrong as written.
26. **R — `ActMapInfo` prints an unvalidated engine dword as `%s`** after proving
    exactly one byte readable and testing it for printable ASCII. That is a
    heuristic, not a bound.
27. **R — `LnkEntLine`'s `cb[64]` versus a worst-case escaped 40-char class
    string (234 bytes).** Safe only because `LnkEsc` truncates, not because the
    buffer is big enough. `nb[ENT_NLEN*6]` *does* hold, with 5 bytes spare.

### 3.6 Leaks

28. **F — `PkEnsureGdi` had no counterpart at all.** A DC, a 540×580 DIB section,
    a 1.25 MB heap buffer, two fonts, two brushes and the picker's D3D texture
    were created once per injection and destroyed nowhere; `g_pkOldB` was saved by
    `SelectObject` and never used to restore the DC. Added `PkFreeGdi`, font and
    brush deletion (handling the `g_fontHd == g_fontUI` alias and the stock-object
    case), the buffer freed in `Worker` after the hook is off and the thread
    joined, and `ReleasePickerTexture()` in `RemovePresentHook`.
29. **R — `DrawOverlayD3D` saves and restores render states, shaders, FVF,
    declaration and texture, but not the four `D3DTSS_*` or the four
    `D3DSAMP_*` it sets.** Sampler states apply to programmable pixel shaders too,
    so from our first overlay draw onward the game's texture stage 0 is
    point-filtered and clamped. Whether that is *visible* needs a runtime look;
    the missing save/restore is not in doubt.
30. **R — a failed picker `CreateTexture` is retried every single frame.** The
    adjacent console path gets this right (`InterlockedExchange(&g_ingame, 0)`
    with the comment *"do not retry every frame"*); the picker block, otherwise
    parallel, has no such guard.

### 3.7 Unreachable code

31. **F — two branches in the per-frame detour could never run**: the "stage 4"
    `SetUIActive(1)` call and the panel-geometry watch, gated on `g_wantUI` and
    `g_watch`, neither of which anything ever set.
32. **R — `NoclipTick`'s documented fallback is unreachable.** It is guarded by
    `if (Readable(FN_ENT_SETPOS, 8)) { ...; return; }`, and that address is inside
    Dunia's mapped `.text`, so the test is always true. The comment says the raw-
    write path is *"kept as a fallback rather than deleted: it is what has been
    shipping and it does work"* — describing code that cannot execute. This also
    makes `FN_SETDIRTY` and the two-proxy physics sync effectively dead.
33. **R — `DriveKeysToVel` returns 1 on every path**, so both
    `if (!DriveKeysToVel(mine))` branches are unreachable and its doc comment
    (*"returns 0 only when the creature should be left to its own devices"*) is
    stale — that check moved into the callers.
34. **R — the picker window is never shown.** All three `ShowWindow(g_pickWnd, …)`
    calls pass `SW_HIDE`, deliberately. A never-shown window gets no `WM_PAINT`,
    no mouse and no keyboard, so most of `PickerProc` — including its ~85-line
    hand-painted panel — is dead, along with `PickerBarRect`, `PickerScrollBy`,
    `FillRound` and the two subclass procs. **This is a large, coherent block and
    deleting it is the owner's call, not mine.**
35. **F — the whole `OutputDebugStringA` capture was never wired up.**
    `InstallDebugStringHook` and `RemoveDebugStringHook` had zero call sites, so
    `avatar_debug.log` was never written and Scaleform GFx's log — ActionScript,
    font, image and SWF errors — plus Dunia's fatal path went uncaptured. It was
    a complete, working feature that nobody switched on. **Now switched on** —
    see §9.2.

### 3.8 Races

36. **R — the picker snapshot has no lock at all**, while the console snapshot
    right beside it has `g_snapCs` on both sides and a comment block titled *"THE
    TEAR"* explaining why. Same 1.25 MB `memcpy`, same two threads, unfixed. Also
    `g_pkSnapReady` is a plain `static int` where the console's `g_snapReady` is
    `volatile long` written with `InterlockedExchange`.
37. **R — `PickerAct` can act on the wrong entity.** It captures `g_pkcSel`,
    indexes `g_pkcData` to get an index into `g_entRows`, and the *main* thread
    refills `g_entRows` independently. A selection captured before a refill names
    a different entity after it — and one of the actions is DELETE. Memory-safe
    (the `g_entCount` bound holds); semantically wrong.
38. **R — `PkDrag` puts a full memory barrier *between* the two halves of a
    coordinate pair**, which actively guarantees the render thread can observe the
    new X with the old Y. Cosmetic; obviously a misplaced line.
39. **R — `SetFocus`/`SetForegroundWindow` are called cross-thread** from
    `PickerHide` (reached from the input thread) onto windows owned by the overlay
    thread. `SetFocus` only works within the calling thread's queue, so it
    silently does nothing when Escape closes the picker.
40. **R — `g_scroll` uses `InterlockedExchange` around a non-atomic
    read-modify-write** on both sides. The wrapper provides no more safety than a
    plain store while reading as if it does; `InterlockedExchangeAdd` is what the
    PgUp case wants.

---

## 4. What I changed

Four commits, each built and proved fresh with `go.bat build`.

### 4.1 Commands
- **`drivecam <height> <dist>` implemented.** Advertised in `modhelp`, in
  `DriveStart`'s own on-screen text and in the Tab seed; dispatched nowhere.
- **`grab` removed from `modhelp`.** Implemented nowhere at all — no dispatch, no
  numpad handler, no state. The help line now names what actually moves entities.
- **`entflag undo` implemented**, making the block's own promise true. It refuses
  when the saved address is no longer this pawn's flag word.
- **Eleven commands added to Tab completion**; `modhelp` now also mentions
  `rcprobe`, `streaming`, `fixplayer`, `allsectors`, `mergelib` and the `fp*`
  diagnostics.

### 4.2 Bugs fixed
Items marked **F** in §3: 1–13, 16–18, 21–22, 28, 31.

### 4.3 Dead code removed
Every one grepped over the whole file first, and every site keeps a one-line note
naming what replaced it.

`ApplyTextFix()` (67 lines — the falsified "+0x38 hypothesis") · `PkCacheSync()`
(22 lines of the exact cross-thread `SendMessage` storm the row cache was built
to end) · `PkNowMs()` · `g_wantUI` · `g_wantPanel` · `g_watch` · `g_textMode` ·
`g_textLogged` · `g_postWarp` · `g_postWarpXY` · `POSTWARP_FRAMES` ·
`POSTWARP_Z` · `g_kbHook` · `g_kbThread` · `g_kbTid` · `g_kq` · `g_kqHead` ·
`g_kqTail` · `KQ` · `g_hookCalls` · `g_lastHookCalls` · `g_vpW` · `g_vpH` ·
`extern g_pkSnapFwd()` · `FN_LOADWORLD` · `VT_SLOT_LOADW` · `SPAWN_FILE` ·
`OFF_CC_FOV_LIVE` · `DRIVE_STALL_MS` · `FN_KILLPAWNAGENT` · `fnKillPawnAgent` ·
the unused `editing` local in the hotkey loop.

### 4.4 Performance
`listx` walks the entity map on the game's main thread and this project measured
the pull at ~95 ms for 1,251 entities. Two changes, both on that path:

- **`EntityNameFast`** — the snapshot's inner loop called `EntityName`, which is
  **two `VirtualQuery` syscalls per entity**: ~2,500 kernel transitions per pull
  at roughly 10 µs each, about **25 ms**. Replaced on the snapshot path only,
  with exactly the transformation `RefNodeEntityFast` already makes and documents
  (QuickPtr + SEH instead of VirtualQuery). It keeps its own `__try`, so a
  faulting name costs the name and not the whole row — the old code emitted the
  entity as `"?"`, and dropping the row instead would have silently shrunk the
  editor's world. `EntityName` itself is untouched: every other caller is a
  once-per-command read where a syscall is free.
- **Class id formatted once per bucket** instead of one `_snprintf` per entity
  (~1,251 calls become ~200), and the name copy stops at the NUL instead of
  `strncpy` zero-filling all 96 bytes of a field averaging about 30.

And one off that path but bigger in absolute terms:

- **The console painter is now rate-limited to ~15 Hz independently of the
  overlay tick.** Opening the picker drops that tick from 66 ms to 10 ms so a
  list you are typing into feels live — which silently made the *ungated* console
  painter 6.6× dearer. Per pass it fills and alpha-lifts ~576,000 pixels twice,
  `memcpy`s 2.3 MB under `g_snapCs`, and raises `g_snapDirty` unconditionally so
  the render thread re-uploads 2.3 MB to VRAM. At 100 Hz, to redraw text that
  changes at typing speed. `PkPaint` keeps the fast cadence — it *has* a change
  gate, which is what made 10 ms affordable in the first place.

**These are arithmetic, not measurements.** `Editor/tools/perfprobe.py` is what
would confirm them; see §7.

---

## 5. What I deliberately did not touch, and why

- **The eight editor-link verbs and `LinkTick`'s structure.** Breaking the live
  link breaks the level editor. `listx`'s reply format, `poslist`'s non-JSON
  format and the `unknown verb` error text are all contracts the Python side
  depends on (`live.py` falls back only when the error contains `unknown verb`).
  Nothing in `LinkTick` changed.
- ~~**the pending `bones` verb — not applied.**~~ **Superseded: applied on the
  owner's authorisation, verbatim. See §9.1.**
- **`Readable()` itself.** A region cache would remove most of the remaining
  syscalls, but it answers *"this region was committed earlier in this walk"*
  rather than *"now"*, and this file's own comment says the page can be unmapped
  mid-walk while the world streams. That is a real weakening of the project's #1
  safety primitive for a second-order win. The `EntityNameFast` route gets most
  of the same benefit with the safety property unchanged.
- **The never-shown picker window (§3.7 #34) and the `OutputDebugStringA` block
  (§3.7 #35).** Both are large, coherent and complete. One is dead by a
  deliberate design decision recorded in its own comment; the other is a working
  feature nobody switched on. Deleting either is a product decision.
- **`g_lastVelCall` and `g_sigVt`** — write-only state, but the writes sit inside
  drive teardown, and drive teardown is where cross-thread mistakes in this file
  have hurt most. Removing them earns nothing and touches that path.
- **The duplicated `GetPlayerEntity` / `GetPlayerElem` / `GetPlayerObject` walks
  and the `FreecamEnter` / `FirstPersonEnter` preambles.** Real duplication that
  has really drifted (§3.4 #19), but unifying them changes what four live features
  resolve to, with no way to test the result. Reported; the safety guards each one
  was individually missing were added in place.
- **`lib.xml`, `Editor/`, and `D:\Games\Avatar The Game\`** — untouched, per the
  brief. No editor suite is affected by anything here.

---

## 6. What cannot be settled by reading

Stated plainly, because it is most of this:

- **Whether any fix works.** Everything was proved by the compiler and by
  argument. Nothing was proved by the game.
- **The `listx` saving.** Predicted ~25 ms from a syscall count times this
  project's own measured per-call cost. A prediction until `perfprobe.py` prints
  a number.
- **Whether `drivecam` actually reframes the camera.** The state it writes is the
  state the `[`/`]` and `=`/`-` keys write, and those are reported working — but
  the command path has never executed.
- **Whether the `End`-while-driving crash (§3.1 #3) was in fact this.** The
  mechanism is certain; that it is the crash anyone actually hit is inference.
- **Every item marked R in §3.** They are described precisely enough to act on,
  and not one of them was confirmed against a running game.
- **Whether the sampler-state leak (§3.6 #29) is visible.** The asymmetry is
  certain; the visual consequence is not.

---

## 7. Runtime test plan

Ranked: highest risk of regression first. Each line says what to type and what
correct looks like. **Build with `go.bat build`, then `go.bat inject` — do not
run `go.bat` bare while an editor session is attached.**

### Tier 1 — did I break the main product?

| # | Do this | Correct result | Fails if |
|---|---|---|---|
| 1 | Start the editor, `hello` in its log | proto + DLL build stamp + world name | link dead — the highest-consequence regression here |
| 2 | Editor viewport: full refresh (`listx`) | all entities appear, named, with boxes | names empty or count wrong ⇒ `EntityNameFast` is wrong |
| 3 | Editor auto-refresh on (`poslist`), leave it running 30 s | positions track; no name changes | anything renames ⇒ the meta flag is wrong |
| 4 | With auto-refresh **still running**, type `ents` in the console | browser lists entities **with names** | empty list ⇒ §3.3 #8 not fixed |
| 5 | Drag an entity in the editor (`move`) | it moves, or reports honestly that it refused | — |
| 6 | `listx` while watching the frame rate | should hitch less than before | this is the §4.4 claim; `Editor/tools/perfprobe.py` gives the number |

### Tier 2 — the unload path (the fixes most likely to matter, and least likely to be exercised by accident)

| # | Do this | Correct result |
|---|---|---|
| 7 | `drive` a creature, `F6` for the HUD, then press `End` | game keeps running; log ends `---- detached ----` with **no** `[exit] ***` lines |
| 8 | `firstperson`, then `End` without leaving it | same — this is the look-at pointer case |
| 9 | `drive` one species, stop, `drive` a different species, then `End` | log shows `[vt ] restored N of N patched slot(s)` with N ≥ 2 |
| 10 | `ingame` on, `End`, then re-inject and `End` again | no crash on either unload; no GDI handle growth in Task Manager |
| 11 | `freecam`, `noclip`, `freeze`, then `End` | camera, physics and time scale all restored |

### Tier 3 — the commands I changed

| # | Type this | Expect |
|---|---|---|
| 12 | `drivecam` | `drivecam: height 3.0, distance 7.0` + usage |
| 13 | `drive` a creature, then `drivecam 6 15` | camera pulls back and up; `[`/`]`/`=`/`-` still work from there |
| 14 | `entflag` | flag word + `'entflag undo' puts the whole word back (nothing saved yet)` |
| 15 | `entflag clear 400000` then `entflag undo` | second line restores the original word |
| 16 | `entflag clear 400000`, `warp sp_hometree`, `entflag undo` | **refuses**, naming both addresses |
| 17 | `modhelp` | no `grab` line; `rcprobe`, `streaming`, `mergelib`, `fp*` present |
| 18 | Type `age` + Tab, `rcp` + Tab, `resu` + Tab, `merg` + Tab | completes to `agentinfo`, `rcprobe`, `resurrect`, `mergelib` |

### Tier 4 — the behaviour changes

| # | Do this | Expect | Watch for |
|---|---|---|---|
| 19 | `drive` a creature, then left-click something else in the world | chase camera **stays on the creature** | if it now refuses to follow at all, §3.3 #11 is wrong |
| 20 | `drive`, walk until the sector unloads and the creature freezes | camera holds its last position, no crash | previously it read a possibly-freed entity |
| 21 | `drivebind 3 Viperwolf_Attack_Warning` on a creature whose slot 3 was "combat" | key 3 sends the signal, does **not** toggle combat | |
| 22 | `pick` in a crowd, then `delete`, then `agentinfo` | `agentinfo` says nothing is selected — not the dead thing's name | |
| 23 | Open `ents`, type into its search box for 20 s, watch the frame rate | should be **better** than before | if console text now feels laggy, the 15 Hz cap in §4.4 is too aggressive |
| 24 | `pick` where 5+ things overlap | the "also here:" line lists them all, comma-separated | previously it silently dropped names |

### Tier 5 — regression sweep on things I did not change but stand near

`freecam` / `freecam 1` · `firstperson` + `fpaim` + `fpoffset` · `spawn` (picker
and by name) · `spawn_all` · `warp sp_hometree` then `fixplayer` · `tp` ·
`respawn` · `kill` / `resurrect` · `vehenter` / `vehexit` · `timescale 0.25` /
`freeze`.

---

## 8. One structural note

`drivecam` was advertised in three places and implemented in none. That is not a
typo, it is a shape: **a new command has to be added to four independent lists** —
the dispatch in `TryModCommand`, the hardcoded seed in `LoadCmdList`,
`console_cmds_seed.h`, and the printed help in `ModHelp` — and nothing checks
them against each other. Eleven more commands were missing from two of those
lists when I started.

The cheap fix is a build-time check: a small script that greps the `_stricmp(p, …)`
and `_strnicmp(p, …)` arms out of `TryModCommand` and diffs them against the two
completion lists and `ModHelp`, failing the build on a mismatch. `DevAccess/scripts/`
already holds `seed_cmds.py`, which generates one of the four. I did not write it
— it belongs in `scripts/`, outside `console_dll/`, and it is a separate decision.

---

## 9. Addendum — the two authorised changes

Both were flagged in §5 as owner decisions; the owner authorised both. Applied
after everything above.

### 9.1 The `bones` verb — applied verbatim

`DevAccess/EDITOR_ANIMATION_DLL_PATCH.md`, all three inserts, **byte-for-byte as
written**. The three anchors matched exactly once each, mechanically, and were
taken from the patch document's own fenced blocks rather than retyped:

| Insert | Where it landed |
|---|---|
| §2 helper — `CID_RENDERABLE`, `VT_BONEHOLDER_A|B`, `OFF_BONE_*`, `BONE_*`, `BoneHolder()`, `BoneMatFinite()` | immediately before `static void LinkTick(void* console)`, and ~3,150 lines after the `FN_GET_COMPONENT` / `fnGetComponent` block it depends on |
| §3 verb — the `bones` block | inside `LinkTick`, after the `listx` block's `goto done; }`, before the `player` comment |
| §4 help line | the `LnkFail` string, now `"…listx, poslist, bones, player, get, select, move"` |

**Nothing was "improved".** The reply format the editor was tested against is
untouched: `bones <HI:LO>[,…] [A|B]` (and `bones sel`), one `"ent"` sub-header
per entity, `{"i","h","m":[16 floats]}` per bone, then the `stat` and `end`
lines. The `unknown verb` phrase that `live.py` latches on to is preserved
verbatim, so an editor built against a newer protocol still degrades correctly
against an older DLL.

**Two concerns, reported rather than acted on** (the brief asked for exactly
this):

1. **`BoneHolder` validates the vtable slot with `Readable(vt, slot + 4)` and
   then calls `vt[slot / 4]`.** `Readable` proves the memory is committed, not
   that the dword there is a function — and this file states repeatedly that
   those are different claims. The `__try` around the call is the real guard, and
   it is present, so the failure mode is a caught fault rather than a crash. But
   if `+0x84` on some renderable is not an accessor at all, the first symptom
   will be a swallowed exception and `src` reporting `vt80`, not a clear error.
   Worth knowing when reading the first run's output.
2. **It reads `holder+0x2C` as the count and trusts `holder+0x20` as an array of
   `n * 0xA0` bytes.** Both are bounded (`n <= BONE_MAX`, then `Readable` over the
   whole span), so this is safe — but the *stride* is the one number that is
   inferred from two disassembled accessors rather than measured, and a wrong
   stride would produce plausible-looking garbage matrices rather than a fault.
   `boneview`'s `ratio` readout is what catches that; §7 test 26 below.

The verb is **selection-scoped and inert until asked** — it costs nothing on the
per-frame path, since `LinkTick` returns on one interlocked compare when no
request is pending.

### 9.2 The `OutputDebugStringA` capture — wired up

`InstallDebugStringHook` is now called in `Worker`, immediately after
`InstallCrashReporter()` and after the `g_rebase` block (the IAT entry is
Dunia's, so its address is meaningless before the rebase delta is known).
`avatar_debug.log` will now receive Scaleform GFx's log and Dunia's fatal path.

**The unload path was the constraint, so it got the most care.** Five things:

1. `RemoveDebugStringHook()` added to `RemoveHook()`, before
   `RemoveCrashReporter()` — so the capture stays live as long as possible while
   still coming off well before the unmap, with its own 120 ms drain plus
   `Worker`'s `Sleep(300)` after it.
2. **The same ordering bug the Present hook had, fixed here too.**
   `RemoveDebugStringHook` nulled `g_odsOrig` *before* the `Sleep(120)` that
   exists to protect it, and the handler ends with `if (g_odsOrig) g_odsOrig(s)`.
   Milder than the Present case — that one called address 0, this one silently
   swallows a message — but it is the same mistake, so: restore the slot, drain,
   *then* drop the pointer.
3. **A failed restore now refuses to forget.** It used to zero `g_odsOrig`
   whether or not the `VirtualProtect` succeeded. It now logs loudly and keeps
   the pointer so the sweep can repair.
4. **Added to `VerifyUnhooked`.** The sweep's contract is "every slot we ever
   wrote"; this is a new slot, so it is now checked, with a `g_odsOrigEver` copy
   for the same reason `g_rdPresentEver` exists — the sweep runs after
   `RemoveHook` has already zeroed the live pointer.
5. **`g_odsCs` is deliberately not deleted.** The handler's guard is
   `if (s && g_odsCsInit)` followed by `EnterCriticalSection` — check-then-act,
   and deleting a critical section out from under that is exactly the `g_snapCs`
   shape in §3.1 #3. It is 24 bytes of our own static storage that goes away with
   the mapping.

**One incidental fix, in the same territory.** `Worker`'s
*"g_console never appeared"* path did a bare `return 0` with the crash reporter
already armed and the DLL still resident — no thread left to unload it, so
`inject.py` would refuse with *"already injected"* and only a game restart
cleared it. That is the identical trap the `InstallHook` failure path directly
below it was already fixed for. It now removes both hooks and unloads.

### 9.3 Build state — HISTORICAL, resolved 2026-08-04

> **This section is kept for the method, not the state.** The stale binary
> described below was rebuilt: `dist\avatar_console.dll` now links at
> **2026-08-04 14:43 UTC** against a source last written 07:42 local, so the DLL
> is **ahead of** the source, not behind it. `check_cmds.py` passes 75/75, the
> two output names are byte-identical (md5 `a44d4d35e81c01937a6e27c8b030c442`),
> machine is `0x014C` (x86) and the image base is `0x2A000000` as intended.
> **No action is required from this section.** What is still worth keeping is the
> failure mode it names — see `tools\go.bat`, which exists solely because a
> silent `LNK1104` once cost two debugging rounds against a stale binary.

**As written (now false): the source compiles and links; the shipped
`avatar_console.dll` is STALE.**

`go.bat build` fails at `LNK1104: cannot open file 'avatar_console.dll'` because
`Avatar.exe` is running and holds it. That is the documented case the freshness
gate exists to catch, and `buildstatus.py` correctly reports:

```
[STALE] avatar_console.dll   built 03:09:34 but source is 03:22:46 - SOURCE IS NEWER
```

To prove the change is not merely *compilable* but *linkable*, the same source
was built with identical flags (`cl /TP /LD /O2 /W3`, x86, same libs) to a
scratch output that does not touch the locked DLL: **`LINKCHECK OK`, `14C machine
(x86)`, no compiler warnings.** So the failure is the lock, not the code.

**The owner must press `End` in-game to unload, then run `go.bat build` and
`go.bat inject`.** Until then the running DLL has none of this.

### 9.4 Extra runtime tests for these two changes

Insert ahead of Tier 5.

| # | Do this | Correct result | Fails if |
|---|---|---|---|
| 25 | `bones sel` with a standing NPC selected | `count` ≈ 103, `src` = `vt84` or `vt80`, `us` in the `stat` line | both slots failing on *every* entity means the accessor is neither, and the two call sites in the patch's §1 need re-reading |
| 26 | Watch `boneview`'s per-model line | `ratio` near 1.000, `matched` close to the bone count | `matched` well below the count = the hash join is failing, or the `0xA0` stride is wrong (§9.1 concern 2) |
| 27 | Read the `us` field on that first reply | well under a millisecond | this is the number the design lives or dies by, and it was a prediction until that line printed |
| 28 | `bones` on something with no skeleton (a rock, a light) | a per-entity `"err"` line, other ids in the same request still answered | a whole-request failure means the per-entity error handling is not working |
| 29 | Editor: full refresh, then a bone pull, then auto-refresh | all three still work; `listx`/`poslist`/`player` unchanged | any link regression here is the highest-consequence outcome of this change |
| 30 | After a session, open `DevAccess/console_dll/avatar_debug.log` | it exists and has GFx/Dunia lines with timestamps and thread ids | empty or absent ⇒ the IAT slot did not validate; the log says so at startup |
| 31 | **`End` to unload, then re-inject, then `End` again** | no crash either time; log shows `[dbg ] OutputDebugStringA restored` and **no** `[exit] *** ... STILL ours` lines | this is the test that matters most — a second hook now has to come off cleanly |

---

## 10. Addendum — the Tab-completion bug report

Reported symptom: *"typing `spawn` should complete to the whole family —
`spawnall`, `spawnground` and the rest — but it only offers a few of them, and
misses `spawnall` entirely."*

### 10.1 Diagnosis first

The two candidate causes were "the list is incomplete" and "the matching logic is
wrong". Both were tested against the real data before anything was changed, by
replicating `CmdAdd`, `LoadCmdList` and `TabComplete` in Python and running them
over the actual `console_cmds_seed.h`, `console_cmds.txt` and `console_dump.txt`.

**Result: three separate things, and the headline example is not what it looks
like.**

1. **The list was incomplete — and that is already fixed, but unbuilt.** Before
   commit `1f12a2b`, eleven dispatched commands were in *neither* completion list
   (`agentinfo`, `driveai`, `editorlink`, `facing`, `facinginfo`, `mergelib`,
   `rcprobe`, `respawn`, `resurrect`, `revive`, `vehinfo`). Tab could not offer
   them however many times it was pressed. The cross-check now reports
   `DISPATCHED BUT IN NO LIST: []`. **The owner is running a DLL from before that
   fix**, so this is very likely most of what was actually hit — typing `re` and
   pressing Tab could never reach `respawn`, `resurrect` or `revive`.
2. **`spawnall` does not exist.** The command is `spawn_all`, with an underscore.
   Tab was right to not offer `spawnall`. All five real members of the family —
   `spawn`, `spawn_all`, `spawn_list`, `spawn_trap`, `spawnground` — were in the
   list the whole time, and the simulation confirms the cycler reached all five
   even before this fix.
3. **But the ordering and the silence made a working cycle look broken.** Two
   real defects, both fixed here:
   - The table is in insertion order and there was no exact-match rule, so
     typing `spawn` and pressing Tab gave **`spawnground`** — because
     `spawnground` sits earlier in the seed than `spawn` does. Typing `fp` gave
     `fpoffset`. That reads as Tab jumping somewhere arbitrary.
   - **`g_cmds` had exactly one reader in the whole file — `TabComplete`
     itself.** Nothing ever displayed the candidates or the count. With ~550
     names and a blind cycle, *"are the rest missing, or am I two presses
     away?"* is unanswerable. Stopping after two presses and concluding "it only
     offers a few" is the correct inference from the available evidence.

So it was mode (1) for eleven commands, plus a genuine ordering/feedback defect
that made the remaining families look broken too.

### 10.2 What was fixed

- **Exact match first.** On a fresh Tab run, an entry equal to the stem is
  offered before any longer prefix match. `spawn` → `spawn`, then `spawn_list`,
  `spawn_all`, `spawn_trap`, `spawnground`. Cycling from there is unchanged.
- **The candidate set is announced**, once per Tab run, through the existing
  `g_note` input-thread → main-thread hand-off: `tab: 5 matches - spawn
  spawn_list spawn_all spawn_trap spawnground`. A stem that matches nothing now
  says so instead of leaving the key looking dead.
- **The 70 hand-written `strcpy` lines became one `kOurCmds[]` table**, seeded
  through `CmdAdd` so it is bounds-checked against `CMDMAX` and deduped. The old
  block had neither check and was safe only because it happened to run first.

### 10.3 The structural fix — drift cannot ship silently

Adding a command means touching four independent places: the dispatch chain,
`kOurCmds[]`, `console_cmds_seed.h`, and `ModHelp`. Nothing compared them, and
all of them had drifted. C cannot derive the completion list from a chain of
`_stricmp` calls, so the next best thing:

**`DevAccess/console_dll/check_cmds.py`**, run by `build.bat` *before* `cl`. It
greps the `_stricmp(p, "…")` / `_strnicmp(p, "…")` arms out of `TryModCommand`,
diffs them against `kOurCmds[]`, and **fails the build** on a mismatch in either
direction — dispatched-but-not-completable (the eleven), or
completable-but-not-dispatched (the `drivecam` shape). It also prints an advisory
list of `ModHelp` lines starting with a word that is not a command, which is
where `grab` hid.

It was tested against deliberately drifted copies of the source in both
directions and correctly failed each with exit 1, so it is a real check and not
one that always passes. It skips silently when python is not on PATH, so it can
never stop someone building from a shared copy.

### 10.4 Extra runtime tests

| # | Do this | Correct result |
|---|---|---|
| 32 | Type `spawn`, press Tab **once** | completes to **`spawn`** — not `spawnground` |
| 33 | Keep pressing Tab | `spawn_list` → `spawn_all` → `spawn_trap` → `spawnground` → wraps. All five, none skipped |
| 34 | Watch the console line after that first Tab | `tab: 5 matches - spawn spawn_list spawn_all spawn_trap spawnground` |
| 35 | Type `re` + Tab | `respawn`, then `resurrect`, then `revive` — these were the eleven that no list carried |
| 36 | Type `rcp` + Tab, `merg` + Tab, `agent` + Tab | `rcprobe`, `mergelib`, `agentinfo` |
| 37 | Type `zzz` + Tab | `tab: no command starts with "zzz"` — not silence |
| 38 | Type `drive` + Tab, cycle right round | all 8: drive, drivespeed, drivewait, drivecam, drivesignal, drivecalm, drivebind, driveai |
| 39 | `warp ` + Tab | still cycles WORLD names, not command names — the `warp` argument path is untouched |
| 40 | Shift+Tab from mid-cycle | steps backwards through the same set |

**Note on `spawnall`:** there is no such command. It is `spawn_all`. Test 33 is
the check that the whole real family is reachable.

---

## 11. Addendum — the Tab regression, and its real root cause

The section 10 fix was a **usability regression**: Tab stopped completing at all
and printed a log line on every press instead. Reported as *"why aren't you
autocompleting? It's not even autocompleting, it's just telling me which commands
it found."* Twenty consecutive presses produced twenty identical lines.

### 11.1 One root cause, three visible symptoms

The fresh-run test keyed off `g_tabIdx`, and `InKey` contained:

    if (vk == VK_TAB) { TabComplete(...); return; }
    g_tabIdx = -1;              /* any other key ends the completion cycle */

The input thread polls **~240 virtual keys every 8 ms** and hands `InKey`
anything with an event, so that line fired *between* two Tab presses.
`g_tabIdx` did not survive from one press to the next. Therefore:

- **Every press was a "fresh run"**, so every press took the new exact-match
  branch — and that branch set the index and jumped straight to the announcement
  **without writing `g_in`**, on the reasoning that the buffer already held that
  text. It did. So nothing moved on screen. *(symptom 1: no completion)*
- **Every press therefore also announced**, gated on the same broken flag.
  *(symptom 2: twenty identical lines)*
- The announcement walked `g_cmds` **from index 0** while the cycler started at
  the exact match — two orderings, one displayed and the other used, so the
  display was actively wrong about what the next press would do.
  *(symptom 3: `spawnground` listed first)*

**This same clobbering had been breaking Tab all along.** Before the exact-match
branch existed, every press was equally "fresh" and simply re-offered the *first*
prefix match — which is exactly the original report, *"it only offers a few of
them"*. Section 10 diagnosed the list correctly and misdiagnosed the interaction.

### 11.2 The fix: the run state is the buffer

`g_tabIdx` is **gone**, and so is the `InKey` line that reset it. A run continues
if and only if `g_in` still equals `g_tabLast` — exactly what Tab last wrote.
Typing, backspacing or submitting changes the buffer and ends the run by
construction; a stray `InKey` call cannot end it at all, because it does not
touch the line.

Also fixed:

- **Tab always rewrites the line**, including when the completion is textually
  identical to what is already there. That was the omission.
- **`TabNth` / `TabOrdOf` are the single source of candidate order** — ordinal 0
  is the exact match, then the rest in table order — and the listing walks the
  same helpers, so display and behaviour cannot disagree again.
- **The shell convention**: first Tab completes silently; a second Tab in the
  same run lists the candidates once; never while the completion is unambiguous.
  One line across a whole cycle, not one per press.
- **A trailing space is argument position**, handled silently. `spawn` + Tab +
  space + Tab no longer reports `no command starts with "spawn "` — a failure
  against a stem the completer itself had just produced. There is no argument
  completion except `warp`'s, so it does nothing rather than pretending.
- **The no-match message records the run too.** Without that it repeated on every
  press — the same flooding, on the failure path.
- `TabCompleteWorld` takes the same buffer-derived `fresh`, so `warp <TAB>`
  cycling cannot be reset either. It had the identical defect.

### 11.3 How it was verified this time

The section 10 test simulated the **match set**, which was already correct, and
so could not see the bug. This one simulates the **keystroke sequence** and
asserts on the **input buffer** and the **message count**:

    type 'spawn' then Tab x6
      1 -> spawn          4 -> spawn_all
      2 -> spawnground    5 -> spawn_trap
      3 -> spawn_list     6 -> spawn   (wraps)
      messages printed across the whole run: 1
      and that one line lists the candidates in the SAME order the key walks them

21 assertions, all passing, including: the cycle still advances when a stray
`InKey` reset is injected between presses (the exact regression); `re` reaches
`respawn`/`resurrect`/`revive`; a no-match stem prints exactly one message across
five presses; a trailing space prints none; an unambiguous stem never lists;
Shift+Tab steps backwards; and typing mid-cycle starts a fresh run.

**Ordering note.** The non-exact members cycle in table order (`spawn`,
`spawnground`, `spawn_list`, `spawn_all`, `spawn_trap`), not the literal sequence
in the bug report. Any stable order works; what matters is that the exact match
leads, every member is reachable, and the listing shows the same order the key
will follow. All three now hold.

### 11.4 Revised runtime tests (these replace 32-40)

| # | Do this | Correct result |
|---|---|---|
| 32 | Type `spawn`, press Tab **once** | the line becomes `spawn`. Something is completed — this is the whole complaint |
| 33 | Press Tab five more times | `spawnground` then `spawn_list` then `spawn_all` then `spawn_trap` then back to `spawn` |
| 34 | Count the `tab:` lines across all six presses | **exactly one**, after the second press, listing the five in cycle order |
| 35 | Type `re` + Tab, keep pressing | reaches `respawn`, `resurrect`, `revive` |
| 36 | Type `zzz`, press Tab five times | **one** message, line unchanged |
| 37 | Type `spawn`, Tab, then space, then Tab | line stays `spawn ` — no message, no failure text |
| 38 | Type `modhel` + Tab, then Tab twice more | completes to `modhelp`; **no** listing (unambiguous) |
| 39 | `warp ` + Tab, repeatedly | still cycles WORLD names, and now advances properly between presses |
| 40 | Shift+Tab from mid-cycle | steps backwards through the same order |

---

## 12. Task 1 — is the AI hijack complete? (interim verdict + the decisive test)

**Short answer: no, and it never could have been — because the mod does not
write the creature's facing at all.**

### 12.1 What we actually control, established from this file's own evidence

Two paths write anything to the creature:

- `hkSetDesiredVelocity` (agent vtable **+0x128**) substitutes our vector when
  the AI asks for one, and
- `DrivePush()` calls that same engine setter **every frame from the main-thread
  detour**, whether or not the AI asked.

`DriveKeysToVel()` — the single shared source of that vector, deliberately
factored so the two callers cannot drift — produces **a velocity and nothing
else**. It never touches orientation. And the setter it feeds (`0x10A8FF60`) is,
per the disassembly recorded beside `DrivePush`, a pure store:

    mov ecx,[ecx+0x260]    ; agent -> CPawn
    call 0x1026BA50        ; = mov eax,[ecx+0x28] -> pawn state block S
    S+0x0C = x, S+0x10 = y, S+0x14 = z

So: **we steer translation only. Every degree of yaw the creature has is written
by engine code we do not touch.** That is not a bug in the suppression, it is a
gap in what was ever attempted, and it explains the symptom directly.

### 12.2 The channels, and which are covered

| # | Channel | Suppressed today? | By what |
|---|---|---|---|
| 1 | Desired velocity / locomotion request | **yes** | `+0x128` hook, plus `DrivePush` overwriting every frame |
| 2 | Self-directed animation signals | **yes** (when `driveai` is on) | `+0x148` hook drops the agent's own `RequestSignal` |
| 3 | Combat behaviour | **partly** | `drivecalm` → `AgentCombat(0)` at `+0x1E0`. Suspends a *behaviour*, not the animation track |
| 4 | Sensory focus (target/look-at) | **one byte only** | `facing` zeroes `sens+0x1D` before `Update` |
| 5 | **Yaw / orientation write** | **NO** | nothing. We never write it and never block it |
| 6 | **Targeting, path requests, behaviour selection** | **NO** | the agent's `Update` (`+0x208`) still runs in full |
| 7 | **Animation root motion** | **NO** | not investigated here |

Channels 5–7 are unsuppressed, and the whole of 6 runs every tick even with
`facing` on — `facing` removes one *input* to the brain, not the brain.

### 12.3 The decisive experiment — `drivelock`

`FACING.md` ends without a conclusion, and the `facing` command says so on
screen: *"whether yaw is actually driven from this focus is UNKNOWN, the last hop
was never found."* The experiment that settles it is not more reading:

    drivelock off    the AI updates normally (what ships today)
    drivelock soft   zero the focus byte before Update - what `facing` does
    drivelock hard   DO NOT CALL the agent's Update at all

`hard` returns from `hkAgentUpdate` without invoking the original, for the driven
agent only. No sensing, no targeting, no behaviour, no path requests. Steering is
expected to survive because `DrivePush` writes the pawn state directly, which
§12.1 shows is downstream of the agent.

**Both outcomes close the question:**

- **stops swivelling at `hard` but not at `soft`** → the yaw write is downstream
  of the focus byte, and `facing` was the wrong lever all along. Then the job is
  to find the write between the agent and the transform.
- **still swivels at `hard`** → the agent is *not* responsible, because none of
  it ran. That eliminates the entire AI agent in one test and points at the pawn,
  the movement component, or animation root motion.

This is also the answer to *"per-channel or one clean gate?"* — `hard` **is** the
clean gate. If it holds, per-channel suppression can be retired rather than
extended.

**Stated risk, untested:** if the move tree or animation state machine is ticked
from that `Update`, `hard` may freeze the creature's animation while it still
slides where you steer it. That is a readable result, not a fault, and it is why
this is a level rather than the new default. `off` remains what ships.

### 12.4 What is still open

Two research streams were running when this was written and their findings are
**not** in this section: (a) a full digest of what `FACING.md`, `CONTROLLED.md`,
`CREATURE_RIDING.md`, `NPC_POSSESSION*.md` and `POSSESSION.md` already establish
about every control channel, and (b) a search of the newly built `ENGINE_MAP`
(25,568 named functions, 27,565 globals, `dunia.db`) for the actual per-frame
yaw write and for any engine-level "this entity is externally controlled" flag.
Whatever they find refines §12.2 and may replace §12.3 with a precise
suppression — but it does not change the experiment's value, because the
experiment is what tells us which half of the engine to look in.

### 12.5 Runtime tests for Task 1

| # | Do this | What it tells you |
|---|---|---|
| 41 | `drive` a creature, let it settle, watch whether it turns on its own | the baseline. `drivelock` alone reports `off` |
| 42 | `drivelock soft`, provoke it again | this is exactly what `facing` does; if it still swivels, the focus byte is not the lever |
| 43 | `drivelock hard`, provoke it again | **the decisive one.** Report which of the two §12.3 outcomes you see |
| 44 | While in `hard`, check the creature still moves on WASD | confirms §12.1 — steering is downstream of the agent |
| 45 | While in `hard`, watch its animation | if it slides without animating, the move tree is ticked from the agent Update — say so |
| 46 | `drivelock` with no argument | reports the level and the count of skipped updates — the evidence that the gate is actually firing |
| 47 | `drivelock off`, then `End` to unload | the `+0x208` hook must come off; log shows no `[exit] *** ... STILL ours` |
| 48 | `drive` species A, stop, `drive` species B, `drivelock hard`, `End` | two vtables patched; the registry restore must handle both |

### 12.6 CORRECTION to 12.2, and the two levers that were never implemented

A full read of `FACING.md`, `CONTROLLED.md`, `CREATURE_RIDING.md`,
`CREATURE_AUDIT.md`, `NPC_POSSESSION*.md` and `POSSESSION.md` corrects §12.2 and
supersedes part of §12.3.

**The biggest finding: `facing` has always been FACING.md's "Lever 3", which that
document explicitly marks *"diagnosis only, do not ship"*.** Writing
`sens[0x1D] = 0` **before** the original `Update` makes the `je` at `0x10AB5F23`
skip the **entire** `Update` body — charge timer, stim broadcast, everything. So
`facing` was never "suppressing a turn"; it was skipping the tick from the
inside. That is why it feels heavy-handed, and it is why `drivelock soft` and
`drivelock hard` turn out to be nearly the same experiment.

`FACING.md` names two levers it *does* recommend, and neither had ever been
implemented. Both are now `drivelock` levels:

| Lever | Doc's words | What it does | Level |
|---|---|---|---|
| 1 | *"most surgical; try first"* | call `Update`, **then** write `B[0x31] = 0` — be the last writer for the frame | `drivelock last` |
| 2 | *"the outcome the brief asks for"* | leave the focus alive but overwrite the focus **position** with our own aim point, at **both** ends (`B+0x34` and `sens+0x20`) because §15.6 leaves open which the consumer reads | `drivelock aim` |
| 3 | *"diagnosis only, do not ship"* | zero `sens[0x1D]` **before** `Update` | `drivelock soft` (= today's `facing`) |

The reason before-vs-after matters: `Update` copies `sens → B` **every tick**, so
writing before it is either overwritten immediately or skips the tick. Only
writing after wins the frame.

`aim` points the focus 20 m along the **camera's forward row** — the same row
`DriveKeysToVel` steers by — so the creature's facing and its movement agree
instead of fighting.

**Corrections to the §12.2 channel table:**

- **Pawn-state facing (`UsingAim`/`UsingLook`, `S+0x1C..0x1E`) is not a gap — it
  is CONFIRMED DEAD FOR ANIMALS.** `facinginfo` on a swivelling Viperwolf
  returned all zeros, and `FACING.md`'s own header says §§0, 4 and 8 *"were
  tested in game and are WRONG for animals… Do not implement §8."*
- **`CTaskOrientToward` is likewise dead for animals** — it reaches the pawn via
  `agent+0x338`, which on a `CBtzAnimalAgent` is a stim object, not a `CPawn`;
  and it is absent from every driveable species' brain.
- **Genuinely unsuppressed, confirmed:** re-pathing (`+0x17C` `BuildMoveRequest`,
  21 call sites, still submitted); GOSM `UseRotation` / `IgnoreRotation` root
  motion events; the move-manager `TurningAngle` pivot graph; and
  **`CAnimalSteeringEngineNew`** (crc32 `0x4E9DAADE`, vtable `0x110F108C`) —
  described as *"a plausible home for the turn-rate clamp that actually
  executes, and nobody has looked inside it."* That is the largest
  un-investigated candidate in the whole corpus.
- **There is no engine-level "AI off for this entity" for animals.** Every
  candidate was checked. `0x10760FA0` is `SetSpawnPoint`, not
  `SetControlledEntity` — `CONTROLLED.md` demolishes `POSSESSION.md` on this, and
  agrees with the standing project note. `CPawn.bIsAI` (`0x01` on every NPC,
  `0x00` on the player) is the closest thing named anywhere, and what gates on it
  is **UNTRACED**.

**So: per-channel, not one gate — for now.** `hard` remains the bisect, but the
honest ordering is now `last` → `aim` → `soft` → `hard`, because the first two
are what the research actually recommends and they had simply never been built.

### 12.7 Revised Task 1 test order (supersedes 41-48 where they differ)

| # | Do this | What it tells you |
|---|---|---|
| 41 | `drive` a creature, let it settle and swivel | baseline; `drivelock` reports `off` |
| 42 | **`drivelock last`** | FACING Lever 1, the one the document says to try first. If the swivel stops, the focus mirror **is** the yaw input and the question is closed |
| 43 | **`drivelock aim`** | Lever 2. Best case: the creature turns to face where your camera looks. That is the requested behaviour, not just suppression |
| 44 | `drivelock soft` | = today's `facing`. Skips the whole Update body from the inside |
| 45 | `drivelock hard` | strongest bisect. Still swivels here ⇒ the agent is not responsible at all; look at root motion or `CAnimalSteeringEngineNew` |
| 46 | Under every level, check WASD still moves it | confirms §12.1 — steering is downstream of the agent |
| 47 | Watch the animation under `soft`/`hard` | if it slides without animating, the move tree is ticked from the Update |
| 48 | `drivelock` bare | reports the level and the skipped-update count — proof the gate is firing |
| 49 | `drivelock off`, then `End` | the `+0x208` hook must come off cleanly; no `[exit] *** … STILL ours` |
| 50 | Drive species A, stop, drive species B, `drivelock aim`, `End` | `+0x208` is overridden **per species**, so two vtables get patched; the registry restore must handle both |

**FACING.md's own stop rule still applies:** if it still swivels with the focus
provably zero, *say so and stop — do not guess.* The next candidates in its own
order are a consumer that re-reads `sens+0x18` itself, the base-agent path at
`0x109DB440` (which uses `sens[0x28]`, not `sens[0x1D]`), and root motion from a
pivot clip selected upstream of everything examined.

---

## 13. Task 2 — the bottom HUD, and how it was made inspectable

### 13.1 The loop that made it possible

The artwork was previously only viewable by injecting, entering drive mode and
looking at a moving frame — useless for judging a chamfer angle or whether a
stepped gradient actually steps. So the drawing was factored into
**`hud_draw.h`**, which takes a 32-bit BGRA buffer and a memory DC and nothing
else: no engine, no globals, no game state.

**`hud_preview.c`** compiles that same header into a standalone `.exe` and writes
`out\hud_*.bmp` from synthetic values (100, 62, 8, 0; slow and fast camera; both
panels). `build_preview.bat` builds and runs it, and it never touches
`avatar_console.dll` — safe to run while the game is up.

The preview cannot drift from what ships, because there is exactly one copy of
the drawing code and both include it.

**This found four real defects that reading the code would not have:**

1. The paw rendered as a **blob with four specks** — toes at 16–18% of the paw
   radius are invisible at 60 px.
2. Fixing that by enlarging exposed a worse bug: drawing each pad's rim, body and
   highlight *before* moving to the next put every pad's dark rim **on top of its
   neighbour**, so the main pad's own lobes cut two seams across it and the paw
   rendered as **six separate circles**. Fixed by drawing the whole paw in
   **three passes** (all rims, then all bodies, then all highlights) — which is
   what any compound shaded silhouette needs.
3. The circle only **touched** the bar rather than merging — it read as a badge
   beside a bar. The bar now starts a fifth of the radius inside the circle's
   centre and the ring is drawn last, so it occludes the join.
4. The speed meter showed **nothing at 120** — a linear 40..4000 scale puts the
   entire usable low end inside the first 10%. PgUp/PgDn *multiply* speed by
   1.35, so the meter is now **logarithmic**, and any non-zero value lights at
   least one step.

### 13.2 The paw: three tones per pad, in three passes

**Chosen approach: concentric offset ellipses — a dark rim, the body, and a
smaller highlight pushed up and left.**

Why, against the alternatives:

- **Flat silhouette** — one brush, looks like a sticker. This was the named easy
  failure.
- **Pre-rendered image** — would look best, but means embedding a binary blob in
  the source or shipping a file beside the DLL. This project deliberately keeps
  the DLL self-contained; the compiled-in command seed exists for that reason.
- **`GradientFill`** — GDI only does linear and rectangular ramps, which is wrong
  for a round pad.
- **Offset ellipses** — pure GDI, no asset, scales with the ring radius, and
  gives a pad catching light from the upper left, which is where the frame
  highlight already implies the light is. 21 `Ellipse` calls, and the panel is
  only recomposed when a value changes.

Proportions ended at four toes on an arc (outer pair smaller and lower) over a
**wide, flat** main pad with two lower lobes. Flat is the point: 52×40 rendered
as a ball with specks over it. The eye identifies a paw from *the arc of four
against a broad base*, so those are the two things that had to survive at 60 px.

### 13.3 Why it needed no new D3D resource

`OverlayPaintDrive` already composed into the shared GDI surface and handed it to
`SnapPublish`, which the Present hook uploads into `g_tex` and draws with
`DrawPrimitiveUP` **inside the game's own frame**. The new `OverlayPaintHud`
takes the same route.

So it is on the capture path (Discord, OBS) for free, and — the reason this
route was chosen — **it adds no texture, no critical section and no teardown
ordering**. §3.1 records two separate D3D/GDI teardown bugs this file has already
paid for; the cheapest way not to pay a third time is to add no resource at all.
The only new GDI objects are two fonts, created lazily and destroyed inside the
existing `OverlayFreeGdi`.

### 13.4 Cost control

The artwork is nearly static, so `OverlayPaintHud` recomposes only when the
**integer** health percent, the camera speed, the client width or which panels
are shown actually changes. When nothing moved it returns before `SnapPublish`,
so the 2.3 MB VRAM upload does not happen either. Health is sampled on the
**main thread** at 10 Hz and published through `g_hudHpPct` — the overlay thread
must never make an engine call, which is why the value is pushed to it rather
than fetched.

### 13.5 F6 now cycles

The HUD replaced the text panel as the default, and a straight swap would have
silently retired the driving key list that panel carries. **F6 cycles: off →
health/speed HUD → driving key list.** Nothing was lost.

### 13.6 Runtime tests

| # | Do this | Correct result |
|---|---|---|
| 51 | `drive` a creature, close the console | the bottom HUD appears: paw circle, stepped bar, `HP` and a number |
| 52 | Let the creature take damage | segments extinguish from the right; the paw tint moves blue → purple → pink |
| 53 | Compare the number against `agentinfo` / `kill`'s report | they must agree — both read the same character-sheet slots |
| 54 | `freecam`, then PgUp/PgDn | the CAM SPEED panel appears bottom-right and its meter moves by ~1 step per press |
| 55 | Watch the frame rate with the HUD up and nothing changing | no measurable cost — it must not recompose or re-upload while static |
| 56 | Record with Discord or OBS | the HUD is in the capture, because it is drawn inside the game's frame |
| 57 | Press F6 three times | HUD → key list → off → HUD, with an on-screen note each time |
| 58 | Resize the game window | the bar re-spans the new width on the next change |
| 59 | `End` to unload while the HUD is up | clean; the two HUD fonts come down with `OverlayFreeGdi` |
| 60 | `build_preview.bat` | writes `out\hud_*.bmp` without the game running — the loop that made §13.1 possible |

---

## 12.8 CORRECTION — the engine-level AI gate DOES exist, and the ordering was fine

A byte-level trace of the decompile (25,568 named functions, `dunia.db`) landed
after §12.6 and **overturns two of its conclusions.** Both corrections are in our
favour.

### A. "There is no engine-level *AI off* for animals" — WRONG

There is, and it is one byte: **`agent+0x1C4` (u8)**. On BTZ animal agents the
per-tick entry is vtable `+0xCC` (`FUN_10ab5070`):

    if ( !this->vfunc_0xE4() )      // 109c0ad0: mov al,[ecx+0x1C4]; ret
          this->vfunc_0x208(dt);    // Update - the slot we hook

Getter is vtable `+0xE4` (`FUN_109c0ad0`); setters `FUN_10a8ded0` (=1, with
teardown) and `FUN_10a8dc40` (=0); initialised in `CGameAgent`'s constructor
`FUN_10a8e630`. §12.6's claim that `CPawn.bIsAI` was "the closest thing named
anywhere" was simply looking in the wrong place.

Shipped as **`drivelock agent`**. Two consequences shaped the implementation:

- **Our own `+0x208` hook goes silent** in this mode — the engine stops calling
  `Update`, so anything needing to happen per tick cannot live in
  `hkAgentUpdate`. It lives in `DriveLockTick`, on the main thread.
- **The flag only stops NEW commands.** What is already in the controller block
  persists and the pawn, animation and physics keep consuming it, so the stale
  look-at is cleared every frame.

**One correction to the advice that came with the finding:** `ctrl+0x0C` must
**not** be cleared. `ctrl` is `*(pawnBase+0x28)` with `pawnBase = *(agent+0x260)`
— the same block `SetDesiredVelocity` writes, storing x/y/z at
`S+0x0C/+0x10/+0x14` where `S = *(pawn+0x28)` (the disassembly is recorded beside
`DrivePush`). Zeroing it every frame would cancel our own steering, because
`DrivePush` is the thing writing it. Only the look-at is stale.

The look-at is cleared at **both** `+0x30` and `+0x31`, and via both routes
(`agent+0x300 → +0x28` and `agent+0x260 → +0x28`), because the trace itself flags
a four-byte disagreement between the write and read offsets — *"either different
structs, or my alignment is off by a slot"*. Writing both costs a few bytes and
removes the ambiguity as a variable.

### B. "`facing` may be zeroing the byte too late" — NO, the ordering is correct

The proposed cheapest-possible fix was that our hook might zero `sensor+0x1D`
*after* calling the original, by which time `FUN_10ab5f00` has already copied the
real value out. **Checked: it does not.** In `hkAgentUpdate`, the write

    sens[OFF_SENS_HASFOCUS] = 0;

is 23 lines *above* `((fnAgentUpdate)g_faceOrig)(agent, edx, dt);`, and the
comment beside it has always said *"BEFORE the original, so its je at
0x10AB5F23 is taken"*. So `facing`/`soft` has been ordered correctly all along.

**That is a useful negative result, not a non-event.** The sensor byte *is*
genuinely wired to facing — the trace confirms the copy — and we *are* zeroing it
at the right moment, and the creature still swivels. Ordering is therefore
eliminated, which strengthens the case that the turn is written **downstream of
the agent entirely**: the `CAnimal` rotation controller, or animation root
motion.

### C. Orientation writers are now exhaustively known

A byte-scan of all `.text` for the euler-cache invalidate
(`and dword [reg+0x90], 0xffdfffff`) finds it in exactly **three** functions, so
those are the only places an entity's orientation can change:

| Address | What | Callers |
|---|---|---|
| `0x101b4310` | `CEntity::SetWorldMatrix` — the runtime one | 33 |
| `0x101b47a0` | attachment / world-shift | 1 |
| `0x101b4430` | the reflected `"WorldMatrix"` property setter | — |

Thin wrappers: `0x101b4630` `SetAngles`, `0x101b44e0` `SetOrientation`,
`0x101b4580` `SetPosition`. This is a proof rather than a search: **any** yaw
change funnels through `0x101b4310`.

### D. Root motion can rotate the entity

Two paths, both ending at `SetWorldMatrix`: `FUN_10578e60` composes the root
quaternion onto the entity's, and `FUN_10767de0` does `yaw += rootEuler[2]`.
`ANIMATION.md` documented only the translation side. Path 2 is gated on `CPawn`
(humanoids); animals are `CAnimal`, a sibling under `CPawnBase`, so **path 1 is
the one that applies to creatures** — though "animals carry
`CAnimDrivenComponent`" is flagged by the trace as **inferred, not verified from
data**.

### E. What shipped, and what did not

**Shipped:**

- `drivelock agent` — the `+0x1C4` gate, plus per-frame stale look-at clearing,
  plus restore in `DriveStop` so neither an unload nor a stalled detour can leave
  a permanently deaf creature behind.
- `driveturn [n|off]` — **probe 1**. Clamps `CAnimal+0x144`
  (`fNormalMaxAngularVelocity`) and `+0x148` (`fScaredMaxAngularVelocity`) to
  zero and restores on demand. `CAnimal` carries a full spring-damper rotation
  controller the humanoid path does not have; its consumer was never traced, so
  this is a probe. If clamping stops the swivel, that is the whole answer in one
  write; if it does not, the controller is eliminated.

**Not shipped — probe 2, hooking `0x101b4310` to log return addresses.** It is
the single most decisive probe available and I did not build it, because it is
**not cheap**: `0x101b4310` is a plain function, not a vtable slot, so it needs
an inline trampoline — stolen prologue bytes, a relocated stub, a `JMP` patch, a
byte-signature check, and removal on unload. This file has never done an inline
hook (the closest is a one-byte `.text` poke), and §3.1 lists six real
unload-path crashes it has already paid for. Writing that machinery quickly, for
a hook on a function called for every entity every frame, is how a seventh gets
added. It should be built deliberately, with the entity-pointer filter applied
before anything else so the common case is one compare and a return.

### 12.9 Test order, revised again

| # | Do this | What it tells you |
|---|---|---|
| 41 | `drive`, let it swivel | baseline |
| 42 | **`driveturn 0`** | probe 1, and the cheapest possible whole answer. Stops swivelling ⇒ the turn is rate-limited by `CAnimal`'s controller |
| 43 | **`drivelock agent`** | the engine's own gate. Still turns ⇒ the turn is downstream of the agent, i.e. root motion |
| 44 | `drivelock last` | FACING Lever 1 |
| 45 | `drivelock aim` | FACING Lever 2 — best case, it faces where you look |
| 46 | `drivelock soft` / `hard` | the bisects. Ordering is already correct, so these test the *body*, not the timing |
| 47 | Under every level, check WASD still steers | `drivelock agent` deliberately does not clear `ctrl+0x0C` for this reason |
| 48 | `driveturn off`, `drivelock off`, then `End` | both restores must fire; log shows `+0x1C4 restored` and no `[exit] *** … STILL ours` |
| 49 | `drivelock agent`, then stop driving without turning it off | `DriveStop` must restore the byte — the creature must not be left deaf |

---

## 14. The game's own health bar — NOT reachable, and what is actually there

The request was to stop drawing our own bar and instead drive the engine's, "how
the game exactly does it… but for the creature". The honest answer is that this
cannot be done by calling anything, and the reason is structural rather than a
gap in the search.

### 14.1 The player HUD is Scaleform GFx, not engine drawing code

There is no C++ "draw the health bar" function to call. The HUD is a Flash movie,
and the entire C++ → Flash surface is `InvokeParsed` against named ActionScript
paths of the form `_ingameHUD.*`.

**The complete set of those paths, grepped out of the whole 66 MB decompile
(`grep -oh '_ingameHUD\.[A-Za-z0-9_.]*' | sort -u`), is 34:**

```
_ingameHUD.ActivateCommand              _ingameHUD.notifications.Hide
_ingameHUD.InGame_SetMode               _ingameHUD.notifications.MissionNotification_Change
_ingameHUD.dialogue.ActivateCommand     _ingameHUD.notifications.MissionNotification_Hide
_ingameHUD.hud.Ammo_Ring_Hide           _ingameHUD.notifications.ObjectiveNotification_Show
_ingameHUD.hud.Ammo_Ring_Show           _ingameHUD.notifications.QuestNotification_Complete
_ingameHUD.hud.Ammo_Ring_setIcon        _ingameHUD.notifications.SetOutOfBoundWarningTimer
_ingameHUD.hud.setRingMode              _ingameHUD.notifications.Show
_ingameHUD.hud.skill_SetActivated       _ingameHUD.notifications.TutorialPanel_Close
_ingameHUD.notifications.Combo_Finisher_Hide     ... TutorialPanel_Open
_ingameHUD.notifications.Combo_Finisher_Show     ... ZoneName_Hide / ZoneName_Show
_ingameHUD.notifications.Combo_Finisher_setActive  ... _comboBtn / timer
_ingameHUD.notifications.Combo_setChainedHits   _ingameHUD.scanner.Close / Open / setDetails
_ingameHUD.notifications.ContextNotice_Icon     _ingameHUD.setAwareState
_ingameHUD.notifications.ContextNotice_Key      _ingameHUD.setCinematicSkip
                                                _ingameHUD.setMiniMapBack
```

**Not one of them is health, vitality, or a bar.** There is a ring
(`setRingMode`, `Ammo_Ring_*`), skills, scanner, notifications, subtitles,
minimap — and no health entry point. This is an enumeration of the whole surface,
not a failed search for a name I guessed.

### 14.2 The other mechanism does not help either

Scaleform also allows `SetVariable` instead of `Invoke`. Grepping the decompile
for it finds **two** occurrences and **both are inside the GFx runtime's own
error strings** (*"SetVariable failed: can't resolve the path"*, *"NULL pathToVar
passed to SetVariable/SetDouble()"*). The game does not push HUD values that way
through any path we can see.

`m_fCurrentVitality` exists as a property-name string at `0x102e7b40`, so vitality
is a named property on the C++ side — but the binding that carries it into the
Flash movie is not exposed as a callable path.

### 14.3 So the bar lives in data, not code

The health display is authored inside the `.gfx`/`.swf` asset. Driving it for a
creature would mean: editing that Flash asset to add a second bar, giving it an
ActionScript entry point, repacking it into the patch folder, **and** adding a
C++ `InvokeParsed` call for the new path. That is a Flash-authoring project with
an asset-pipeline dependency, not a HUD change — and `D:\Games\Avatar The Game\`
is read-only, so the asset would have to go through `patch.pak`.

**Stated plainly, as asked: the game's own health bar is genuinely unreachable by
calling it. I have not quietly fallen back to custom drawing — the custom bar was
removed in `53d19d8` and nothing replaced it.** If a creature health readout is
still wanted, the three routes are: a line in the existing controls panel (cheap,
consistent with what was just restored), the Flash-asset project above, or
reinstating the custom bar. That is the owner's call, not mine.

### 14.4 For the engine-map agent — HUD/UI binding names

Flagged as their current main blocker, so recording it here:

- **The 34 `_ingameHUD.*` ActionScript paths above are UI binding names.** They
  are string literals in the decompile and should feed the CRC/name dictionary
  directly.
- `0x1000EE10` = **`wrap_RtlEnterCriticalSection`**, and `CConsole` holds its
  critical-section pointer at **`+0x88`** — that offset is likely shared by other
  lock-bearing engine objects, and it is what made the crash in §15 diagnosable.
- `0x100AC0C0` = **`CConsole::Printf`** (already `FN_PRINTF` in the DLL, now
  cross-confirmed from the symbol map).

---

## 15. The Escape-while-driving crash — cause, not guess

Both `Crash 1.txt` and `Crash 2.txt` are the same crash, and it is fully
explained. Resolving the addresses against `ENGINE_MAP/SYMBOLS.tsv` rather than
reading them raw was the step that cracked it:

| address | symbol |
|---|---|
| `0x1000EE10` | `wrap_RtlEnterCriticalSection` — the fault site |
| `0x100AC0C0` | `CConsole::Printf` — **which is this file's `FN_PRINTF`** |
| `0x100AC196` / `0x100AC1A5` | return addresses inside it |
| `0x100AB660` | STL `char_traits::assign` — the string work Printf does |
| `0x100EDDC0` | `Mem_Free` |

`CConsole::Printf` is not null-tolerant: its first act is to take the console's
own lock, loading the critical-section pointer from `[this+0x88]`. With
`this == NULL` that reads address `0x88` and faults. Every register matches:
`ESI=0` (the NULL `this`), `ECX=0x88` and *"reading address 00000088"*,
`freecam=1 drive=1` (the Escape-while-driving branch, which calls `DriveStop(0)`),
and `[drive] combat resumed` — `AgentCombat(1)`, a few statements above the
offender — as the last line before it.

The byte-identical register file across both crashes is explained rather than
merely noted: a fixed code path reaching a **literal** NULL, not a race and not
corruption.

**The offender was mine.** `DriveStop` ends with `DriveTurnSet(0, 0, 0.0f)`, and
that function's restore path opened with an unconditional
`P_(console, 0, AC "driveturn: restored\n")`. Added in `6371679`. `DriveStop`'s
own prints were already guarded and its header even warns that `console` is NULL
on the unload path; the new helper simply did not get the same treatment.

Fixed in `b3dd212`: every print in `DriveTurnSet` gated, `FaceHookSet` gated the
same way (it is also called with a NULL console and was safe only because
`on == 0` returns early — luck, not design), and the rule written at `DriveStop`
where the NULL originates.

The `[wdog] frame loop STALLED` line after each crash is the watchdog noticing
the thread died. Symptom, not a second bug.

---

## 16. The HUD work is REMOVED — what stays, and what must not be re-investigated

The owner's decision on §14.3 was **none of the three options: drop the creature
health readout entirely**, and then further — strip the other HUD additions too.
Target end state, now shipped: **the original single controls panel, bottom
right, plain F6 toggle, and nothing else on screen.**

### 16.1 What came out

| Removed | Was added in |
|---|---|
| the creature health bar and its artwork (`hud_draw.h`, `hud_preview.c`, `build_preview.bat`) | `7bb624e`, `4fa7aad` |
| `g_hudHpPct` and the 10 Hz main-thread health sampler in the detour | `7bb624e` |
| the two HUD fonts and their teardown | `7bb624e` |
| `OverlayPaintHud` and its change-gate state | `7bb624e` |
| the free-camera speed panel: `FreecamHudLines`, and the `OverlayPaintPanel(mode)` two-builder refactor | `53d19d8` |
| the design-variant harness: `hud_variants.h`, `hud_variants.c`, `build_variants.bat`, `make_sheet.py`, the `out/` ignore and the `out/` directory | `8088eca` |

`OverlayPaintDrive` and `DriveHudLines` are now **byte-identical to their
pre-HUD versions** (diffed against `7bb624e^`), and the paint caller is back to
`g_ovlOn && g_drive && g_hudOn`. Nothing orphaned was left behind — no helper,
no font, no state, no harness file.

Kept deliberately: `design_refs/` (the mockups and the rejected-variant sheet).
Those are the record of a decision, not build input, and nothing includes them.

### 16.2 Two fixes that had to survive the strip, and did

Both lived in commits that also contained work being removed, so they were
verified explicitly after the strip rather than assumed:

1. **The null-`console` crash fix** (`b3dd212`). `DriveTurnSet` — 5 guarded
   prints, 0 unguarded. `FaceHookSet` — 5 guarded, 0 unguarded. `DriveStop`
   still calls `DriveTurnSet(0, 0, 0.0f)`, and that call is still safe.
   **Repro path to re-check in game: `drive` → `freecam` → Escape.**
2. **The F6 regression fix** (`53d19d8`). F6 is a plain two-state toggle
   (`long v = g_hudOn ? 0 : 1;`), not a three-way cycle. The controls panel is
   there on the first press.

### 16.3 DO NOT RE-INVESTIGATE THIS — the negative result stands

§14 is kept in full, and this is why. **The game's own health bar is unreachable
from code.** That was established properly and it cost real work:

- the player HUD is **Scaleform GFx**, not engine drawing code, so there is no
  C++ "draw the bar" function to call;
- the entire C++ → Flash surface is `InvokeParsed` against named ActionScript
  paths, and **all 34 `_ingameHUD.*` paths were pulled out of the full 66 MB
  decompile and enumerated** in §14.1. **Not one is health, vitality or a bar** —
  there is a ring, skills, scanner, notifications, subtitles and minimap, and no
  health entry point. That is an enumeration of the whole surface, not a failed
  search for a guessed name;
- the alternative mechanism does not help either: `SetVariable` appears twice in
  the decompile and **both occurrences are inside the GFx runtime's own error
  strings**;
- `m_fCurrentVitality` exists as a property name at `0x102e7b40`, but the binding
  carrying it into the movie is not a callable path.

The bar is authored inside the `.gfx`/`.swf` asset. Driving it would mean editing
that Flash asset, giving it an entry point, repacking through `patch.pak` and
adding a C++ invoke — a Flash-authoring project with an asset-pipeline
dependency, not a HUD change.

**The owner has chosen to drop the feature rather than take any of those routes.**
If it is ever revisited, start from §14, not from scratch.

§14.4 (the `_ingameHUD.*` binding names, `wrap_RtlEnterCriticalSection` at
`0x1000EE10`, and `CConsole`'s critical section at `+0x88`) also stays — it has
been passed to the engine-map agent, whose CRC dictionary was blocked on exactly
those UI names.

### 16.4 Superseded sections

§13 (the bottom HUD) and its runtime tests 51–60 describe code that no longer
exists. §13.1's *method* — factoring the drawing into a header so a standalone
`.exe` can render it offline — remains the right technique if any custom drawing
is ever wanted again, and §13.2's reasoning about why a claw needs Béziers rather
than stacked ellipses is preserved in `4fa7aad` and `8088eca`. The colour finding
is worth keeping in mind independently of all of it: **vivid orange lerped to
vivid pink crosses red at its midpoint**, which is why every one of the 15
variants read red, and why the chosen mockup's purple → magenta → pink is a short
arc that stays vivid.
