# CONSOLE_GATE — what actually stops the Avatar (2009 PC, retail 1.02) developer console from opening

**Date:** 2026-07-26 · **Scope:** static analysis of `Dunia.dll` (preferred base `0x10000000`, loads there — all
addresses below are both file-image VAs *and* runtime VAs, 1:1) · **Method:** read-only.

---

## 0. Executive answer

**The console is not gated by a flag, a mode, a null pointer, or a missing asset. It is gated by
*missing code*.**

Three independent, mutually corroborating facts:

1. **CONFIRMED** — The `toggle_console` input signal *is* delivered to a live handler, is *explicitly
   matched by hash*, and that case's body is **empty**: it jumps straight to the function epilogue and
   returns "handled". `FUN_10635D90 + 0x662` (`0x106363F2`): `cmp eax,[0x11227250]` / `je 0x1063630D`,
   where `0x1063630D` is `pop edi; pop esi; mov al,1; pop ebx; add esp,0x44; ret 8`.
2. **CONFIRMED** — The method that shows/hides the console UI, `CConsole::SetUIActive(bool)` @
   **`0x100A7790`**, is called **exactly twice in the whole 16 MB of `.text`, and both call sites pass
   `false`** (`0x103D6771` and `0x106D61F2`, both with `ebx` provably 0 from a preceding `xor ebx,ebx`).
   **There is no `SetUIActive(true)` anywhere in the binary.**
3. **CONFIRMED (empirical, two independent live process dumps)** — the magic-static guard byte that
   `CFCXConsole::SetActive(true)` would set on its first execution, `[0x1125AE40]`, is **`0` in both
   dumps**. That variable is written from exactly two instructions, both inside the `open` branch of
   `0x10EF0DE0`. The open path has therefore **never executed** in a real session.

**Everything else the console needs is present, constructed, and running.** In particular the console
UI object *is* created at engine start and *is* ticked every frame (§3). Only the "turn it on" call
is missing.

**Verified against the live retail process** (PID 23468, read-only, `scripts/console_state_probe.py`):

```
Dunia.dll base 10000000 : MZ confirmed          <- no relocation, addresses are 1:1
g_console        [111CA4B4] = 180B1BC0          OK
g_console->m_pUI [+0x78]    = 18774B00          <- the CFCXConsole window OBJECT EXISTS
  m_pUI vtable              = 11142220          <- exactly the expected CFCXConsole vtable
  m_pUI->state   [+0x58]    = 2                 <- idle (born closed, never touched)
  m_pUI->height  [+0x5C]    = 0                 <- invisible
  m_pUI->inputCtx[+0x30]    = FFFFFFFF          <- never registered an input context
g_console->m_bUIActive [+0x69] = 0
dbgtext2d service   [1121E13C] = 14EF9410       non-null
input manager       [111E61F8] = 185DAA00       non-null
input ctx owner     [111E5EAC] = 150EF5A0       non-null
SetActive(1) guard  [1125AE40] = 00000000       <- the console has NEVER been opened
OnSignal guard      [1125AE90] = 00000000       <- the console has NEVER seen input
```

**Is it flippable?** Not as a flag — there is no flag. But it is **callable**: an injected DLL running
on the main thread can call `CConsole::SetUIActive(g_console, true)` directly, and every single
dependency of that call has now been observed live and healthy. See §5. Confidence: **high** on the
diagnosis, **high** that the object and its preconditions exist, **medium-high** that the window
actually opens on the first try (the open path is code that has provably never executed, §5.2).

---

## 1. Corrections to prior conclusions

