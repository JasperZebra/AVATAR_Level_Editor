# How we got the developer console working — Avatar: The Game (2009), PC retail 1.02

*Short version, written to be shared. Everything here is from static analysis of `Dunia.dll` plus
read-only probing of a live retail process. Full detail is in `CONSOLE_GATE.md` and
`MAINTHREAD_HOOK.md`.*

---

## The one-sentence answer

**The console isn't locked — it's half-deleted.** The command interpreter is completely intact and
running in retail; only the code that *opens the window* was removed. So we don't open the window.
We call the interpreter directly from an injected DLL.

---

## What's actually wrong in the retail build

Three findings, each independently confirmed:

1. **The `toggle_console` key still works — it just does nothing.** The input signal is delivered to
   a live handler and explicitly matched by hash. The case body is *empty*: it jumps straight to the
   function epilogue and returns "handled." (`0x106363F2` → `0x1063630D`, which is just
   `pop/pop/mov al,1/pop/add esp,0x44/ret 8`.)

2. **`CConsole::SetUIActive(bool)` @ `0x100A7790` is called exactly twice in 16 MB of `.text`, and
   both call sites pass `false`.** There is no `SetUIActive(true)` anywhere in the binary.

3. **The open path has provably never executed in a real session.** `SetActive(true)` would set a
   magic-static guard byte at `0x1125AE40` on first run. It reads `0` in two independent live process
   dumps.

Meanwhile everything else is alive: `g_console` exists at `0x111CA4B4`, its UI object exists with the
correct vtable, and `CConsole::UpdateUI` is ticked every single frame.

So there is **no flag to flip and no branch worth patching** — patching that `je` gains you nothing,
because the case body doesn't exist. It's missing code, not a gate.

---

## What we do instead

Skip the window entirely. `CConsole::ExecuteLine` is fully live and has 57 call sites in the shipped
binary. We inject a DLL, swap one vtable entry so our function runs once per frame on the engine's
own thread, and feed command strings to the interpreter from there.

```c
#define G_CONSOLE_PTR   0x111CA4B4   /* void** g_console                    */
#define FN_UPDATE_UI    0x100A75E0   /* CConsole::UpdateUI(float) — vtable slot 1 */
#define FN_EXEC_LINE    0x100AE5F0   /* CConsole::ExecuteLine(DuniaString*)  */
```

That's the whole trick. Output comes back through the engine's own printf, so command results land in
`avatar_game.log` and in our overlay.

---

## The four things that cost us the most time

These are the ones worth stealing.

**1. Engine calls MUST happen on the main thread.** Our first attempt called the dispatcher from a
`CreateRemoteThread` thread and crashed the game instantly, every time. The fix is to hook something
the engine calls itself every frame. `CConsole::UpdateUI` @ `0x100A75E0` is the ideal target: called
once per frame, and on entry **`ECX` already holds `g_console`** — the exact `this` pointer you need,
with no lookup and no risk of reading a half-constructed global.

Our threading contract is: the hotkey thread never touches engine state, it only pushes strings onto
a lock-protected queue. The per-frame detour pops and executes them.

