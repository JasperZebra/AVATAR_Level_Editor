# What to ship

## The bundle — ONE file

```
dinput8.dll          the mod. That is the entire bundle.
README.txt           keys + requirements (write from the section below)
```

Copy `dinput8.dll` into `<install>\bin`, next to `Avatar.exe`. Start the game
normally. Uninstall by deleting that one file.

There is nothing else because there is nothing else to lose: the 722-name
Tab-completion list, the multiplayer spawn points and the command tables are all
compiled into the binary, and the DLL has **no data file it requires to
function**. `install.bat` does the copy for you and refuses while the game is
running; the copy is all it does.

### Why it loads by itself — and why `dinput8.dll`

`dumpbin /dependents` on the shipped binaries:

```
Avatar.exe  ->  Dunia.dll  MSVCR80.dll  KERNEL32.dll  dvm.dll
Dunia.dll   ->  WS2_32 KERNEL32 USER32 GDI32 ole32 OLEAUT32 MSVCP80 gdiplus
                MSVCR80 dbghelp DINPUT8 d3d9 d3dx9_41 XINPUT1_3 PSAPI binkw32
                X3DAudio1_6 DSOUND ADVAPI32 SHELL32 WINMM IPHLPAPI WININET dvm
```

Nothing the *exe* imports can be proxied — `Dunia.dll` and `dvm.dll` are the game
and its DRM, `MSVCR80` is resolved through a side-by-side manifest so a loose copy
is ignored, and `KERNEL32` is a KnownDLL, taken from a pre-mapped section object
without ever looking in the application directory.

From Dunia's list, `dinput8.dll` is the right target: it is a plain Windows DLL,
always present in `SysWOW64`, not a KnownDLL, so the application directory —
`bin\`, where `Avatar.exe` lives — is searched first and our copy wins. It has six
exports, all by name, and Dunia imports exactly one of them, `DirectInput8Create`.
All six are forwarded to the real `C:\Windows\SysWOW64\dinput8.dll`, so DirectInput
keeps working normally; the mod starts on its own thread from `DllMain`.

`d3d9.dll` and `xinput1_3.dll` were the alternatives and are worse: d3d9 has
ordinal-only exports that differ between Windows versions, and xinput1_3 ships
with the DirectX redistributable rather than with Windows, so on a machine that
never installed it there is no real DLL behind the proxy at all.

The DLL itself imports only `KERNEL32`, `USER32` and `GDI32` — it is built with
the static CRT, so there is no Visual C++ redistributable to install. This matters
more than it used to: as a load-time dependency of `Dunia.dll`, a missing
dependency of *ours* would stop the game from starting at all.

### The old way still works

`build.bat` writes two files that are byte-for-byte identical:

```
avatar_console.dll   for inject.py - inject into a running game
dinput8.dll          for the drop-in - the game loads it at startup
```

The DLL reads its own file name in `DllMain` and behaves accordingly, so there is
one binary and one source, and the two paths cannot drift apart. Injection is
still the better loop while developing: you can rebuild and re-inject without
restarting the game, and `End` unloads cleanly.

**Do not use both at once.** Two copies in one process means two sets of hooks on
one vtable slot, and that is not survivable. `inject.py` now detects a `dinput8.dll`
loaded from the game's own folder and refuses.

### What changes in proxy mode

* The DLL starts at **process creation**, long before a level exists. It waits —
  with no timeout — for the console object, logging a heartbeat every so often.
  Menus and intro videos are not an error. The mod arms itself when a level loads.
* It **never unloads itself**. Dunia's import thunk points into this image, so
  `FreeLibrary` would unmap the code that thunk jumps to and kill the game on the
  next DirectInput call, silently. `End` still removes every hook and stops every
  thread — the mod goes inert — but the image stays resident. Restart to re-arm.
* `g_dir` is the folder the DLL sits in, which is now `bin\`. The log,
  `avatar_cmds.txt` (F11), `console_cmds.txt` and `console_dump.txt` all live
  there.

## The old bundle — inject.py

```
avatar_console.dll   the mod itself
inject.py            run this to inject
console_cmds.txt     OPTIONAL. Additive Tab-completion cache; the same names are
                     compiled in, so deleting it costs nothing.
