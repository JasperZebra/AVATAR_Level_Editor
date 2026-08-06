# avatar_console.dll — working console command execution

**Status: WORKING.** Arbitrary console commands execute in the live game, verified
numerically. The console window also **opens** — the first time that code has run
in this build's history. Text rendering inside the panel is still unsolved.

---

## The one-paragraph version

Retail deleted the console's *toggle*, not the console. `toggle_console` is
received, hash-matched, and branched straight to a bare epilogue. But the whole
interpreter is intact and ticking: `g_console` exists, its UI object carries the
right vtable, and `CConsole::UpdateUI` runs every frame. So we hook that
per-frame call, and from inside it — on the **main thread**, which is the part
that matters — we call the engine's own `ExecuteLine`. No window required.

## Usage

```
build.bat                      build (32-bit, MSVC). Writes TWO identical
                                 files into dist\:
                                   avatar_console.dll  for inject.py
                                   dinput8.dll         for the drop-in
dist\install.bat               copy dinput8.dll into <install>\bin - then
                                 just start the game.
python dist\inject.py          inject into the running Avatar.exe
python dist\inject.py --status report what is loaded, change nothing
```

## Layout

The root holds only what it takes to BUILD, so the file you edit is not buried
in the files it produces:

```
avatar_console.c        the mod - one file, all of it
console_cmds_seed.h     generated, #included: the tab-completion seed
mp_spawns.h             generated, #included: multiplayer spawn points
check_cmds.py           the build gate - fails the build when the dispatch
                          chain and kOurCmds[] disagree
build.bat               builds into dist\

dist\                   build outputs, and the two ways to load them
tools\                  generators and probes; not needed to build
data\                   command lists and dumps read at runtime, not compiled
docs\                   this file, DISTRIBUTION.md, CRASH_ANALYSIS.md,
                          MULTI_INSTANCE.md, CHANGES_MERGE_NOTES.md
archive\                old logs and superseded copies
design_refs\            UI mock-ups
```

**Two ways in, one binary.** Dropped into the game's `bin\` folder as
`dinput8.dll` the game's own loader picks it up at startup — `Dunia.dll` imports
`DirectInput8Create` from it, and all six exports are forwarded straight through
to the real `SysWOW64\dinput8.dll`. The DLL reads its own file name in `DllMain`
to decide which mode it is in, so the two paths cannot drift apart. Injection
stays the better loop while developing: rebuild and re-inject without restarting.
Never use both at once — two copies means two sets of hooks on one vtable slot.
The full reasoning, and why not `d3d9.dll`, is in **DISTRIBUTION.md**.

Auto-loaded, the DLL starts before the main menu, waits (with no timeout) for a
level to exist, and never unloads itself — `End` disarms it but the image has to
stay resident, because Dunia's import thunk points into it.

## Two copies of the game at once

Dropped in as `dinput8.dll`, the DLL can also open the game's single-instance
gate, so you can host on one copy and join on another for solo multiplayer
testing. It is opt-in: create an empty `bin\avatar_multi.txt`, and delete it to
go back to stock. No game file is modified either way.
**MULTI_INSTANCE.md** has the whole thing — the three separate gates, the
disassembly, and the troubleshooting table.

## If someone else is editing avatar_console.c

**CHANGES_MERGE_NOTES.md** lists exactly which regions of the file the
multi-instance work touched and which it did not, so two people can merge
without reading 20,000 lines. Short version: one new contiguous block, two lines
in `DllMain`, and two lines at each of three unload paths.

| Key | Action |
|---|---|
| **F11** | run every line of `avatar_cmds.txt` |
| **F12** | self-verifying smoke test (see below) |
| **F9** | open the console panel (`SetUIActive(1)`) |
| **F10** | close it |
| **Pause** | **PANIC** — close console *and* release the mouse cursor |
| **Delete** | `CConsole::Printf` text test |
| **End** | close console, free cursor, unload the DLL |

`avatar_cmds.txt` is the command line into the game: edit it in any text editor,
press F11, no rebuild. All output goes to `avatar_console_dll.log` next to the DLL.

## Confirmed working commands

