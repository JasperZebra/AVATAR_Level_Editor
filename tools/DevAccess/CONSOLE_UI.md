# Why the Avatar (2009 PC) developer console UI is dead — and the concrete path to reviving it

Scope: this file only covers the **console window** (the `~` overlay). The *command system* behind it
is alive and reachable today by three other routes — see `DEV_ACCESS.md`. Do not spend effort on the
UI before reading that, because you probably do not need it.

---

## 1. What is definitively present (all CONFIRMED)

Offsets are file offsets into
`C:\Test\Tools\Decompiled DLL's\Avatar\PC\Dunia_Decrypted_DLLs\Dunia_Retail_1.02_decrypted.dll`.

### 1.1 The console's own help text — verbatim, in retail

```
0x01031418  To get the list of all available commands, type "?".
0x010313B0  To get more help about a specific command, type the command name followed by a space and "?" or "help".
0x01031338  To get a list of all commands starting with a specific prefix, type the prefix name followed by a space and "!".
0x010312B8  To auto-complete a command name (or get the next command name), press "Tab" ("Ctrl-Tab" to get the previous command name).
0x01031268  "pageup" and "pagedown" can be used to scroll up/down the console buffer.
0x01031588  Type "help" for more information.
0x010315AC  Shows help on using the console.
0x010317A4  Clears the console text buffer.
```

Nothing about this is stubbed. The identical block exists in the retail PS3 EBOOT (`0x0189ddf0`) and
both Xbox 360 SKUs.

### 1.2 The classes

| string | file off |
|---|---|
| `CConsoleService` | `0x0107BCA4` |
| `CFCXConsoleService` | `0x010130FC` |
| `CFCXConsole` | `0x0109B604` |
| `CFCXMultiPlayerConsoleService` | `0x010999E8` |
| `CFCXGRStateConsole` | (state-machine class list) |
| `CFCXGameModeConsoleNode` | `0x01098634` |
| `CDominoConsoleCommandManager` | `0x010467B4` |
| `RegisterConsoleCommand` / `UnregisterConsoleCommand` | `0x01046830` / `0x01046814` |

`FCXConsole` also appears as a **declared game mode** inside the shipped binary FCB
`Data\engine\gamemodes\gamemodesconfig.xml`, alongside `FCXSingle`, `FCXMainMenu`, `FCXBenchmark`
and `Editor`.

### 1.3 The registry is populated at engine init, unconditionally

Console elements are registered inside `CCryEngine::Initialize` @ `1018F9A0`
(decompile line 275666; the registration run is lines 276250–276420). Sample, with the exact
`(help, name)` pairing the compiler emitted:

```
FUN_10003590("Clears the console text buffer.", uVar5);   FUN_10003590("clear", uVar5);
(*DAT_1100038c)("console_dump_elements");                  FUN_10003590("console_dump_elements", uVar5);
(*DAT_1100038c)("snapshot_viewport");                      FUN_10003590("snapshot_viewport", uVar5);
(*DAT_1100038c)("render_menu_only");                       FUN_10003590("render_menu_only", uVar5);
FUN_10003e20("Evicts all managed resources (D3D and driver-managed)."); FUN_10003e20("evict_resources");
```

**There is no `if (developer)` around any of it.** Same for the game-side tables
(`FUN_1062D070` @ line 1027675 for `Game`, `FUN_1092DED0` @ line 1464586 for `BtzGame`).
This matches the earlier live finding (Cheat Engine, `Dunia.dll+11233978` → ~28 MB heap object packed
with command-name strings): the backend is genuinely alive.

### 1.4 The one-key shortcut presets are registered too

Stored command lines with their labels (`0x01031170`–`0x010316B4`):

| shortcut name | expands to | name string VA |
|---|---|---|
| `fps` | `gfx_showfps 2` | `0x11032A54` |
| `nolod` | `gfx_LodScale 0.001` + `gfx_KillLodScale 0.001` | `0x1103243C` |
| `gm` | `qc_ShowGeomTxtInfo 1` | `0x11032A0C` |
| `sm` | `qc_showmem 1` | `0x110329F0` |
| `tm` | `Qc_showtargetedMaterial 1` | `0x110329DC` |

(Several of the *targets* no longer exist — see `COMMANDS.md` §3 caveat. `nolod` targets do exist.)

### 1.5 The input side is fully wired, all the way to the engine

`D:\Games\Avatar The Game\Data_Win32\Data\config\inputactionmapcommon.xml`:

