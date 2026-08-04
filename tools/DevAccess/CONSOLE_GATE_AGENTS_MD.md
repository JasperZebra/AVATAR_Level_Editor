# Paste-ready `agents.md` sections — Avatar console gate resolved (2026-07-26)

These blocks are written in `agents.md`'s house style and are meant to be pasted **into
`agents.md`** by a human. Nothing in this file edits `agents.md` itself.

**Placement:**
* **Block A** goes immediately after the existing heading
  `## Avatar console commands & cheat injection (2026-07-09) — SOLVED via Lua, console UI itself still dead`
  (≈ L4908), as a correction banner.
* **Block B** replaces the bullet in `### Why the console UI doesn't open` that begins
  *"The actual gate is inside `CConsoleService`'s constructor (`LAB_107b1d50`), which is
  DVM-protected/JIT'd"* and the "Best-guess conclusion" paragraph that follows it.
* **Block C** is a new top-level section to append after the existing one.

---

## Block A — correction banner

```markdown
> **⚠ CORRECTED 2026-07-26 — two claims in this section are now DISPROVEN.**
>
> 1. **"The actual gate is inside `CConsoleService`'s constructor (`LAB_107b1d50`), which is
>    DVM-protected/JIT'd — invisible to static analysis."** — **WRONG.** `dvm.dll` is
>    Solidshield/Tages copy protection (73 KB loader + 89 MB DRM VM image, zero game content — see
>    `Decompiled DLL's\Avatar\PC\Avatar_dvm_overlay\README.md`). It never encrypted Dunia's `.text`.
>    `0x107B1D50` **is** `CConsoleService::CConsoleService()` and it is plain, readable x86 in the
>    on-disk image; it was "invisible" only because **Ghidra never defined a function there** —
>    auto-analysis folded `0x107B1CC0`–`0x107B1DA4` into the unrelated `FUN_107b14f0`, whose
>    decompiled body stops long before it. The constructor is also **not** the gate.
> 2. **"confirmed it live (god mode via `Avatar_GodNpc` fired in-game)"** — believed to be a
>    **FALSE POSITIVE**. That session almost certainly had `GodMode="1"` set in
>    `engine\settings\defaultgameconfig.xml` at the same time. TESTS 3–7 in
>    `Avatar 2009 Documentation\DevAccess\TEST_LOG.md` injected 320 `domino\system` boxes with
>    `GodMode` back at stock `"0"` and **no runtime marker from any of them ever appeared**. Also
>    note the shipped Lua is **Lua 4.0** — no `pcall`, no `io`, no `os` — which silently killed every
>    probe that used `pcall`.
>
> The real gate is now known and fully documented in
> `Avatar 2009 Documentation\DevAccess\CONSOLE_GATE.md`. Summary in Block C below.
```

---

## Block B — replacement for the "actual gate" bullet

```markdown
- **The actual gate — SOLVED 2026-07-26.** It is not a flag, a mode, a null pointer or a missing
  asset. It is **missing code**. The `toggle_console` signal *is* delivered, *is* matched by hash,
  and the case body is **empty**:

  ```
  ; FUN_10635D90 (game-mode debug signal handler), Dunia.dll @ base 0x10000000
  106363F2  3b 05 50 72 22 11   cmp eax,[0x11227250]   ; [0x11227250] = 0xD4989D79
                                                        ;              = CRC32("toggle_console")
  106363F8  0f 84 0f ff ff ff   je  0x1063630D         ; -> straight to the epilogue
  ; 0x1063630D:  pop edi / pop esi / mov al,1 / pop ebx / add esp,0x44 / ret 8
  ```

  There is **zero code** between the branch and the return. `al = 1` means "signal consumed", so it
  never propagates anywhere else. `0xD4989D79` occurs in exactly two places in the whole DLL — the
  static initialiser and this comparison. `request_teamchange` (`0x45909C46`) shares the same dead
  target, which is what proves this is a deliberate ship-time strip rather than a decompiler artefact.

  **`cheat_menu` is dead for the identical reason:** `CRC32("cheat_menu") = 0xFD9AEF75`, matched at
  `0x108E7709`, `je 0x108E7A51` — and `0x108E7A51` is `pop esi / add esp,0xc / ret 8`, the epilogue.
  Input-map rebinding can never reach it. **Stop spending launches on XML.**