| prior claim | status | evidence |
|---|---|---|
| "`CConsoleService`'s constructor is at `LAB_107B1D50`, which is **DVM-protected/JIT'd and invisible to static analysis**" (`CONSOLE_UI.md` §3, `agents.md` L4908+) | **HALF RIGHT, WRONG REASON — the blocking conclusion is DISPROVEN** | `0x107B1D50` *is* `CConsoleService::CConsoleService()` — it allocates `0x38` bytes, stores vtable `0x1107D458` (name string `CConsoleService` @ `0x1107D4A4` sits right after that vtable), zeroes `+0x34/+0x35/+0x36`, sets `+0x30 = 7`. It is **plain, ordinary, fully readable x86** in the on-disk image. It was invisible only because **Ghidra never defined a function there** — the auto-analysis swallowed `0x107B1CC0`–`0x107B1DA4` into the unrelated `FUN_107b14f0`, whose decompiled body stops long before it. Nothing is encrypted. |
| `dvm.dll` encrypts Dunia's `.text` | **DISPROVEN** (already established, re-confirmed here) | Every address in this document was read straight out of `Dunia_Retail_1.02_decrypted.dll` with a plain PE reader + capstone. Prologues are clean. See also `Avatar_dvm_overlay/README.md`. |
| "`cheat_menu` has no engine consumer / the signal is dangling" (`TEST_LOG.md` TEST 1/2) | **RIGHT ANSWER, NOW WITH A MECHANISM** | `cheat_menu` **does** have a consumer: `CRC32("cheat_menu") = 0xFD9AEF75`, matched at `0x108E7709` (`cmp eax,0xfd9aef75` / `je 0x108e7a51`). `0x108E7A51` is `pop esi; add esp,0xc; ret 8` — **the epilogue**. Same compiled-out-stub pattern as `toggle_console`. No amount of rebinding will ever reach it. Input-map editing is closed, permanently. |
| `FUN_100AE650` is `(char* batchName)`, cdecl; the `.console` file failed for path/mount reasons (`TEST_LOG.md` PHASE 1) | **DISPROVEN** | It is `__thiscall(CConsole* this, DuniaString* name)` and the name **must already carry the `.console` extension**. See §6. The PHASE-1 call passed no `this`, a raw `char*` where a 0x1C-byte string object was expected, and no extension. It failed in `FUN_100A9C70`'s very first instruction group and printed `"\nInvalid file path: %s (%s)\n"` into the (invisible) console log. Nothing to do with archives or mounts. |
| "The engine hashes signal names, so absence of a literal string proves nothing" | **CONFIRMED, and now solved** | The hash is **plain zlib/PKZIP CRC-32 of the lowercase name**. Proof: `0x10EF0E05` writes the literal `0x3603CFB6` into the static that names the `"console"` action map, and `crc32(b"console") == 0x3603CFB6`. This makes every hashed signal in the binary searchable by name — see `scripts/signal_hash.py`. |

---

## 2. The gate, named precisely

### 2.1 The handler

**`FUN_10635D90`** @ **`0x10635D90`** — `__thiscall bool (this, uint32 signalHash, SignalEvent* ev)`,
`ret 8`, frame `sub esp,0x44`.

It is the **game-mode node's debug/system signal handler**. Its first ~700 bytes are the MSVC
magic-static initialiser block that computes/caches ~40 signal-name CRC32s into `.data`
(`0x112271F0`–`0x11227264`, guard word `0x11227264`). Then it does a linear `cmp eax,[static]` / `je`
chain against the incoming hash at `[ebx]` where `ebx = [esp+0x54]`.

Signals it handles (hashes reversed with `scripts/signal_hash.py` against the shipped
`Data\config\inputactionmap*.xml` name set):

`active_camerafirst`, `active_camerathird`, `active_cameraghost`, `active_camerafree`,
**`toggle_console`**, `toggle_scoreboard`, `request_teamchange`, `show_pausemenu`, `debugmenu`,
`enable_profiler_dump`, `disable_profiler_dump`, `enable_renderer_dump`, `enable_memtracer_dump`,
`enable_physics_dump`, `enable_pix_dump`, `disable_pix_dump`, `recompile_shaders`, `create_issue`,
`screenshot`, `open_loadout`, `enable/disable_action_mass_renaming`, `Voicechat_Remap`.

### 2.2 The exact conditional

```
; --- FUN_10635D90, the toggle_console case ---
106363F2  3b 05 50 72 22 11     cmp  eax, dword ptr [0x11227250]   ; eax = incoming signal hash
                                                                   ; [0x11227250] = 0xD4989D79
                                                                   ;              = CRC32("toggle_console")
106363F8  0f 84 0f ff ff ff     je   0x1063630D                    ; <-- straight to the epilogue

; --- 0x1063630D : the epilogue. There is ZERO code between the branch and this. ---
1063630D  5f                    pop  edi
1063630E  5e                    pop  esi
1063630F  b0 01                 mov  al, 1                          ; "signal consumed"
10636311  5b                    pop  ebx
10636312  83 c4 44              add  esp, 0x44
10636315  c2 08 00              ret  8
```

`request_teamchange` (`0x45909C46`, at `0x106363E6`) shares the same dead target — a second
retail-stripped feature, which is what confirms this is a deliberate ship-time strip and not a
decompiler artefact.