```xml
line 8    <Import file="Config\InputActionMapConsole.xml"/>
line 18   <ActionMap name="common_showconsole">
line 19       <Binding input="kb:~" action="press" signal="toggle_console"/>
line 20       <Binding input="kb:`" action="press" signal="toggle_console"/>
line 21       <Binding input="kb:J" action="press" signal="create_issue"/>
line 22   </ActionMap>
...
line 32   <ActionMap name="common_system" resendOnChange="0" >
line 37       <Import actionmap="common_showconsole"/>
```

`common_system` is the always-active system map. **The `~` keybind is delivered in every gameplay
state.** Verified by reading the file directly, base and `Patch\config\` copy — the patch copy differs
from base by exactly one added line (`mouse:lb → respawn` at line 258); nothing console-related
changed.

`Data\config\inputactionmapconsole.xml` (9959 bytes) is a **complete, intact console input map**:
`ActionMap name="console"` with copy/paste (`lctrl+c/v`), `console_ctrl` /
`console_ctrl_release`, Tab autocomplete, backspace/delete, `console_execute_buffer` (Return),
`console_clear_input` (Escape), Home/End, arrow-key history, PgUp/PgDn scroll,
`mouse:wheel → console_scroll`, and the full per-character `console_char_<x>` table.

The engine side matches exactly: **95 `console_char_*` signal names** are registered by a single
function at `.text` `0x10EF1200`–`0x10EF2A00` (name strings `0x01140A38`–`0x01140FFC`;
`scripts/code_strings_near.py 0xEF1200 0x1400` dumps the whole list). 93 of these also exist in the
PS3/X360 builds. So the console text-entry path is compiled in on PC.

The `"console"` action map is **never `<Import>`ed by any other map** — the engine activates it by
name when the console opens. That is normal design, not evidence of removal.

### 1.6 The console's font ships, and exists for nothing else

`Data\graphics\fonts\` contains **exactly two files**: `couriernew9x16.xbt` and
`couriernew11x18.xbt`, referenced by every world descriptor as
`<TempHack FontTex1="graphics/Fonts/couriernew9x16.xbt" FontTex2="graphics/Fonts/couriernew11x18.xbt"/>`.
All player-facing UI in Avatar is Scaleform. These two bitmap fonts exist solely for the
console / stats / `System:DrawDebugText2D` renderer. Supporting shaders also ship as sources:
`Data\engine\shaders\meta\debugtext.fx`, `debugline.fx`, `debugforcedcolor.fx`, `bbox.fx`,
`primitive.fx`.

---

## 2. What is *not* the gate — ruled out

| candidate | verdict | evidence |
|---|---|---|
| Console stripped from retail | **FALSE** | §1 above. Help text, 95 char signals, registry, classes, fonts all present. |
| `toggle_console` string missing ⇒ signal removed | **FALSE, and a trap** | The engine hashes signal names (`GamerProfile.xml` stores them as CRC pairs, e.g. `0x646CA0E7:0x1C630B12`). The *working* `ShowStartMenu` is equally absent as a literal. String-presence proves nothing either way. |
| `~` keybind not reaching the engine | **FALSE** | `common_showconsole` is imported by `common_system` (line 37) — confirmed by direct file read. |
| `EngineProfile.QcConfig.IsQcTester` | **NOT the gate** | Already tested by the project: flipped to `1` in `GamerProfile.xml`, edit persisted across launch, console still did not open. Note the shipped `GamerProfile.xml` already has `IsQcTester="1"` while `Data\engine\settings\defaultengineconfig.xml` has `"0"`. |
| PC build has less console code than console builds | **FALSE — it is the opposite** | 316/436 console-build dev tokens are present in the PC DLL. The 120 console-only tokens are all platform plumbing (`sys_ppu_thread_*`, SPU/stereo/sixaxis CVars). The `cheat_` reflection block is byte-identical across PS3, both X360 SKUs, and both PC DLLs. |
| Missing console Scaleform asset | **Unlikely** | No console `.gfx` exists in `Data\ui\flash`, but the console is not a Scaleform surface — it uses the bitmap fonts in §1.6. |

---

## 3. The actual gate — where it is, and why it is hard

`CConsoleService`'s constructor is at `LAB_107B1D50`. That address falls in a **DVM-protected
region**: `dvm.dll` (89 MB) contains no plaintext strings at all (`raw/pc_dvm_strings.txt` — zero hits
for any console identifier), and it decrypts/JITs `.text` ranges of `Dunia.dll` at runtime. Two
independent symptoms of the same thing:

1. The constructor's body is not usable in the static decompile.
2. A raw 4-byte reference scan of the on-disk image for the `0x0100F3A0`–`0x0100F450` flag strings
   (`-editorpc`, `-borderless`, …) finds **zero** referencing code, even though those strings must be
   read by something. Their handler is inside an encrypted range.

So the open-logic condition cannot be read statically. Everything below is therefore
**HYPOTHESIS**, ordered by strength.

### H1 (strongest) — the console requires a host process the retail launcher is not

`Data\engine\settings\defaultengineservicesconfig.xml` declares three distinct executables:

```xml
PCInGameEditorExecNamePrefix="fc2editor"
PCEditorExecNamePrefix="editor"
PCEngineExecNamePrefix="farcry2"
```

`Data\config\defaulteditorconfig.xml` (4872 bytes, shipped verbatim with live Ubisoft
infrastructure — `AssetStatusDB_Host="jake.mtl.ubisoft.org"`,
`helpURL="\\Ubisoft.org\Projects\farcry_x\Public\NomadDoc\index.html"`,
`Mail_Sender="Baltazar_Ed_User@avatar.org"`) contains `<GameMode id="FCXEditor" string="0"/>`.
`gamemodesconfig.xml` declares both `Editor` and `FCXConsole` as game modes.
The engine's internal name is **Nomad**; the build/branch is **Baltazar**; the PDB path leaked in
`Avatar.exe` is `d:\CastorVersion\AVATAR-PC-0075\baltazar\mainPC\bin\NomadLaunch_PC.pdb`, and the
X360 SKUs leak `d:\CastorVersion\AVATAR-Prod-0309\baltazar\main\...`.

Reading: `FCXConsole` is a **game-mode/state**, and retail `Avatar.exe` boots a mode graph that has no
transition into it. That is a much harder gate than a boolean — it is a missing state edge, not a flag.

### H2 — `ConsoleDeveloperOnly` is a per-element filter, not the window gate

The reflection attribute set at `0x01016E14`–`0x01016E90` is:
`UseInConfig`, `UseInProfile`, `ConsoleFloat`, `ConsoleInt`, **`ConsoleDeveloperOnly`**,
`ConsoleGroup`, `ConsolePrefix`, `ConsoleHelp`, `UseInConsole`.
These decorate *individual config fields*. `ConsoleDeveloperOnly` hides a CVar from a non-developer
console; it does not decide whether the console opens. Worth reading if you get the console open and
find CVars missing — not worth chasing first.

### H3 — a runtime flag set only by an absent code path

There is no `developer`, `devmode`, `IsDeveloper` or `bDev` string anywhere in the PC binaries
(only `ConsoleDeveloperOnly` as an attribute name). If the gate is a bool, it is set by
DVM-protected code, which means finding it needs dynamic work, not more string searching.

---

## 4. Concrete path to reviving it, cheapest first

### Step 0 — Do you actually need it? (do this first)

Everything the console can do is reachable without it:

* `Game:Exec("<batchfile>")` from injected Lua runs any `.console` batch, i.e. any console command.
* `BtzGame:*` (53 functions incl. `God`, `Kill`, `InventoryHack`, `MegaAmmo`, `SetHP`, `GiveXP`,
  `MapCheat`, `UnlockMetagame`) and `Game:*` (98 functions) are direct Lua calls.
* `Insert` / `Home` / `PgUp` already toggle debug views; `F6` already activates the free camera.
* L3+R3 on a gamepad already fires the `cheat_menu` signal.

See `DEV_ACCESS.md`. Reviving the console UI buys you *interactivity*, not *capability*.

### Step 1 — Dump the registry, so you know what the console would give you (no patching)

Create a batch file `dumpall.console` containing:

```
console_dump_elements
```

Place it at `Data\scripts\Console\dumpall.console` via the proven patch/repack route, then either
launch with `-exec dumpall` **or** call `Game:Exec("dumpall")` from an injected domino Lua node.
The engine writes `ConsoleElementsDump.txt` (name string `0x01031468`). That file is the
authoritative, complete command + CVar inventory with live types and defaults, which no amount of
static extraction can match.

### Step 2 — Break on the constructor, live (the only way to find the real gate)

This is the decisive experiment and it has not been attempted.

1. Attach a debugger after the DVM has decrypted the module (i.e. once the main menu is up).
2. Locate `CConsoleService` via the known global: `Dunia.dll+0x11233978` holds the pointer to the
   populated registry object (confirmed live previously).
3. Set a hardware breakpoint on the `toggle_console` signal handler. Find it by breaking on the
   signal-dispatch path with `~` pressed, or by breaking on reads of the console object.
4. Single-step the branch that decides not to open. Record the condition operand's address and value.
5. That address is the patch target. Report it as `Dunia.dll+<offset>` — **do not** derive an offset
   from the on-disk image, because the region is encrypted at rest and disk offsets will not match
   runtime.

Because the code is JIT'd/decrypted at runtime, a static byte patch to `Dunia.dll` on disk is
**not** expected to work. A runtime patcher (Cheat Engine script / DLL that waits for the module to
be decrypted, then flips the condition) is the realistic delivery mechanism.

### Step 3 — If Step 2 shows a missing game-mode transition (H1), stop

If the gate turns out to be "the current `CFCXGRState*` has no edge to `FCXConsole`", patching one
byte will not help; you would need to author a state transition, which is out of proportion to the
benefit given Step 0. In that case the correct answer is: **the console UI is not recoverable in
retail, but the console command system is fully usable via Lua.**

---

## 5. What was NOT tested (be honest about this)

* No live breakpoint on `CConsoleService` / the `toggle_console` handler.
* `-exec` was not run end-to-end; only the parse site and the executor were located statically.
* `Game:Exec()` was not run live; the registration and the executor are confirmed statically and the
  `Game:`/`BtzGame:` table names are confirmed against shipped `missiontools.lua`, but no in-game
  confirmation exists yet.
* No attempt to xref the `-editorpc` cluster or `LAB_107B1D50` in `Dunia_LIVE_DECRYPTED.dll` (the
  runtime dump), which would likely resolve several of the open questions cheaply and should be done
  next.