avatar_cmds.txt      optional: commands run by F11
README.txt           keys + requirements (write from the section below)
```

`spawn_names.txt` and `spawn_known.txt` are no longer part of this. `spawn_list`
reads the **live** archetype table — the file-based version could only offer names
from the full library, most of which do not exist on any given map, which is
confidently wrong rather than merely empty. `spawn_known.txt` is still consulted
if present (it gates `spawn` on "does any level register this name"), and its
absence still means "do not block anything", exactly as before.

`console_cmds.txt` is one command name per line, seeded from static analysis of
the binary so Tab works the moment the DLL is injected. **F10 merges into it and
never removes anything**, so running `?` on a level that registers `domino_*`
commands adds them permanently, for every future session.

Completion used to be rebuilt from `console_dump.txt`, which F10 writes from
whatever is in the console ring at that instant — press F10 when the ring holds
`?` output and you get 443 names, press it after some other output has scrolled
past and you get four, permanently. `console_dump.txt` is now only what its name
says, a readable dump of the scrollback; it can add names but never take any
away.

**Ship the Python script, not a compiled injector.** An unknown `.exe` that
injects into a game process is indistinguishable from malware at a glance, and
no README will overcome that. `inject.py` is ~200 readable lines using only the
standard library (`ctypes`) - anyone suspicious can read exactly what it does
before running it. That auditability is worth more than saving users a Python
install.

With the injector, everything lives in one folder anywhere on disk and nothing at
all is copied into the game directory.

Either way, **no game file is modified**. The drop-in *adds* one file,
`bin\dinput8.dll`, and changes nothing that shipped: `Avatar.exe`, `Dunia.dll` and
`patch.pak` are untouched, and there is no registry key and no launcher shim.
Uninstalling is `del bin\dinput8.dll`.

## How a user runs it

**The drop-in:** copy `dinput8.dll` into `<install>\bin` and start the game.
That is all of it. No Python, no terminal, no timing.

**The injector**, still supported for development:

1. Install Python 3 (any recent version; **no `pip install` needed** - the
   script uses only the standard library).
2. Start Avatar and **load into a save** (not the main menu).
3. Run `python inject.py` in the folder. It prints the key list and injects.

`python inject.py --status` reports what is loaded and changes nothing - useful
for telling "it didn't inject" apart from "it injected but a key isn't working".

`End` in-game unloads cleanly and the game keeps running, so it can be
re-injected without a restart.

If `OpenProcess failed` appears, run the injector as Administrator.

## Requirements and limits — state these clearly to users

* **Avatar: The Game, PC, retail 1.02.** Every engine address is hardcoded for
  this exact build. Another version, another language build, or a different patch
  level will not work and could crash — the DLL verifies `CConsole::UpdateUI`'s
  vtable entry before hooking and aborts if it does not match, so the common case
  is "nothing happens" rather than a crash, but do not promise that.
* **`Dunia.dll` does not have to load at its preferred base any more.** Every
  engine address in the DLL is written against `0x10000000` (what the decompile
  shows) and rebased at startup by `actualBase - 0x10000000`. Vtable identity
  constants are rebased too — they compare against pointers the loader relocated,
  so a constant that stayed put would fail every integrity check closed.

  This was not always true. One launch put Dunia at `0x02290000` and the first
  hardcoded read crashed the game *on injection*, before the hook was installed —
  which reads to a user as "the mod is broken" rather than "your DLL moved". The
  log now states the base and the delta on every run, and refuses to continue if
  Dunia.dll is not loaded at all.

  One consequence for debugging: on a relocated load, `[CRASH]` lines report both
  the live address and its decompile-relative equivalent. Look up the second one.
* 32-bit DLL, matching the game. `inject.py` works from either 32- or 64-bit
  Python: it parses the target's own export table to find `LoadLibraryA`, rather
  than assuming its address matches the injector's.
* Windowed or borderless. The text overlay is a layered window, which **will not
  composite over exclusive fullscreen**.
* Writes `avatar_console_dll.log` and `console_dump.txt` next to the DLL. If the
  folder is read-only (e.g. Program Files), logging silently does nothing.

## Keys — for the README

```
F9          console (toggle)
Shift+F9    block game input while the console is open (on by default)
F10         dump scrollback to console_dump.txt, and reload Tab completion
F7          text overlay on/off
F8          noclip / free-fly
F11         run every line of avatar_cmds.txt
F12         self-test (verifies command execution really works)
Tab         complete command name   (Shift+Tab cycles backwards; `warp` and
            `modhelp` complete even before you have dumped the registry)
PgUp/PgDn   console CLOSED: fly speed    console OPEN: scroll scrollback
Up/Down     command history
Pause       RESCUE - force noclip off, close the console, give back the mouse
            and foreground. Works even when the game has stopped rendering,
            because it touches nothing but our own flags and Win32.