**`CRC32("toggle_console") = 0xD4989D79` occurs in exactly 2 places in the whole DLL** — once where it
is written into the static (`0x10635E01`) and once where it is compared (`0x106363F2`). There is **no
second consumer**. The signal reaches exactly one place and dies there.

### 2.3 What it tests, and where

There is nothing to flip. The conditional tests the *signal identity*, not a mode/flag/permission.
`al = 1` is returned unconditionally, so the signal is also swallowed and never propagates to any
other handler.

---

## 3. What *is* alive — the console is built and ticking

This is the surprising part and it is what makes a fix plausible.

### 3.1 `CConsoleService::CreateConsole()` runs unconditionally at startup — **CONFIRMED**

```
107B1CC0  53                    push ebx                       ; CConsoleService::CreateConsole(this)
107B1CC1  57                    push edi
107B1CC2  8b 3d b4 a4 1c 11     mov  edi, [0x111CA4B4]         ; edi = g_console (command registry)
107B1CC8  85 ff                 test edi, edi
107B1CCA  8b d9                 mov  ebx, ecx
107B1CCC  74 39                 je   0x107B1D07
107B1CCE  83 7f 78 00           cmp  dword ptr [edi+0x78], 0   ; already have a UI?
107B1CD2  75 33                 jne  0x107B1D07
107B1CD4  56                    push esi
107B1CD5  6a 00                 push 0
107B1CD7  68 90 00 00 00        push 0x90                      ; sizeof(CFCXConsole) = 0x90
107B1CDC  e8 ..                 call 0x100EE250                ; engine operator new
107B1CE8  8b c8                 mov  ecx, eax
107B1CEA  e8 61 0f 74 00        call 0x10EF2C50                ; CFCXConsole::CFCXConsole()
107B1CEF  8b f0                 mov  esi, eax
107B1CF5  8b 06 / 8b 50 04 / ff d2                             ; pUI->vtable[1]()  (0x10EF0EF0, font/res init)
107B1CFE  56 / 8b cf
107B1D01  e8 da a6 c3 ff        call 0x103EC3E0                ; g_console->m_pUI (+0x78) = pUI
107B1D08  c6 43 36 01           mov  byte ptr [ebx+0x36], 1    ; service->m_bConsoleCreated = 1
```

`CreateConsole` is **virtual slot `+0x3C`** of `CConsoleService`'s vtable `0x1107D458` (the base
`IService` vtable `0x110157A0` has a do-nothing `0x1004C910` there; `+0x40` is the matching
`IsCreated()` getter `0x1004C920` = `return this->[0x36]`; `+0x1C` is `DestroyConsole` `0x107B1D10`).

Slot `+0x3C` is driven by the **generic service-manager post-init loop**, `FUN_101DF650` @
`0x101DF650`:

```
101DF674  8b 0f                 mov ecx,[edi]        ; for each registered service
101DF676  8b 01                 mov eax,[ecx]        ;   vtable
101DF678  8b 50 3c              mov edx,[eax+0x3c]
101DF67B  ff d2                 call edx             ;   svc->OnPostInit()
101DF68B  75 e7                 jne 0x101DF674       ; loop
```

There is **no `if (developer)`** anywhere on that path, and `CConsoleService` is registered
unconditionally against four interface IDs at `0x108A61E6`–`0x108A6282` (factory `0x107B1D50`, service
registry `[0x111E61FC]`).

⇒ **`g_console->m_pUI` (`*(void**)(*(void**)0x111CA4B4 + 0x78)`) is a live, constructed `CFCXConsole`
at runtime.** — **CONFIRMED BY OBSERVATION**, not just by construction: in the running retail process
it reads `0x18774B00`, and `*(void**)0x18774B00 == 0x11142220`, the exact `CFCXConsole` primary
vtable. `CreateConsole` does run.

### 3.2 The console UI is updated every frame — **CONFIRMED**

`CConsole`'s own vtable is the 4-slot table at **`0x110197FC`** (written by `FUN_100ADC50` and
`FUN_100AE4D0`):

| slot | addr | meaning |
|---|---|---|
| `+0x00` | `0x100AE5D0` | scalar deleting dtor |
| `+0x04` | `0x100A75E0` | **`CConsole::UpdateUI(float dt)`** — `if (m_pUI) m_pUI->vtable[0](dt)` |
| `+0x08` | `0x100A7790` | **`CConsole::SetUIActive(bool)`** |
| `+0x0C` | `0x100A9180` | `CConsole::OnChar/Forward(a,b)` → `m_pUI->vtable[5]` |