- **Signal-name hashing is SOLVED: it is plain zlib/PKZIP CRC-32 of the lowercase name.** Proof:
  `0x10EF0E05` writes the literal `0x3603CFB6` into the static naming the `"console"` action map, and
  `crc32(b"console") == 0x3603CFB6`. Every hashed signal in the binary is now searchable by name —
  see `Avatar 2009 Documentation\DevAccess\scripts\signal_hash.py`. This retires the old caveat that
  "absence of a literal string proves nothing": you can now search for the *hash* instead.

- **Everything the console needs is alive.** `CConsoleService::CreateConsole()` (`0x107B1CC0`, virtual
  slot `+0x3C`) is driven unconditionally by the generic service post-init loop `FUN_101DF650`
  (`0x101DF678`: `mov edx,[eax+0x3c]; call edx` for every registered service) — there is no
  `if (developer)` on that path. It allocates a `0x90`-byte `CFCXConsole` and stores it at
  `g_console + 0x78`, where `g_console = *(void**)0x111CA4B4`. The engine then calls
  `g_console->UpdateUI(dt)` **every frame** from `0x1018F476`. The window is constructed and ticking;
  it is simply never told to show itself.

- **`CConsole::SetUIActive(bool)` @ `0x100A7790` is called exactly twice in 16 MB of `.text`, and both
  call sites pass `false`** (`0x103D6771` and `0x106D61F2`, both after a `xor ebx,ebx`). There is no
  `SetUIActive(true)` anywhere in the retail binary.

- **Confirmed against the live retail process (PID 23468, 2026-07-26, read-only):**
  `g_console = 0x180B1BC0`; `g_console->m_pUI = 0x18774B00` with vtable `0x11142220` — **the console
  window object genuinely exists in a running retail game**; `state[+0x58] = 2` (idle),
  `height[+0x5C] = 0` (invisible), `inputCtx[+0x30] = 0xFFFFFFFF` (never registered),
  `m_bUIActive[+0x69] = 0`. Every dependency of the open call is up: debug-text service `0x14EF9410`,
  input manager `0x185DAA00`, input-context owner `0x150EF5A0`. Probe:
  `Avatar 2009 Documentation\DevAccess\scripts\console_state_probe.py`.

- **Empirical confirmation from two independent live process dumps:** the MSVC magic-static guard that
  `CFCXConsole::SetActive(true)` sets on first execution, `[0x1125AE40]`, is **`0` in both** — that
  variable is written from exactly two instructions, both inside the *open* branch of `0x10EF0DE0`.
  The open path has never executed. Likewise `[0x1125AE90]` (guard for `CFCXConsole::OnSignal`) is
  `0` in both, and the lazy class descriptors `[0x11227F80]` (`CFCXConsole`) and `[0x1122A770]`
  (`CFCXGRConsole`) are `0` in both — while `[0x112225AC]` (`CConsoleService`) and `[0x112225C0]`
  (`CFCXConsoleService`) are populated.

- **The "`FCXConsole` is a game mode with no retail transition" theory is dead.** The console UI is not
  a mode — it is a plain object owned by `g_console` at `+0x78`, ticked from the engine frame
  function. The `FCXConsole` entry in `gamemodesconfig.xml` and the `CFCXGRStateConsole` /
  `CFCXGameModeConsoleNode` classes belong to a different, entirely unused editor path (their class
  descriptors are never even queried at runtime). Do not chase a state transition.
```

---

## Block C — new section to append

```markdown
## Avatar console — the working invocation API (2026-07-26)

`Dunia.dll` loads at its preferred base **`0x10000000`** with no relocation, so every address below is
simultaneously a decompile address and a runtime address. `Avatar.exe` is 32-bit (WOW64).

### The three globals that matter

| VA | meaning |
|---|---|
| `0x111CA4B4` | **`g_console`** — the `CConsole` command registry (`this` for every call below) |
| `g_console + 0x78` | `CFCXConsole* m_pUI` — the console window object (constructed at boot) |
| `g_console + 0x69` | `bool m_bUIActive` |

### The API