End         unload the DLL
```

Flight: `W A S D` along the camera's facing, `Space` up, `Left Ctrl` down,
`Shift` 4x speed, `Alt` quarter speed.

## Commands the DLL adds

`?` only lists commands the **engine** registered, so anything added here is
invisible to it. `modhelp` is the discovery path, and the console prints a
one-line pointer to it on the first frame after injection.

```
modhelp        list what the DLL adds
warp           usage + the single-player world names
warp list      every world name, grouped sp / mp / other
warp <world>   change world, the way the game does it
tp <x> <y> <z> move the player there (Z is up)
fixinput       reload the input bindings
spawn <arch>   create an entity in front of you
spawn! <arch>  same, skipping the safety check
spawn_list <t> search what THIS level can spawn (reads the live table)
spawn_all      merge the full archetype library into this level
vehenter       board the thing you last spawned
vehexit        get out
vehstatus      what am I in?
freecam        detached camera - the body stays put (toggle)
save           request the game's autosave
```

`freecam` uses the engine's own `Cameras.Camera.Free` archetype and its
`free_camera` action map, so the engine drives it: mouse looks, WASD moves, wheel
changes speed. It refuses while the camera stack is Locked (a cutscene owns it),
and **Pause also leaves it**, so there is no way to get stranded.

`vehenter` calls the same native the shipped mission graphs use to seat the player
(`vehicleusers.lua` → `VehicleUserGetIn`). It covers ATVs, the Scorpion, the AMP
suit and flying mounts alike, and camera/HUD/driver-controls follow on their own.
A wrong target no-ops rather than crashing. `warp` leaves the vehicle first,
because warping while seated is untested.

`save` requests the game's checkpoint autosave — **it overwrites your current
slot**, exactly like a checkpoint. There is no scratch slot; copy
`Documents\My Games\Avatar\Saved Games` if you want a fallback.

**`spawn` works, and the spawnable set is per level.** Retail loads the current
level's `entitylibrary.fcb`, never the full 3.7 MB one — so Hometree has Na'vi,
key NPCs and pets but barely any vehicles, while Plains of Goliath has AMP suits
and Scorpions.

`spawn_list` reads the **live archetype table** out of the engine rather than any
file, so it only ever shows things that will actually spawn on the current map,
and it names that map in its output. The engine clears and rebuilds that table on
every world load, so it is correct by construction on maps we never catalogued.
The walk is four pure reads per entry with no engine call in the traversal —
`spawn_list` cannot crash the game.

Archetype lookup is **case-insensitive**: the key is `crc32(lowercase(name))`. The
CRC column in `spawn_names.txt` is case-sensitive and is a label, not the runtime
key — do not use it as an index.

`spawn_names.txt` is now only a reference for browsing outside the game.

`fixinput` reloads the input action map. A world load tears it down and only the
engine's post-load operation puts it back; the symptoms of it being missing are
total — no movement, no camera, no pause menu. **`warp` no longer needs it**: the
engine's own path restores the bindings itself. `fixinput` is a manual escape
hatch, kept in case a session ends up in that state some other way.

`warp` exists because the stock `load_level` is **dead code** — it is registered
through the script template `Game:LoadLevel(%%)`, and `LoadLevel` is absent from
the `Game` registrar's 99 entries, so the console builds a Lua chunk that resolves
to nothing and the error path never prints.

`warp` calls the engine's own `GameChangeWorldDefaultSpawnPoint`, the same global
the shipped `domino\system\changeworld.lua` uses. That hands the whole
thirteen-operation context switch to the engine, so **the pawn is respawned at the
destination's default spawn point and the input bindings are restored
automatically**.

An earlier version called `CBTZGame::LoadWorld` directly and crashed, because that
function is child 3 of a 7-child composite that is operation 11 of the switch —
one leaf of a tree, with twelve other things left undone. If you find notes
elsewhere describing `warp` as crash-prone, they describe that version.

`warp` turns noclip off and leaves any vehicle before changing world — stale fly
coordinates carried into a new world dumped the player through the floor once,
and warping while seated is untested.

## Things worth telling users up front

* **`?`** lists every registered command; **F10** then saves that list to
  `console_dump.txt`, which also feeds Tab completion. The registry changes per
  level, so re-dump after loading a different map.
* Many commands are **inert Far Cry 2 leftovers** — `Cheat_godmode`,
  `Cheat_unlimitedammo`, `gfx_ShowFPS` and friends execute but do nothing. That
  is the game, not the mod. Confirmed working: `cheat_GodMode`, `ai_IgnorePlayer`,
  `env_Hour`, `env_TimeScale`.
* `domino_*` commands are **level-specific** — they only exist while the level
  that registers them is loaded.
* **Turn noclip off before changing level.** It auto-disables when it detects the
  player entity being rebuilt, but switching off first is the safe habit.
* Noclip moves the player with `CEntity::SetPosition`, which broadcasts to every
  component. An earlier build wrote the position field and hand-synced only the
  two physics proxies, which is what made the mesh lag behind and pop to catch
  up. If the log says `FALLBACK: raw write + proxy sync`, that older path is
  live and the lag may return.

## Building from source

`build.bat` produces both binaries. Two traps are already handled in it and worth
keeping if anyone ports this:

* Use **`vcvarsall.bat x86`**, not `vcvars32.bat` — the latter fails on some
  installs (`vswhere.exe is not recognized`) and silently leaves an x64
  environment, which then rejects `__thiscall` with a wall of syntax errors.
* Compile as **C++ (`/TP`)** — `__thiscall` is a C++ calling convention and MSVC
  will not accept the function-pointer typedefs in C mode.

Confirm the output says `14C machine (x86)`.

## Legal / practical note

This is a single-player-only tool that modifies nothing on disk. It injects into
a running process, which is inherently the kind of behaviour antivirus looks for.
Shipping the injector as readable Python rather than a binary substantially
reduces false positives and lets a cautious user verify it themselves - say so in
the README rather than letting people wonder.