`UpdateUI` is called once per frame from the engine frame function `FUN_1018EF50`:

```
1018F46C  8b 0d b4 a4 1c 11     mov  ecx, [0x111CA4B4]   ; g_console
1018F472  d9 44 24 10           fld  dword ptr [esp+0x10]; dt
1018F476  8b 01                 mov  eax, [ecx]
1018F478  8b 50 04              mov  edx, [eax+4]        ; slot +4 = UpdateUI
1018F47B  51 / d9 1c 24 / ff d2 call edx
```

`CFCXConsole::Update` (`0x10EF3A80`) then runs its slide animation from `[this+0x58]` (state) /
`[this+0x5C]` (pixel height) and, when `height > 0`, calls the renderer `FUN_10EF2E00`. Its only
precondition is `FUN_103B4C30` → `[0x1121E13C] != 0` (the 2D debug-text/`DrawDebugText2D` service),
which is **non-null in both live dumps** (`0x11650350`).

### 3.3 The open/close primitive is complete — **CONFIRMED**

`CFCXConsole::SetActive(bool)` @ **`0x10EF0DE0`** (vtable `0x11142220` slot 3):

* `arg != 0` → `[this+0x58] = 0` (⇒ `Update` sets height to 300 and starts drawing); lazily builds the
  static name `[0x1125AE3C] = 0x3603CFB6 = CRC32("console")`; registers/activates the **`console`**
  input action map through the input manager `[0x111E61F8]`; stores the returned context id in
  `[this+0x30]`; pushes an input context (`0x101A2450`); tail-calls `0x10197930` on `[0x111E5EAC]`.
* `arg == 0` → `[this+0x58] = 1` (close), clears `[this+0x14]`, `[this+0x15]`, unregisters.

The constructor `0x10EF2C50` sets `[this+0x58] = 2` (idle) and `[this+0x5C] = 0` — i.e. **born closed**.

`CConsole::SetUIActive(bool)` @ **`0x100A7790`** is the public wrapper:

```
100A7790  53 / 8b 5c 24 08      ebx = arg
100A7795  56 / 8b f1            esi = this (g_console)
100A7798  3a 5e 69              cmp  bl, [esi+0x69]      ; already in that state?
100A779B  74 12                 je   done
100A779D  8b 4e 78              mov  ecx, [esi+0x78]     ; m_pUI
100A77A0  85 c9 / 74 0b         if (!m_pUI) goto done
100A77A4  8b 01 / 8b 50 0c      edx = m_pUI->vtable[+0x0C]   ; CFCXConsole::SetActive
100A77A9  53 / ff d2            call it with (bool)
100A77AC  88 5e 69              mov  [esi+0x69], bl
100A77B1  c2 04 00              ret 4
```

### 3.4 Typed input and command execution are complete — **CONFIRMED**

`CFCXConsole::OnSignal` @ **`0x10EF3290`** (vtable `0x11142210` slot 1) matches, by CRC32,
`console_copy` (`0x2A6CE751`), `console_paste` (`0x83EB2DAA`), `console_autocomplete` (`0x9FF8DA37`),
`console_execute_buffer` (`0x9EF7ED46`), `console_clear_input` (`0xBAD9EB18`), `console_scroll`
(`0x25DFD256`), `console_ctrl` / `console_ctrl_release`, `console_backspace`, `console_delete`, … and
on `console_execute_buffer` it does:

```
10EF350D  50                    push eax                 ; the typed line (narrow)
10EF350E  8d 4c 24 14 / e8 ..   call 0x10003EA0          ; build DuniaString
10EF351B  8d 44 24 10 / 50      push &str
10EF351C  8b cb                 mov  ecx, ebx            ; this = g_console
10EF351E  e8 5d a8 1b ff        call 0x100ADD80          ; CConsole::Dispatch(this, DuniaString*)
```

The ~95 `console_char_*` → ASCII mappings are built in `FUN_10EF12D0`, called from the CFCXConsole
constructor at `0x10EF2D44`. All 95 name strings are present at `0x11142238`–`0x111427FC`.

`[0x1125AE90]` — the magic-static guard for `OnSignal`'s CRC table — is **`0` in both live dumps**,
i.e. the console has never received a single input signal. Consistent with everything above.