| VA | signature | notes |
|---|---|---|
| `0x10003E20` | `__thiscall DuniaString* DuniaString::ctor(void* self, const char* s)` | `ret 4` |
| `0x10EC2F90` | `__thiscall void DuniaString::dtor(void* self)` | `ret 0` |
| `0x100AE5F0` | `__thiscall void CConsole::ExecuteLine(void* this, DuniaString* line)` | `ret 4` — **57 call sites in the engine itself** |
| `0x100ADD80` | `__thiscall void CConsole::Dispatch(void* this, DuniaString* line)` | `ret 4` — lower level; prefer `ExecuteLine` |
| `0x100AE650` | `__thiscall void CConsole::ExecBatch(void* this, DuniaString* file)` | `ret 4` — filename **must include** `.console` |
| `0x100A7790` | `__thiscall void CConsole::SetUIActive(void* this, int bActive)` | `ret 4` — **the open/close call retail never makes** |
| `0x100AC0C0` | `__cdecl void CConsole::Printf(void* this, int flags, const char* fmt, ...)` | caller cleans |

`DuniaString` is **0x1C bytes**: `+0x00` allocator tag (`0x111B7F74`), `+0x04..+0x13` SSO buffer or
`char*`, `+0x14` length, `+0x18` capacity (`< 0x10` ⇒ inline buffer at `+0x04`).

### The exact idiom (copied byte-for-byte from the engine at `0x100AE6E7`)

```c
unsigned char s[0x20];
void* console = *(void**)0x111CA4B4;
((void*(__thiscall*)(void*,const char*))0x10003E20)(s, "gfx_ShowFPS 1");
((void (__thiscall*)(void*,void*))      0x100AE5F0)(console, s);
((void (__thiscall*)(void*))            0x10EC2F90)(s);
```

**This must run on the main thread.** `TEST_LOG.md` PHASE 1b crashed calling `0x100ADD80` from a
`CreateRemoteThread` thread. Hook `CConsole::UpdateUI` @ **`0x100A75E0`** — called once per frame from
the engine frame function, and `ECX` on entry is already `g_console`. Full details, prologue bytes and
a staged bring-up plan: `Avatar 2009 Documentation\DevAccess\MAINTHREAD_HOOK.md`.

### Why `-exec` / `Game:Exec()` never worked from a remote thread

`FUN_100AE650` is **not** `(char* name)` cdecl as previously recorded. It is
`__thiscall(CConsole* this, DuniaString* filename)` and the filename **must already carry the
`.console` extension** — `Game:Exec()`'s own implementation (`FUN_1062B9A0`) appends `".console"`
(`0x11098C2C`) and loads `ECX` from `[0x111CA4B4]` before calling it (`0x1062BC1A`–`0x1062BC25`).
The PHASE-1 experiment passed a raw `char*` with no extension and no `this`; the path resolver
`FUN_100A9C70` read bytes 24–27 of the ASCII text as the string's capacity field, produced garbage,
and the function printed `"\nInvalid file path: %s (%s)"` into the (invisible) console buffer and
returned. **There was never an archive or mount problem.**

### Test-command hygiene

Use `gfx_ShowFPS 1` or `qc_ShowPlayerPos 1` as positive controls — both are confirmed registered
(present in `.rdata` *and* in the live heap registry). **Never** test with `Cheat_godmode`,
`Cheat_unlimitedammo` or `Cheat_speed_factor`: they are dead Far Cry 2 leftovers and will hand you a
false negative.

### Note on the Ghidra decompile

`Avatar_Dunia_Retail_1.02_decrypted.txt` has **large unanalysed gaps** — the entire console-service
region, `0x1018DF60`–`0x1018EE20`, `0x10EF12C0`–`0x10EF2E00` and more. Ghidra assigns those bytes to a
neighbouring `FUN_` whose decompiled body does not cover them, which is exactly how the
"DVM-protected constructor" myth started. **For anything console-related, disassemble
`Dunia_Decrypted_DLLs\Dunia_Retail_1.02_decrypted.dll` directly** (capstone; helper scripts in
`Avatar 2009 Documentation\DevAccess\scripts\`). Also note both files in `Dunia_Decrypted_DLLs\` are
**live process dumps**, so their `.data` sections carry real runtime globals — a free source of
"what was this pointer at runtime" answers.
```