```
cheat_GodMode 1        works
ai_IgnorePlayer 1      works
env_Hour 2             works (time of day visibly changes)
cheat_UnlimitedAmmo 1  EXECUTES - the value is set to 1 - but the flag is inert
                       in Avatar (dead Far Cry 2 leftover, like the rest of that family)
```

The distinction matters: **command dispatch working and a given flag doing
something are separate questions.** Confirm the former by reading the value back,
not by looking for an effect.

## How it works

**VTable swap, not an inline hook.** The engine calls `UpdateUI` virtually
(`mov ecx,[0x111CA4B4]` then `call [vtable+4]`), so we replace one function
pointer — no trampoline, no byte patching, no relocating the relative `je` in the
prologue, no MinHook dependency. `InstallHook` verifies `vtable[1]` really is
`0x100A75E0` and aborts if not.

**Threading contract.** The hotkey thread never touches engine state; it only
pushes strings onto a lock-protected queue. The detour — main thread, once per
frame, `ECX` already holding `g_console` — pops and executes. An earlier attempt
called the dispatcher from a `CreateRemoteThread` thread and crashed the game
instantly.

**The call idiom** (the engine's own, byte-identical to code at `0x100AE6E7`):

```c
unsigned char s[0x20];
((fnStrCtor )0x10003E20)(s, line);   // DuniaString::ctor(const char*)  thiscall
((fnExecLine)0x100AE5F0)(console, s);// CConsole::ExecuteLine           thiscall
((fnStrDtor )0x10EC2F90)(s);         // DuniaString::dtor               thiscall
```

## Addresses (Dunia.dll at its preferred base `0x10000000` — verified live)

| Address | What | Convention |
|---|---|---|
| `0x111CA4B4` | `g_console` (pointer) | — |
| `0x100A75E0` | `CConsole::UpdateUI(float)` — vtable slot 1 | thiscall, `ret 4` |
| `0x10003E20` | `DuniaString::ctor(const char*)` | thiscall |
| `0x10EC2F90` | `DuniaString::dtor()` | thiscall |
| `0x100AE5F0` | `CConsole::ExecuteLine(DuniaString*)` | thiscall |
| `0x100AE650` | `CConsole::ExecBatch(DuniaString*)` — name needs `.console` | thiscall |
| `0x100A7790` | `CConsole::SetUIActive(bool)` | thiscall |
| `0x100AC0C0` | `CConsole::Printf(this, int flags, fmt, …)` | **cdecl** |
| `+0x78` | `g_console->m_pUI` | — |
| `+0x69` | `g_console->m_bUIActive` | — |
| `pUI+0x58` | state: 0 opening, 1 closing, 2 idle | — |
| `pUI+0x5C` | panel height (300 when open) | — |

## The smoke test, and why it is shaped that way

F12 does this **inside a single frame**, so no ambient state can interfere:

```
write GodMode = 0        (force a known state)
ExecuteLine "cheat_GodMode 1"
read GodMode             -> 1 means the console interpreter processed the line
```

It then does a control write to prove the field is writable, so a FAIL can only
mean ExecuteLine didn't process the line.

**This design exists because of repeated false results.** Do not smoke-test with
`gfx_ShowFPS`, `qc_ShowPlayerPos`, or the `Cheat_*` family — all confirmed dead in
this build, so "nothing happened" would tell you nothing. Always test with
something whose storage you can read back.

## Known-good build recipe

Two traps, both encoded in `build.bat`:

* **Use `vcvarsall.bat x86`, not `vcvars32.bat`.** On this machine vcvars32 fails
  (`vswhere.exe is not recognized`) and silently leaves an **x64** environment.
* **Compile as C++ (`/TP`).** `__thiscall` is a C++ calling convention; MSVC
  rejects it in C mode with a wall of `syntax error: missing ')' before '*'`.

Confirm the output says `14C machine (x86)`.

## Current limitation — the panel draws, the text does not

`SetUIActive(1)` opens the panel (height 300, `m_bUIActive=1`, guard `0 → 1`) and a
translucent band is visibly drawn. But there is **no text, no prompt, no cursor**,
and typing shows nothing. `Printf` with flags 0–3 produced no visible output and
no crash.

Not the cause: font/resource handles at `pUI+0x80..0x8C` read `4 / 0 / 3 / 1`
(populated, not null) and the 2D debug-text service `[0x1121E13C]` is non-null.

One live observation worth following: the `OnSignal` guard `[0x1125AE90]` read `0`
in every prior measurement and reads `0x7FFFF` after typing — so keystrokes may
now be reaching `CFCXConsole::OnSignal`. **Treat that value with suspicion** until
someone confirms what that variable is.

### RESOLVED: nothing gates it — and the `+0x38` fix is FALSIFIED

A focused RE pass established that **nothing in `Draw` suppresses the text**. Its
only text-gating branch (scrollback line count, `0x10EF2E8A`) is open, and the
prompt / input line / cursor draw unconditionally. Confirmed live:

* **`Printf` output really is in the ring** at `g_console+0x0C` — the literal
  `"DEVACCESS printf test…"` was read back out of it. Same buffer `Draw` reads.
* **Typing already works** — keystrokes were found in `pUI+0x60` with the cursor
  at `+0x7C` and the input context registered. `[0x1125AE90] = 0x7FFFF` is benign:
  it is a full 19-bit magic-static bitmask, not a corrupt value.
* **`pUI+0x80..0x8C` are not font handles** — they are two `{slotIndex, tag}`
  pairs for render-primitive pools. `+0x84 = 0` is a release tag.
* **`Draw` is queuing glyphs** — the console's batch grew to ~3072 entry slots
  while all 28 other text-pool slots stayed pristine.

So the break is strictly **downstream**: the batch is queued and never rasterised.

**Batch addressing (verified live, needs THREE dereferences):**

```c
unsigned char** inner = *(unsigned char***)(0x11178C68 + 8);  /* DEREF 1 */
unsigned char** base  = *(unsigned char***)inner;             /* DEREF 2 */
unsigned char*  batch = base[ *(int*)(pUI + 0x80) ];          /* DEREF 3 */
```

A one-dereference form yields `inner[4] = 0x1D`, which is the pool's registered
**slot count (29)** at `inner+0x10`, not a pointer — dereferencing it crashes the
game. The pool is also **double-buffered**: `base[idx]` alternates between two
objects each frame.

**The `-1.1f` hypothesis was tested and FAILED.** `CFCXConsole::Update` writes
`-1.1f` to the text batch's `+0x38` while the visibly-rendering quad batch gets
`-1.0f`; ctor default is `0.0f`. Overwriting it with `0.0f` (and with `-1.0f`),
every frame after `Update`, on the correct validated pointer with the field gate
satisfied, produced **no text and no crash**. The field is real and the anomaly is
real, but changing it does not make the text render.

**Do not retry this.** There is no consumer-side evidence for `+0x38`; nobody has
found the code that reads it.

**The rasteriser does exist** — `CSceneDebugTextRenderer` (ctor `0x1040A5F0`) has
exactly one live instance at `0x1853BD00` with its `"DebugText"` shader handle
resolved. And the `gfx_ShowFPS` / `qc_ShowPlayerPos` overlays prove nothing about
it: those CVars are inert and never fill a batch, so their producer never runs.

**The one open question**, read-only and unanswered: does the renderer consume the
*pool's* batches (the console's slot 4) or only its own `CDbgTextBatch` embedded at
`+0xA4`? Its dispatch is not a normal vtable, so the draw entry point must be
found another way. Until that is answered, the output pane stays dark — but
`ExecuteLine` plus reading the ring buffer directly is a complete substitute.

## Hard-won operational rules

* **Every state change ships with its inverse in the same build.** Shipping
  `SetUIActive(1)` with no close left the user with an open console, no input, and
  a mouse trapped in the window.
* **`GetAsyncKeyState`'s low bit is consumed by the read.** Calling it twice for
  the same key in one loop pass makes the second read miss the press — this made
  the open key fire erratically. Sample each key exactly once per pass.
* **Avoid toggle keys** (ScrollLock, NumLock, CapsLock) for hotkeys; they carry
  their own OS-level state.
* **Release the cursor on every close path.** The game clips the mouse.
* Never call `0x100ADD80` / `0x100AE5F0` / `0x100AE650` / `0x100A7790` from a
  thread you created — main thread only, via the detour.
* Do not patch `Dunia.dll` on disk. Nothing is encrypted, the base is fixed, and
  every change needed is a call, not a byte.