---

## 4. The "FCXConsole is a game mode with no retail transition" hypothesis

**Tested. VERDICT: NOT the gate. The hypothesis is wrong (or at least irrelevant).**

* The console UI is **not** a game-mode/state. It is a plain object owned by `g_console` at `+0x78`,
  ticked from the engine frame function (§3.2). No `CFCXGRState*` transition is involved in showing it.
* Empirically, the lazy class-descriptor slots for the *mode* classes are **never touched at runtime**:
  `[0x11227F80]` (`CFCXConsole` class-desc) `= 0` and `[0x1122A770]` (`CFCXGRConsole`) `= 0` in **both**
  live dumps — while `[0x112225AC]` (`CConsoleService`) and `[0x112225C0]` (`CFCXConsoleService`) are
  **both populated**. The service half of the system is alive; the "mode" half is inert *and unnecessary*.
* So the `FCXConsole` entry in `gamemodesconfig.xml` and the `CFCXGRStateConsole` /
  `CFCXGameModeConsoleNode` classes are editor/tool leftovers on a **different, unused** path. Chasing a
  state transition would be wasted effort.

---

## 5. Can we flip it? — YES, by *calling*, not by patching a flag

There is no boolean to set and no branch worth patching (patching the `je` at `0x106363F8` gains you
nothing: the case body does not exist, so falling through just runs the *next* comparison).

The correct move is to **call the function the retail build forgot to call**.

### 5.1 The one-line fix

```c
// MUST run on the main thread (see MAINTHREAD_HOOK.md)
typedef void (__thiscall *fnSetUIActive)(void* pConsole, int bActive);
void*  g_console = *(void**)(dunia + 0x011CA4B4);          // dunia == 0x10000000
((fnSetUIActive)(dunia + 0x000A7790))(g_console, 1);       // OPEN
```

Preconditions, all verifiable at runtime before you call:

| check | address | expected | **observed live (PID 23468)** |
|---|---|---|---|
| console registry exists | `*(void**)0x111CA4B4` | non-null | `0x180B1BC0` ✔ |
| console **UI object** exists | `*(void**)(*(void**)0x111CA4B4 + 0x78)` | non-null | `0x18774B00` ✔ |
| UI vtable is the expected one | `**(void***)(*(void**)0x111CA4B4 + 0x78)` | `0x11142220` | `0x11142220` ✔ |
| 2D debug-text renderer up | `*(void**)0x1121E13C` | non-null | `0x14EF9410` ✔ |
| input manager up | `*(void**)0x111E61F8` | non-null | `0x185DAA00` ✔ |
| input-context owner up | `*(void**)0x111E5EAC` | non-null | `0x150EF5A0` ✔ |
| console currently closed | `*(BYTE*)(*(void**)0x111CA4B4 + 0x69)` | `0` | `0` ✔ |
| UI state / height | `*(int*)(pUI+0x58)` / `+0x5C` | `2` / `0` | `2` / `0` ✔ |

**All eight preconditions verified live.** After the call, `[pUI+0x58]` should read `0`, and within a
frame `[pUI+0x5C]` should read `300` and `[pUI+0x30]` should stop being `0xFFFFFFFF`. Those are your
success signals even before anything is visible on screen.

### 5.2 Residual risk (why this is medium-high, not certain)

`SetActive(true)` does more than set a flag: it activates the **`console` input action map** by CRC
name `0x3603CFB6`. That map is defined in `Data\config\inputactionmapconsole.xml`, which is
`<Import>`ed by `inputactionmapcommon.xml` line 8 and therefore parsed. But because this path has
**demonstrably never run in retail** (`[0x1125AE40] == 0` in two dumps), it is untested code. Possible
outcomes:

* **best case** — console slides down, `~`-free but fully typeable, Enter dispatches to `FUN_100ADD80`.
* **likely partial** — console *draws* (that only needs `[+0x58] = 0`), but keystrokes do not arrive
  because the map failed to activate. Still useful: you get the output pane, and you drive commands
  from your own hotkey via §5.3.
* **worst case** — the action-map registration faults. Mitigate by first setting `[pUI+0x58] = 0`
  directly (a pure data write, no code path) and seeing whether the console *draws*. That isolates the
  render half from the input half at zero risk.

**Recommended order: (a) write `[pUI+0x58] = 0` from your frame hook and see if it draws; (b) only
then try the real `SetUIActive(1)`.**