**2. Swap the vtable, don't patch bytes.** The engine invokes `UpdateUI` virtually — `mov
ecx,[0x111CA4B4]` then `call [vtable+4]`. Replacing one function pointer needs no trampoline, no byte
patching, and no relocating the relative `je` inside the prologue. Strictly less to get wrong. Save
the original pointer and restore it on unload — and if you ever hook more than one vtable, keep a
*registry* of every slot you patched, because "remember the last one" leaves live hooks pointing into
your DLL after it unloads.

**3. `dvm.dll` is DRM, not encryption.** We lost real time to the belief that parts of `Dunia.dll`
were JIT-decrypted and invisible to static analysis. They're not. The function we thought was
protected was plain, ordinary, fully readable x86 — **Ghidra just never defined a function there**,
having swallowed the range into an unrelated neighbour whose decompiled body stops long before it.
If a region looks encrypted, check whether your tool simply didn't disassemble it.

One real caveat: the **shipped** `Dunia.dll` has `PointerToRawData = 0` on `.text`, so there is
genuinely no code in that section on disk. Dump it from a live process and work from that.

**4. Every signal and action name in the engine is a plain zlib CRC-32 of the name.** Proof:
`0x10EF0E05` writes the literal `0x3603CFB6` into the static naming the `"console"` action map, and
`crc32(b"console") == 0x3603CFB6`. This makes every hashed name in the binary searchable.

Two consequences that bite:
- It's **case-sensitive**. A wrong name is not an error — it matches nothing, silently, and whatever
  you asked for just doesn't happen.
- The **name strings are not in the DLL at all.** We swept all 21 MB: `viperwolf_`, `tame_sign`,
  `forceidle` as text — none of it is there, in any encoding. The binary stores only the CRCs. The
  vocabulary lives in the data archives. So you can never validate a name table by string-searching
  the executable; you have to check it by CRC.

---

## Specifically for the multiplayer effort

Two things from our notes that may save you a detour. Both are in `MULTIPLAYER.md`.

**Loading an `mp_*` world from the console works, but does not give you a match.** `LoadWorld`
returns true and the MP terrain, geometry and `SpawnPoints.*.Multi` entities all come in — nothing in
`CXGame::LoadWorld` is `sp_`/`mp_`-aware. But the active game mode stays `FCXSingle`, so there's no MP
spawn point service, no player service respawn and no scoring. Decisively: **every one of the 10
game-mode mission layers in every `mp_*` world's `.game.xml` is authored `State="0"` /
`MissionLayerActiveDflt="0"`**, and `CMissionManager::Init` @ `0x10797F30` only activates a mission's
layers when its flag bit 0 is set. The game-mode content is never switched on.

**Watch the map sizes.** The player entity isn't destroyed or repositioned across a world load, so you
arrive at your old coordinates. SP worlds are 1024 m × 1024 m; `mp_*` worlds are 640 m × 640 m (512 m
for `mp_hellsgate_02` and `mp_ps3map`). Unless you were inside the first 640 m of both axes you land
*outside* the loaded map — void, no collision, falling. Teleport the player after the load.

Also worth knowing: **the player list is engine-level, not world-level.** The container at
`0x111E61F8` is allocated once at engine init, not per world.

And `cheat_menu` is a dead end — it has a consumer (`crc32("cheat_menu") = 0xFD9AEF75`, matched at
`0x108E7709`) but the target is the epilogue again. Same compiled-out-stub pattern as
`toggle_console`. No amount of input-map editing will ever reach it.

---

## If you want the window itself

We didn't need it, but it looked reachable. `SetUIActive(g_console, 1)` from the main thread has all
eight of its runtime preconditions verified live (console registry, UI object, UI vtable identity, 2D
debug-text renderer, input manager, input-context owner, and the closed-state fields). The residual
risk is that `SetActive(true)` also activates the `console` input action map by CRC `0x3603CFB6`, and
that path has demonstrably never run in retail — so it's untested code.

The safe order is: **first** write `[pUI+0x58] = 0` from your frame hook, which is a pure data write
with no code path, and see whether the console *draws*. That isolates the render half from the input
half at zero risk. Only then try the real call.

---

## Method note

The one rule we'd pass on above all others: **a negative result is only as broad as the thing you
actually scanned.** We twice recorded "this function has zero callers, it's unreachable" from a scan
that indexed only `E8 rel32` call sites. MSVC emits a method forwarding to a member sub-object as a
**tail jump** — `mov ecx,[ecx+0x90]; jmp target` — an `E9`. One of those "dead" functions is called
every frame. Index `E8`, `E9` *and* absolute references, and state which forms you covered. And
re-running the same method is not independent confirmation — to confirm a negative, change the
method.