### 5.3 The route that does not depend on the UI at all

Regardless of whether the window opens, **command execution is fully live and 57 call sites use it**.
Use it directly:

```c
// DuniaString: 0x1C bytes.  +0x00 allocator tag, +0x04..+0x13 SSO buffer,
//              +0x14 length, +0x18 capacity (<0x10 => inline buffer at +0x04)
typedef void* (__thiscall *fnStrCtor)(void* pStr, const char* s);   // 0x10003E20, ret 4
typedef void  (__thiscall *fnExecLine)(void* pConsole, void* pStr); // 0x100AE5F0, ret 4
typedef void  (__thiscall *fnStrDtor)(void* pStr);                  // 0x10EC2F90, ret 0

char str[0x20];
void* g_console = *(void**)(dunia + 0x011CA4B4);
((fnStrCtor)(dunia+0x00003E20))(str, "gfx_ShowFPS 1");
((fnExecLine)(dunia+0x000AE5F0))(g_console, str);
((fnStrDtor)(dunia+0x00EC2F90))(str);
```

This is the **exact instruction sequence the engine itself uses** at `0x100AE6E7`–`0x100AE6FF`, and at
54 other sites. It is the safest possible call because it is the engine's own idiom, byte for byte.

Verify with a command that has a visible effect and is *known registered* — `gfx_ShowFPS 1` or
`qc_ShowPlayerPos 1`. Do **not** use the `Cheat_*` family (dead Far Cry 2 leftovers).

---

## 6. Why `FUN_100AE650` never read its `.console` file — **SOLVED**

`FUN_100AE650` is **`__thiscall CConsole::ExecBatch(CConsole* this, DuniaString* filename)`**, and the
filename **must already include the `.console` extension**.

Proof — this is `Game:Exec()`'s implementation, `FUN_1062B9A0`:

```
1062BBBA  8b 0d 2c 8c 09 11     mov ecx,[0x11098C2C]        ; ".console"
1062BBC0  8b 15 30 8c 09 11     mov edx,[0x11098C30]        ; "sole"    (tail of the same literal)
...       append to the caller's name ...
1062BC1A  8b 0d b4 a4 1c 11     mov ecx,[0x111CA4B4]        ; this = g_console
1062BC25  e8 26 2a a8 ff        call 0x100AE650             ; ExecBatch(this, &name)
```

And the path builder `FUN_100A9C70` (`0x100A9C70`) is
`(DuniaString* out, DuniaString* name)` — its **very first act** is the SSO decode
`cmp [eax+0x18], 0x10 ; jb → eax+4 ; else → [eax+4]`, then it prepends `"scripts\Console\"`
(`0x11019714`, referenced at `0x100A9DD0` and `0x100A9E55`). The file is then opened through the
archive file-manager `[0x111CAE70]` via `FUN_100F1880`.

The PHASE-1 experiment passed a raw `char*` as `param_1`. `FUN_100A9C70` read
`*(uint*)(charptr + 0x18)` — i.e. bytes 24–27 of the ASCII text `"qc-mp-all-1"` and whatever followed
it — as the capacity, took a garbage branch, produced a garbage path, and `FUN_100AE650` printed
`"\nInvalid file path: %s (%s)\n"` (`0x11019840`) via `CConsole::Printf` — **into the console log
nobody can see**. It then returned cleanly. Exactly the observed behaviour.

**There is no root/mount prerequisite and no init-context requirement.** Correct call:

```c
typedef void (__thiscall *fnExecBatch)(void* pConsole, void* pStr);  // 0x100AE650, ret 4
((fnStrCtor)(dunia+0x00003E20))(str, "qc-mp-all-1.console");   // extension REQUIRED
((fnExecBatch)(dunia+0x000AE650))(g_console, str);
((fnStrDtor)(dunia+0x00EC2F90))(str);
```

(Prefer §5.3's per-line `ExecuteLine` anyway — it needs no file at all.)

---

## 7. Symbol table produced by this analysis

All `Dunia.dll`, base `0x10000000`, runtime == static.

### Functions

| VA | name | convention | notes |
|---|---|---|---|
| `0x10003E20` | `DuniaString::DuniaString(const char*)` | thiscall, `ret 4` | builds the 0x1C-byte string object |
| `0x10EC2F90` | `DuniaString::~DuniaString()` | thiscall, `ret 0` | frees only if capacity ≥ 0x10 |
| `0x100A75E0` | `CConsole::UpdateUI(float dt)` | thiscall, `ret 4` | vtable `0x110197FC[+4]`; called every frame |
| `0x100A7790` | **`CConsole::SetUIActive(bool)`** | thiscall, `ret 4` | vtable `0x110197FC[+8]`; **the open/close call** |
| `0x100A9180` | `CConsole::ForwardChar(a,b)` | thiscall | vtable `0x110197FC[+0xC]` |
| `0x100A9C70` | `CConsole::ResolveBatchPath(String* out, String* name)` | cdecl | prepends `scripts\Console\` |
| `0x100AC0C0` | `CConsole::Printf(this, int flags, const char* fmt, …)` | **cdecl** | writes to the console text buffer |
| `0x100ADC50` | `CConsole::~CConsole()` | thiscall | writes vtable `0x110197FC` |
| `0x100ADD80` | `CConsole::Dispatch(String* line)` | thiscall, `ret 4` | single-command dispatcher |
| `0x100AE5D0` | `CConsole::` scalar deleting dtor | thiscall | vtable `0x110197FC[+0]` |
| `0x100AE5F0` | **`CConsole::ExecuteLine(String* line)`** | thiscall, `ret 4` | **57 call sites; the safe entry point** |
| `0x100AE650` | `CConsole::ExecBatch(String* file)` | thiscall, `ret 4` | needs `.console` extension |
| `0x100AE800` | `CConsole::Cmd_exec(CmdCtx*)` | cdecl | the `exec` console command itself |
| `0x101DF650` | `CServiceManager::PostInitAll()` | thiscall | drives every service's vtable `+0x3C` |
| `0x1018EF50` | engine per-frame function | — | calls `g_console->UpdateUI(dt)` at `0x1018F476` |
| `0x104CE7C0` | world per-frame function | cdecl, void(void) | calls `0x1018EF50` |
| `0x108EF620` | game update (virtual) | thiscall | calls `0x104CE7C0` |
| `0x10635D90` | **game-mode debug signal handler** | thiscall, `ret 8` | **contains the dead `toggle_console` case** |
| `0x108E7700` | BTZ debug signal handler | thiscall, `ret 8` | contains the dead `cheat_menu` case |
| `0x107B1CC0` | `CConsoleService::CreateConsole()` | thiscall | vtable slot `+0x3C` |
| `0x107B1D10` | `CConsoleService::DestroyConsole()` | thiscall | vtable slot `+0x1C` |
| `0x107B1D50` | **`CConsoleService::CConsoleService()`** | cdecl factory | ← the misdiagnosed `LAB_107B1D50` |
| `0x10EF0DE0` | `CFCXConsole::SetActive(bool)` | thiscall, `ret 4` | vtable `0x11142220[+0xC]` |
| `0x10EF0EF0` | `CFCXConsole::InitResources()` | thiscall | font handles → `+0x80..+0x8C` |
| `0x10EF12D0` | `CFCXConsole::BuildCharSignalMap()` | thiscall | ~95 `console_char_*` |
| `0x10EF2C50` | `CFCXConsole::CFCXConsole()` | thiscall | size `0x90`; sets `+0x58 = 2` |
| `0x10EF2E00` | `CFCXConsole::Draw(renderer, height)` | — | text buffer + input line + cursor |
| `0x10EF3290` | `CFCXConsole::OnSignal(hash, ev)` | thiscall | vtable `0x11142210[+4]` |
| `0x10EF3A80` | `CFCXConsole::Update(float dt)` | thiscall | vtable `0x11142220[+0]` |
| `0x103B4C30` | `IsDebugText2DServiceUp()` | cdecl | `return [0x1121E13C] != 0` |

### Globals

| VA | meaning | live value (dump A / dump B) |
|---|---|---|
| `0x111CA4B4` | **`g_console`** — `CConsole*` (command registry) | `0x180D1B00` / `0x180B1BC0` |
| `g_console + 0x78` | `CFCXConsole* m_pUI` | (heap) |
| `g_console + 0x69` | `bool m_bUIActive` | 0 |
| `0x111CAE70` | file/archive manager used by `ExecBatch` | `0x180607E0` |
| `0x111E61F8` | input manager | `0x185DA9C0` |
| `0x111E61FC` | service registry | `0x18612A80` |
| `0x111E5EAC` | input-context stack owner | `0x11A93820` |
| `0x1121E13C` | 2D debug-text render service | `0x11650350` |
| `0x11233978` | BtzGame console command **group** (not the console) | `0x1876C720` / `0x1875C960` |
| `0x1125AE3C/40` | `SetActive(true)` magic static + guard | **`0` / `0` — never executed** |
| `0x1125AE90` | `OnSignal` magic-static guard | **`0` / `0` — never executed** |
| `0x11227250` | `CRC32("toggle_console")` static | `0xD4989D79` (initialised — handler *did* run) |
| `0x11227264` | guard word for that static block | `0xFFFFFFFF` |
| `0x11227F80` | `CFCXConsole` class-desc (lazy) | **`0` / `0` — never queried** |
| `0x1122A770` | `CFCXGRConsole` class-desc (lazy) | **`0` / `0` — never queried** |
| `0x112225AC` | `CConsoleService` class-desc | `0x1107D4A4` (populated) |
| `0x112225C0` | `CFCXConsoleService` class-desc | `0x110148FC` (populated) |

### Vtables

| VA | class | key slots |
|---|---|---|
| `0x110197FC` | `CConsole` (4 slots) | `+4` UpdateUI, `+8` **SetUIActive** |
| `0x1107D458` | `CConsoleService` (19 slots) | `+0x1C` Destroy, `+0x3C` **Create**, `+0x40` IsCreated |
| `0x1107D4B8` | `CFCXConsoleService` | `+0x3C` = thunk `0x104D7EC0 → 0x107B1CC0` |
| `0x11142210` | `CFCXConsole` (secondary, 4 slots) | `+0` dtor, `+4` **OnSignal** |
| `0x11142220` | `CFCXConsole` (primary, 6 slots) | `+0` **Update**, `+4` InitRes, `+8` ?, `+0xC` **SetActive**, `+0x14` OnChar |
| `0x1101ADD8` | console **element/command group** base | `+0x114` RegisterCommand, `+0x124` Release |

### Object layouts

`CFCXConsole` (`0x90` bytes):

| off | field |
|---|---|
| `+0x00` | vtable → `0x11142220` |
| `+0x04` | vtable → `0x11142210` |
| `+0x14/+0x15` | bytes cleared on close |
| `+0x18` | float, repeat/blink timer |
| `+0x30` | input-context id from `SetActive(true)` |
| `+0x34` | `DuniaString` (0x1C) — scratch / prompt |
| `+0x54` | scroll offset |
| `+0x58` | **state: 0 = opening, 1 = closing, 2 = idle** |
| `+0x5C` | **pixel height (0 = invisible, 300 = open)** |
| `+0x60` | `DuniaString` (0x1C) — the input line |
| `+0x74` | input-line length |
| `+0x7C` | cursor column |
| `+0x80..+0x8C` | font / render resource handles |

`CConsoleService` (`0x38` bytes): `+0x00` vtable `0x1107D458`, `+0x30` = 7, `+0x34/+0x35` flags,
`+0x36` = `m_bConsoleCreated`.

`DuniaString` (`0x1C` bytes): `+0x00` allocator tag (`0x111B7F74`), `+0x04..+0x13` SSO buffer or
`char*`, `+0x14` length, `+0x18` capacity (`< 0x10` ⇒ inline).

---

## 8. Honest limits of this analysis

* ~~Not verified live: that `*(void**)(g_console + 0x78)` is non-null in a running retail process.~~
  **DONE — 2026-07-26, PID 23468. It is `0x18774B00` with the correct vtable.** All eight
  preconditions in §5.1 were read from the live process and all pass.
* **Not verified live:** that `SetUIActive(1)` opens the window without side effects. See §5.2 for the
  staged, zero-risk way to find out.
* **Not attempted:** naming the remaining unreversed hashes in `FUN_10635D90`
  (`0x2180DE83`, `0x21F3CA84`, `0x77067607`, `0xB337AD4B`, `0xAA675CFD`, `0xEE9CB364`, `0x30A7A2E9`) —
  they are not in the shipped XML name set, so they are signals with no binding at all. Low value.
* **Ghidra's decompile of `Dunia.dll` has significant unanalysed gaps** (the whole console service
  region, `0x1018DF60`–`0x1018EE20`, `0x10EF12C0`–`0x10EF2E00`, …). Any future work here should
  disassemble the image directly rather than trusting the `.txt` — see `scripts/`.
