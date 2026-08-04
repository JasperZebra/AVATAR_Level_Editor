# CONSOLE_TEXT — why the open Avatar (2009 PC, retail 1.02) console panel draws no text

**Date:** 2026-07-26 · **Scope:** static disassembly of `Dunia.dll` (base `0x10000000`, loads there, addresses
1:1) + **read-only** probing of live `Avatar.exe` PID 18964 · **Method:** capstone over the PE image
(`scripts/dunia_dis.py`) plus `scripts/console_text_probe.py`. Ghidra's `.txt` was not trusted anywhere.

---

> ## ⚠ SUPERSEDED IN PART — read `RASTERISER.md` first (2026-07-26, later same day)
>
> `RASTERISER.md` answers the question this document left open, and in doing so **retracts §0a
> Correction 2 and §7 below, and reinstates this document's *original* §7 conclusion.**
>
> **Retail 1.02 has no 2D debug-text rasteriser.** Nothing consumes the text pool `0x11178C68`:
> all 696 call sites of the pool's consumer-side accessors load an immediate pool address and none
> is `0x11178C68` (the quad pool, which draws the visible console panel, *is* there — positive
> control). And `CSceneDebugTextRenderer`'s draw, called every frame from `0x103D0CC1` and
> `0x103D7C93` with `ECX = renderTable+0x04`, resolves to `0x106DAA10`, whose entire body is
> `C2 0C 00` — `ret 0xC`. Verified byte-for-byte in the live process with passing controls.
>
> Specific corrections to what follows:
> * §0a Correction 2 / §7 — **wrong**; the rasteriser does *not* exist. `[0x1121EBF4]` is written by
>   a load-time static initialiser (`0x1040A560`) and proves nothing about instantiation.
> * §5.1 — `0x1040A5F0` is the **destructor**; `0x1040A810` is the **scalar deleting destructor**;
>   the **constructor is `0x1040A6A0`**. The headline "the consumer — located, and alive" is withdrawn.
> * §0 / §3 / §6.1 — the `+0x38 = -1.1f` anomaly is closed for good: **no code reads any field of any
>   text batch.** (It was already falsified empirically; `RASTERISER.md` §2 supplies the mechanism.)
> * §6.1's three-dereference addressing is **correct** and was re-verified live. Clarification:
>   `pool+0x08` is the producer-side container of a double buffer whose consumer-side twin is
>   `pool+0x0C` (`RASTERISER.md` §1.3).
> * Slot indices are **not** stable across runs — the console's slot was `4` in the session below and
>   `3` in the next. Always read `pUI+0x80`.
>
> Everything in §§1–4 (the `Printf` → ring → `Draw` → batch chain, the input path, the layout math)
> is unaffected and remains CONFIRMED.

## 0. Executive answer

**Nothing in `CFCXConsole::Draw` gates the text. Draw runs, and it successfully queues the text.**

Every stage from `Printf` to "glyphs queued in a render batch" is **CONFIRMED working in the live
process**:

| stage | status | evidence |
|---|---|---|
| `CConsole::Printf` writes the ring buffer | **CONFIRMED** | our exact test string `"DEVACCESS printf test - flags=3 - if you can read this, output works"` was read out of the live ring at `g_console+0x0C` |
| `Draw` reads *that same* ring | **CONFIRMED** | `Draw` reads `g_console+0x0C/+0x10/+0x14/+0x18`; `AddLine` writes `g_console+0x0C/+0x10/+0x14/+0x18`. Same four fields, byte for byte. |
| ring is non-empty (so the scrollback gate is open) | **CONFIRMED** | `[g_console+0x18] = 143` lines live |
| the UTF-16 → ASCII conversion `Draw` needs | **CONFIRMED CORRECT** | lines are stored **wide**; `0x100040D0` is a wide→narrow converting copy ctor (`wcstombs` at `[0x110003D4]`) |
| typing reaches the edit line | **CONFIRMED** | `pUI+0x60` held the wide string `"ffddfv"`, `len=6`, cursor col `+0x7C = 6` |
| the input context was registered | **CONFIRMED** | `pUI+0x30 = 0x3E8` (was `0xFFFFFFFF` forever before) |
| `Draw` submits glyphs into a render batch | **CONFIRMED** | the console's text batch has grown to **3072 entry slots / 2979 char capacity**. Nothing else in the process has ever used that pool. |

**So the break is strictly downstream of `Draw`: the queued text batch is never rasterised.**

**The single anomaly, and the only structural difference between the console's text batch and every
other text batch in the process:**

```
10EF3AF5  f3 0f 10 05 24 28 14 11   movss xmm0, dword ptr [0x11142824]   ; -1.1f
10EF3B01  f3 0f 11 46 38            movss dword ptr [esi+0x38], xmm0     ; textBatch->m_fDepth = -1.1f
10EF3B06  f3 0f 10 05 b4 3a 01 11   movss xmm0, dword ptr [0x11013AB4]   ; -1.0f
10EF3B0E  f3 0f 11 81 88 00 00 00   movss dword ptr [ecx+0x88], xmm0     ; quadBatch->(+0x88) = -1.0f
```

`CFCXConsole::Update` @ `0x10EF3A80` writes **-1.1f** into the *text* batch's `+0x38` and **-1.0f** into
the *quad* batch's equivalent field. The quad batch is the one that draws the **panel you can see**.
The text batch is the one that draws **nothing**. Constructor default for `+0x38` is `0.0f`
(`0x10081F27`), and **every other text batch in the live process reads `+0x38 = 0.0`** — the console's
is the only `-1.1`. `0x10EF3AF9` is also the **only** site in the whole 16 MB `.text` that stores
`-1.1f` into a text batch (the other two references to the constant `0x11142824` are an unrelated array
index at `0x10EFB480` and a `±1.1` clamp at `0x10F482FA`).

---

## 0a. CORRECTIONS — 2026-07-26, after live testing (read this before anything else)

Two things in the first issue of this document were wrong. Both are corrected **in place**, not appended.

**Correction 1 — the batch-addressing expression in my hand-off summary was one dereference short, and
it crashed the game.** `0x100758B0` performs **three** dereferences after `pool+8`; the collapsed
one-liner I sent performed two. The C block in §6.1 of the original document was already correct — the
collapsed form was not. Derivation and the exact wrong value are in §6.1, **reproduced live**. My error.

**Correction 2 — ⚠ THIS CORRECTION IS ITSELF RETRACTED. See `RASTERISER.md` §0 and §3.**
The original §6.0/§7 reasoning ("maybe retail has no 2D debug-text rasteriser") was **right**, though
for a reason neither issue of this document had established: the renderer *class* ships and is
instantiated, but its **draw body is compiled out** (`0x106DAA10 = C2 0C 00`, `ret 0xC`), and nothing
anywhere reads the pool. The inference below — "instantiated + shader resolves ⇒ a render pass
exists" — does not follow, and the `[0x1121EBF4]` premise is invalid (that store is a load-time
static initialiser, `0x1040A560`). The individual facts in the bullet list are correct; the
conclusion drawn from them is not. Original text preserved below for audit:

Retail 1.02 ships a debug-text rasteriser, it **is**
instantiated, and its shader **does** resolve:

* `CSceneDebugTextRenderer` — ctor `0x1040A5F0`, factory `0x1040A810`, descriptor `0x1105E670`,
  class-name string `0x1105E648`. **CONFIRMED present in the retail image.**
* Lazy class descriptor `[0x1121EBF4] = 0x1105E648` **live** — populated, so registration
  (`0x1040A560`) ran. Contrast the known-never-queried control `[0x11227F80]` (`CFCXConsole`) `= 0`.
* **Exactly one live instance, at `0x1853BD00`.** Found by scanning all 581.6 MB of committed writable
  memory in PID 8644. The scan carried a **positive control** — `CFCXConsole` vtable `0x11142220` —
  which returned exactly one hit at `0x18784A60`, the address `g_console+0x78` independently reads.
  (A first, narrower scan restricted to `MEM_PRIVATE` found zero and would have produced a false
  negative; the control is what caught it.)
* Its **"DebugText" effect handle resolved.** `0x1040A7EE` looks up the effect named `"DebugText"`
  (`0x1105E674`) via `0x10EBA3B0` and stores the 64-bit result at `+0x28/+0x2C`. `0x10EBA3B0`
  zero-initialises its out-parameter (`0x10EBA3B5`, `0x10EBA3B8`), so `{0,0}` is the miss value.
  **Live it reads `{0x0000000F, 0x00000000}` — resolved, not a miss.**

⇒ **The 2D debug-text pass exists in retail and is alive.** The `gfx_ShowFPS` / `qc_ShowPlayerPos`
negatives therefore do **not** show the text layer is dead — far more likely those two CVars are
themselves inert, the same retail-strip pattern as the dead `toggle_console` and `cheat_menu` cases in
`CONSOLE_GATE.md` §2. Corroborating: a sweep of **all 29** text-pool slots live shows **every one
pristine except the console's** — no other producer has ever filled a batch, so those commands never
reached the producer stage at all. **The FPS test was not a test of the rasteriser.**

**Consequence for the `+0x38 = -1.1f` hypothesis:** neither confirmed nor refuted. It is still the only
structural anomaly, but it is no longer the only candidate, and §6.1 is no longer presented as "the
fix". The next step is **read-only** and involves no field writes — see §6.4.

---

**Honest caveat, stated up front:** I have not read the code path that turns a queued text batch into
geometry, so `+0x38` remains **HYPOTHESIS**. What is now established is that a consumer exists.

---

## 1. `CFCXConsole::Draw` @ `0x10EF2E00`, fully disassembled

`__thiscall void Draw(CFCXConsole* this, CDbgTextBatch* batch, int height)`, `ret 8`.
Note: the `height` argument (`[ebp+0x0C]`) is **never read**. All layout comes from `0x10EF0C20`.

### 1.1 The only conditional that can suppress text — and it is open

```
10EF2E75  e8 86 47 1b ff   call 0x100A7600            ; CConsole::LockLines (EnterCriticalSection g_console+0x88)
10EF2E7A  8b 5f 18         mov  ebx, [edi+0x18]       ; edi = g_console;  ebx = line COUNT
10EF2E7D  8b 77 14         mov  esi, [edi+0x14]       ; esi = ring HEAD
10EF2E80  33 c0            xor  eax, eax
10EF2E82  03 f3            add  esi, ebx
10EF2E84  85 db            test ebx, ebx
10EF2E86  89 44 24 24      mov  [esp+0x24], eax       ; i = 0
10EF2E8A  0f 86 0b 01 00 00 jbe 0x10EF2F9B            ; <<< count == 0  =>  SKIP THE WHOLE SCROLLBACK LOOP
```

**This is the branch.** Address `0x10EF2E8A`, testing `*(int*)(g_console+0x18)` — the console line
count. **Live it is `143`, so it is NOT taken.**

The only other per-line skip is the scroll offset:

```
10EF2E90  8b 4c 24 28      mov  ecx, [esp+0x28]       ; this (pUI)
10EF2E94  3b 41 54         cmp  eax, [ecx+0x54]       ; i  vs  pUI->m_nScrollOffset
10EF2E97  7d 08            jge  0x10EF2EA1            ; i >= scroll  =>  draw this line
10EF2E99  83 ee 01         sub  esi, 1
10EF2E9C  e9 eb 00 00 00   jmp  0x10EF2F8C            ; else skip
```

**Live `pUI+0x54 = 0`, so nothing is skipped.**

There is **no** state check (`+0x58`), **no** null-buffer check, **no** font-handle check, **no**
"has focus" flag, and **no** render-target / 2D-mode precondition anywhere inside `Draw`. The one
gate that exists upstream is in `Update`:

```
10EF3A8E  e8 9d 11 4c ff   call 0x103B4C30            ; return [0x1121E13C] != 0   (2D debug-text service)
10EF3A93  84 c0            test al, al
10EF3A95  0f 84 8c 01 00 00 je 0x10EF3C27             ; service down => no Update at all
...
10EF3B16  8b 43 5c         mov  eax, [ebx+0x5C]       ; height
10EF3B19  85 c0            test eax, eax
10EF3B1B  0f 8e 9c 00 00 00 jle 0x10EF3BBD            ; height <= 0 => skip Draw AND the panel
10EF3B25  e8 d6 f2 ff ff   call 0x10EF2E00            ; Draw(textBatch, height)
...
10EF3BB5  e8 56 cd ff ff   call 0x10EF0910            ; the translucent PANEL, via the quad batch
```

Both live: `[0x1121E13C] = 0x14ED9410` (non-null) and `height = 300` when open. **`Draw` and the panel
sit inside the *same* `height > 0` gate.** Since the panel is visibly drawn, `Draw` is provably
running. That is the load-bearing deduction of this whole report.

### 1.2 What `Draw` emits, unconditionally

| # | site | what | flags | gate |
|---|---|---|---|---|
| 1 | `0x10EF2F14` | each scrollback line | `0x11` | line count > 0, `i >= scrollOffset` |
| 2 | `0x10EF2FED` | the prompt literal `" >"` (`0x11142820`) | `0x11` | **none** |
| 3 | `0x10EF2FF6`→`0x10EF3072` | the input line `pUI+0x60` | (append) | **none** |
| 4 | `0x10EF3115` | `"  "` (`0x1114281C`) before the cursor | `0x11` | blink phase |
| 5 | `0x10EF3121` | `pUI+0x7C` spaces, then `"|"` (`0x11013AB8`) | (append) | blink phase |
| 6 | `0x10EF31E6` | the scratch/prompt string `pUI+0x34` | `0x11` | **none** |

Items 2–6 have **no gate at all**. Even with an empty scrollback, an open console must still draw
`" >"`, the typed line, and a blinking `|`. The user sees none of them. That, on its own, rules out
every buffer/count/scroll explanation.

### 1.3 Layout — verified sane against the live process

`0x10EF0C20(float* out0, float* out1, float* out2, float* out3)` (cdecl, 4 out-params):

* `out0 = 1.0f` (`0x10EF0D0F`), `out1 = 0.0f` (`0x10EF0D1E`)
* `out2 = (float)clientWidth` (`0x10EF0D2E`)
* `out3 = (float)clientHeight * 0.5f` if `[metrics+2] != 0`, else `* 0.3f` (`0x10EF0D48` / `0x10EF0D79`)

Metrics come from `0x103B4E70` → `*(void**)0x111E3E54 + 0x14`, refined by `GetClientRect`
(`[0x11000708]`) at `0x10EF0C95`.

**Live values:** `width = 1920`, `height = 1080`, `[metrics+2] = 1`, aspect mode `*(0x111E3B9C)+0x40 = 0`.
⇒ `out3 = 540.0`. Scrollback starts at `y = 540 - 42 = 498` (`0x10EF2E62`, `[0x111421F4] = 42.0f`) and
walks **up** by `14.0f` per line (`[0x111421F0] = 14.0f`); prompt/input/cursor at `y = 540 - 14 = 526`;
`x = 1.0`, `z = 1.0`, colour white `{1,1,1,1}`.

Those are all on-screen pixel coordinates. **Layout is not the problem.** (Cosmetic note for later: the
text block spans y≈0..526 while the panel is only 300 px tall — the panel animates to `0x12C = 300`
(`0x10EF3AAD`) but the text is laid out for a *half-screen* console. Once text renders, expect it to
overflow the panel on a 1080p display.)

---

## 2. Where `CConsole::Printf` puts its text — and it landed

### 2.1 The call chain

`CConsole::Printf` @ **`0x100AC0C0`**, **cdecl**, `(CConsole* this, int flags, const char* fmt, ...)`.

```
100AC0C9  38 9c 24 4c 08 00 00   cmp  byte [esp+0x84C], bl   ; flags == 0 ?
100AC0D0  56                     push esi
100AC0D1  8b b4 24 4c 08 00 00   mov  esi, [esp+0x84C]       ; esi = this
100AC0D8  74 09                  je   0x100AC0E3             ; flags == 0 -> always proceed
100AC0DA  38 5e 68               cmp  byte [esi+0x68], bl
100AC0DD  0f 84 fa 00 00 00      je   0x100AC1DD             ; flags != 0 AND g_console->[0x68] == 0
                                                             ;   -> SILENT RETURN
```

**Newly named field: `g_console+0x68` = "verbose/echo enabled".** Live it reads `1`, so even the
`flags != 0` calls went through. (`+0x69` right next to it is `m_bUIActive`.)

Then `vsnprintf` (`[0x110003E4]`, 0x7FF-byte scratch) → narrow `DuniaStringA` → widened →
`0x100AC1A0: call 0x100AB660` = **`CConsole::AddLine(DuniaStringW*)`**.

### 2.2 The buffer, named

`CConsole` owns a **ring of `DuniaStringW*`** embedded at `g_console+0x04`:

| absolute VA | ring field | live |
|---|---|---|
| `g_console+0x0C` | `DuniaStringW** m_ppLines` | `0x3CC98470` |
| `g_console+0x10` | `int m_nCapacity` | `181` |
| `g_console+0x14` | `int m_nHead` | `0` |
| `g_console+0x18` | `int m_nCount` | `143` |
| `g_console+0x88` | `CRITICAL_SECTION` | — |
| `g_console+0xA4` | lock recursion counter | — |

`AddLine` writes them through `edi = g_console+4`: `[edi+8]`=`+0x0C`, `[edi+0xC]`=`+0x10`,
`[edi+0x10]`=`+0x14`, `[edi+0x14]`=`+0x18` (`0x100AB715`–`0x100AB75D`, grow at `0x100AB728`, per-line
`0x1C`-byte allocation at `0x100AB74D`). It also splits the incoming text on `'\r'` (0xD) and `'\n'`
(0xA) via `DuniaString::find` `0x100A78F0`.

`Draw` reads them through `edi = g_console`: `+0x18` count (`0x10EF2E7A`), `+0x14` head
(`0x10EF2E7D`), `+0x10` capacity (`0x10EF2EA1`), `+0x0C` array (`0x10EF2EAF`).

**Same buffer. CONFIRMED, statically and live.**

### 2.3 Live proof our Printf calls landed

`scripts/console_text_probe.py` walked the ring newest-first and found, at indices 14–37, sixteen
copies of our test line (four flag values × four presses):

```
string obj 1A0D2220: 75 7f 1b 11 40 d8 2e 19 3b 56 31 3f 8e 97 a4 00 00 00 80 3f 44 00 00 00 47 00 00 00
   +0x14 len = 68   +0x18 capacity = 71
   heap 192ED840: 44 00 45 00 56 00 41 00 43 00 43 00 45 00 53 00 53 00 20 00 ...
   as UTF-16LE: 'DEVACCESS printf test - flags=3 - if you can read this, output works'
```

**`CConsole::Printf` works perfectly, at every flag value 0–3.** The output pane simply never renders.

### 2.4 Correction: console lines are `DuniaStringW`, not `DuniaStringA`

| | narrow `DuniaStringA` | wide `DuniaStringW` |
|---|---|---|
| size | `0x1C` | `0x1C` |
| `+0x00` | allocator tag `0x111B7F74` | allocator tag `0x111B7F75` |
| `+0x04` | 16-byte SSO buffer, or `char*` | 16-byte SSO buffer (8 wchars), or `wchar_t*` |
| `+0x14` | length in chars | length in **wchars** |
| `+0x18` | capacity | capacity in **wchars** |
| SSO threshold | `capacity >= 0x10` ⇒ heap | **`capacity >= 8`** ⇒ heap |

The allocator tag distinguishes them: `...74` narrow, `...75` wide. Console ring entries, `pUI+0x34`
and `pUI+0x60` are all **wide** (tag `0x111B7F75`).

`CONSOLE_GATE.md` §7 lists a single `DuniaString` with a `0x10` SSO threshold — that is the *narrow*
one only, and it is what `ExecuteLine`/`0x10003E20` take (which is why the ExecuteLine work
succeeded). No change needed there; just do not reuse `0x10` for wide strings.

`Draw` handles the conversion correctly: `0x100040D0` is
`DuniaStringA::DuniaStringA(const DuniaStringW&)` —
`lea ebp,[eax+eax+2]` (2·len+2 bytes), SSO test `cmp [edi+0x18], 8` (`0x10081487`… i.e. `0x10004187`),
then `wcstombs` via `[0x110003D4]` at `0x10004198`. **Encoding is not the bug.**

---

## 3. Is a font loaded? — `+0x80..+0x8C` are **not** font handles

`CFCXConsole::InitResources` @ `0x10EF0EF0` (pUI vtable `0x11142220` slot 1) is nine instructions:

```
10EF0EF4  6a 00                push 0
10EF0EF6  8d 44 24 08          lea  eax, [esp+8]          ; &out[2]
10EF0EFD  b9 68 8c 17 11       mov  ecx, 0x11178C68       ; TEXT primitive pool
10EF0F02  e8 f9 46 18 ff       call 0x10075600            ; Create() -> {slotIndex, tag}
10EF0F15  89 8e 80 00 00 00    mov  [esi+0x80], ecx       ; slotIndex
10EF0F21  89 96 84 00 00 00    mov  [esi+0x84], edx       ; tag
10EF0F1C  b9 18 8b 17 11       mov  ecx, 0x11178B18       ; QUAD/2D primitive pool
10EF0F27  e8 f4 52 18 ff       call 0x10076220            ; Create() -> {slotIndex, tag}
10EF0F34  89 8e 88 00 00 00    mov  [esi+0x88], ecx
10EF0F3A  89 96 8c 00 00 00    mov  [esi+0x8C], edx
```

So `+0x80..+0x8C` is **two `{slotIndex, tag}` pairs for two render-primitive pools**, not four font
handles. The matching destructor `0x10EF0F50` passes both dwords of each pair back to `0x10075710` /
`0x10076330` (Release).

**`+0x84 = 0` is NOT a missing handle.** It is the second word of the text pool's handle; `+0x8C = 1`
is the second word of the quad pool's. `0x100758B0` (Get) only ever reads word 0:

```
100758B0  8b 44 24 04   mov eax, [esp+4]     ; handle*
100758B4  8b 00         mov eax, [eax]       ; slotIndex  <- word 0 only
...
100758D5  03 fd         add edi, ebp         ; &array[slotIndex]
10075961  8b 07         mov eax, [edi]       ; the batch object
```

**Verified live:** text handle `{4, 0}` resolves to batch object `0x19EFD280`; quad handle `{3, 1}`
resolves to `0x19979480`. Both non-null, both with well-formed slot records (`0a 18 04 05`, identical
in shape to every other live slot). **`InitResources` ran fully and successfully.**

`CFCXConsole` holds **no font handle at all** — fonts are internal to the text-primitive system.
The batch object's own resource-ish fields are:

| batch off | meaning | ctor default (`0x10081ED0`) | console live | other batches live |
|---|---|---|---|---|
| `+0x04..+0x1F` | `DuniaStringA` — the accumulated character stream | empty, cap `0xF` | cap **2979** | cap 15 |
| `+0x18` | char count (= that string's length) | 0 | 0 (cleared each frame) | 0 |
| `+0x20/+0x24/+0x28` | vector of `0x30`-byte draw entries | null/0/0 | base `0x1542B010`, **cap 3072** | null/0/0 |
| `+0x2C` | byte flag | `1` | 1 | 1 |
| `+0x30` | `0xFFFFFFFF` | `-1` | `-1` | `-1` |
| `+0x34` | float | `-1.0f` | `-1.0` | `-1.0` |
| `+0x38` | float | **`0.0f`** | **`-1.1`** | **`0.0`** |
| `+0x3C` | `GetCurrentThreadId()` (`0x1000A8B0` = `jmp [0x110000B0]`) | tid | `0x5C34` | `0x5C34` |

The grown capacities are the proof that `Draw` really did append thousands of glyph entries. `+0x38`
is the sole outlier.

---

## 4. The input path — it already works

* **`pUI+0x30` (input context) = `0x3E8` live.** It was `0xFFFFFFFF` in every prior dump.
  `CFCXConsole::SetActive(true)` @ `0x10EF0DE0` registered it — that is the function you already call
  via `CConsole::SetUIActive`. Nothing further is needed.
* **`[0x1125AE90] = 0x7FFFF` is benign and expected — verified, not assumed.** It is an MSVC
  *bit-mask* magic-static guard, one bit per cached CRC32:
  ```
  10EF3290  a1 90 ae 25 11    mov  eax, [0x1125AE90]
  10EF3298  a8 01             test al, 1
  10EF32A0  75 12             jne  0x10EF32B4
  10EF32A2  83 c8 01          or   eax, 1
  10EF32A5  a3 90 ae 25 11    mov  [0x1125AE90], eax
  10EF32AA  c7 05 8c ae 25 11 51 e7 6c 2a   mov [0x1125AE8C], 0x2A6CE751   ; CRC32("console_copy")
  ```
  I counted the stores to `[0x1125AE90]` inside `OnSignal`: **exactly 19** (`0x10EF32A5`, `32BB`,
  `32D1`, `32E7`, `32FD`, `3313`, `3329`, `3341`, `335C`, `3377`, `3392`, `33AD`, `33C8`, `33E3`,
  `33FE`, `3419`, `3434`, `344F`, `346A`). 19 bits set = `0x7FFFF`. **It means `OnSignal` ran to
  completion.** Not a bit-field of anything else, not corruption.
* **The edit line is populated.** `pUI+0x60` live:
  ```
  75 7f 1b 11 | 66 00 66 00 64 00 64 00 66 00 76 00 00 00 00 00 | 06 00 00 00 | 07 00 00 00
  tag(W)        inline SSO buffer: "ffddfv"                       len=6         cap=7
  ```
  i.e. the user typed `ffddfv` and it went in. `pUI+0x7C` (cursor column) = 6, consistent.
  Note `pUI+0x74` is not a separate "input length" field — it is `pUI+0x60`'s `+0x14` length member.
* **`pUI+0x34` (the prompt/scratch string) is empty**, `len=0`. Harmless: `0x10082140` returns
  immediately on a zero-length string (`0x10082163 je 0x100821D1`).

**Typing reaches the edit line, and `Draw` renders that edit line.** There is nothing left to fix on
the input side. `BuildCharSignalMap` @ `0x10EF12D0` did its job.

---

## 5. The render path, as far as it could be traced

```
CConsole::UpdateUI (0x100A75E0, vtable 0x110197FC+4, called every frame from 0x1018F476)
  └─ CFCXConsole::Update (0x10EF3A80, pUI vtable 0x11142220+0)
       ├─ 0x103B4C30 : [0x1121E13C] != 0 ?            -- live OK
       ├─ animate +0x58 state / +0x5C height          -- live 2 / 0 closed, 0 / 300 open
       ├─ textBatch = TextPool.Get(&pUI[0x80], false) -- 0x100758B0, pool 0x11178C68, slot 4
       ├─ textBatch->Clear()                          -- 0x10082230
       ├─ quadBatch = QuadPool.Get(&pUI[0x88], false) -- 0x100764D0, pool 0x11178B18, slot 3
       ├─ quadBatch->Clear()                          -- 0x10081480
       ├─ textBatch->+0x38 = -1.1f                    -- 0x10EF3B01   <<<< THE ANOMALY
       ├─ quadBatch->+0x88 = -1.0f                    -- 0x10EF3B0E
       └─ if (height > 0) {
              CFCXConsole::Draw(textBatch, height)    -- 0x10EF2E00   queues glyphs  [CONFIRMED]
              quadBatch = QuadPool.Get(&pUI[0x88], true)
              0x10EF0910(quadBatch, ...)              -- draws the translucent PANEL  [VISIBLE]
          }
```

Text is appended by `CDbgTextBatch::AddText` @ **`0x10082140`**
(`__thiscall(this, const Vec3* pos, const Vec4* colour, int flags, const char* text)`, `ret 0x10`) and
`CDbgTextBatch::AppendText` @ **`0x100821E0`** (`__thiscall(this, const char* text)`, `ret 4`). Both
are pure buffering: they push a `0x30`-byte entry onto `+0x20` and concatenate the characters onto the
string at `+0x04`. Neither touches a device.

Pools: `0x11178C68` = text (manager object at `0x11178C48`, vtable `0x11017A58`), `0x11178B18` = quad
(manager at `0x11178AF8`, vtable `0x110179B4`), plus a third at `0x11178CD8`. Live: the text pool has
29 registered slots, the quad pool 8.

`AddText`'s `flags` vocabulary, from all 13 call sites in `.text`:

| flags | sites |
|---|---|
| `0x11` | `0x103D724D`, and all four console sites `0x10EF2F14 / 2FED / 3115 / 31E6` |
| `0x12` | `0x10F0A315`, `0x10F0BA9E` |
| `0x20` | `0x103B980E`, `0x103B9C9F` (the `Stats_*` overlay) |
| (none / computed) | `0x101F0BA1`, `0x101F0CB3`, `0x103B528B`, `0x10672FE9` |

`0x11` is **not** console-exclusive (`0x103D724D` uses it too), so the flags are not the anomaly.

### 5.1 ~~The consumer — located, and alive~~ — WITHDRAWN, see `RASTERISER.md` §3

> `CSceneDebugTextRenderer` is **not** a consumer of the pool: `0x11178C68` has 38 absolute
> references image-wide and none is in the `0x1040Axxx` region. Its draw is reached non-virtually
> from `0x103D0CC1` / `0x103D7C93` with `ECX = renderTable+0x04` and is the empty stub `0x106DAA10`
> (`ret 0xC`). Also, in the table below: **`0x1040A5F0` is the destructor, `0x1040A810` is the
> scalar deleting destructor (vtable slot 0), and the constructor is `0x1040A6A0`**; and the
> `[0x1121EBF4]` row proves only that `Dunia.dll` loaded (it is written by the load-time static
> initialiser `0x1040A560`). The live-instance row is correct and was independently re-confirmed
> (one instance, `0x1853BD00`, control passed).

The rasteriser is **`CSceneDebugTextRenderer`**, and it is **not** reachable from the pool globals,
which is why an xref sweep of `0x11178C68` missed it: the pool manager is the *scene attribute*
(`CSceneDebugText`, class-name string `0x11017A44`, manager object `0x11178C48`, vtable `0x11017A58`)
and the renderer reaches it through the scene, not through the global.

| fact | address / value | status |
|---|---|---|
| class-name string | `0x1105E648` = `"CSceneDebugTextRenderer"` | CONFIRMED (image) |
| descriptor / first field written by the ctor | `0x1105E670` (`0x1040A60A: mov [edi], 0x1105E670`) | CONFIRMED |
| constructor | `0x1040A5F0` | CONFIRMED |
| factory (only caller of the ctor, `0x1040A813`) | `0x1040A810` | CONFIRMED |
| destructor / slot release (2 refcounted slots at `+0x94`) | `0x1040A5A0` | CONFIRMED |
| registration (registers sampler `"DiffuseSampler0"` `0x1105E660`, sets the descriptor) | `0x1040A560` | CONFIRMED |
| lazy class descriptor | `[0x1121EBF4] = 0x1105E648` **live** | CONFIRMED |
| **live instance** | **`0x1853BD00`** (581.6 MB scan, positive control passed) | CONFIRMED |
| `"DebugText"` effect handle `+0x28/+0x2C` (`0x1040A7EE`) | `{0x0F, 0}` live — resolved (miss would be `{0,0}`) | CONFIRMED |
| vertex-declaration build (semantic tags `0x5CE9B562`, `0xDF785C7B`, `0xA79767ED` via `0x10EC7E40` on `[0x1125A280]`) | `0x1040A725`–`0x1040A7A8` | CONFIRMED |
| `[0x1125A288]` lookup → `+0x90` | `0x1040A7DD` / `0x1040A7E2`; live `+0x90 = 3` | CONFIRMED |

The instance also embeds a `CDbgTextBatch` of its own at **`+0xA4`** (allocator tag `0x111B7F74` at
`+0xA8`, `strcap 15` at `+0xC0`, `+0x2C` flag `1` at `+0xD0`, `-1` at `+0xD4`, `-1.0f` at `+0xD8`,
`0.0f` at `+0xDC`, thread id at `+0xE0`) — pristine live.

**What is still not established:** the renderer's *draw* method, and therefore whether it consumes the
**pool's** batches (including the console's, slot 4) or only its own embedded one at `+0xA4`. The
descriptor at `0x1105E670` carries only a single code pointer (`0x1040A810`, the factory) — dispatch is
not through a conventional vtable — so the draw entry point has to be found another way. **That is the
open question, and §6.4 states how to close it read-only.**

Consequently the meaning of batch `+0x34` / `+0x38` is still unknown. What I can say:

* Neither is read anywhere in the batch code region `0x10081xxx`–`0x10083xxx`.
* The two pool managers share vtable slots 1–5 (`0x10061170`, `0x10086500`, `0x10084760`,
  `0x10087490`, `0x10084960`) — all thin `add ecx,0x20; jmp` thunks into generic pool plumbing, none of
  them a renderer. Only slot 6 differs (`0x10081F40` text / `0x100810D0` quad) and both forward to
  replication/sync code (`0x1006BC80` / `0x1006C200`), not drawing.
* The batches carry `GetCurrentThreadId()` at `+0x3C` and the pools use a per-slot dirty bit, which is
  the signature of a **game-thread → render-thread double-buffered attribute system**.
* **Every one of the 29 text-pool slots in the live process is pristine except the console's**
  (`+0x20 = NULL`, `strcap 15`, `+0x38 = 0.0`; the console's slot 4 is the only one with `+0x38 = -1.1`).
  ⇒ **No producer other than the console has ever filled a text batch.** That is why `gfx_ShowFPS` and
  `qc_ShowPlayerPos` showing nothing proves nothing about the rasteriser: those commands never reached
  the producer stage. See §0a Correction 2.

---

## 6. Addressing the batch correctly, and what to do next

### 6.0 — WITHDRAWN

The original §6.0 told you to treat "no FPS/stats overlay" as proof that the retail 2D debug-text pass
does not exist. **That inference is invalid and the step is withdrawn.** It was run, it came back
negative, and §0a Correction 2 shows why the negative means nothing: all 29 text-pool slots are
pristine, so those commands never filled a batch — the producer never ran, let alone the rasteriser.
The rasteriser demonstrably exists and is instantiated (§5.1).

### 6.1 — The batch address, derived from the instruction stream (**CORRECTED**)

`CFCXConsole::Update` does not compute the batch address inline. `esi` at `0x10EF3B01` is the **return
value** of `0x100758B0`:

```
10EF3ABB  6a 00                  push 0                     ; bInit = false
10EF3ABD  8d 83 80 00 00 00      lea  eax, [ebx+0x80]       ; &pUI->textHandle
10EF3AC3  50                     push eax
10EF3AC4  b9 68 8c 17 11         mov  ecx, 0x11178C68       ; this = the text pool
10EF3AC9  e8 e2 1d 18 ff         call 0x100758B0
10EF3ACE  8b f0                  mov  esi, eax              ; esi = the batch
...
10EF3B01  f3 0f 11 46 38         movss [esi+0x38], xmm0
```

**`0x100758B0` is the addressing model, and it dereferences three times after `pool+8`:**

```
100758B0  8b 44 24 04   mov eax, [esp+4]   ; handle*
100758B4  8b 00         mov eax, [eax]     ; idx   = handle[0]                       (= 4)
100758B8  8b f1         mov esi, ecx       ; esi   = pool                    (0x11178C68)
100758BA  8b 4e 08      mov ecx, [esi+8]   ; inner = *(pool + 8)             <-- DEREF 1
100758BE  8b 39         mov edi, [ecx]     ; base  = *inner                  <-- DEREF 2
100758CA  8d 2c 85 ..   lea ebp, [eax*4]   ; idx * 4        (stride 4: array of POINTERS)
100758D5  03 fd         add edi, ebp       ; edi   = base + idx*4
   ... (if the slot's dirty bit at [pool+0x30 + idx*8 + 3] & 1 is clear, fall straight through) ...
10075961  8b 07         mov eax, [edi]     ; batch = *(base + idx*4)         <-- DEREF 3
10075966  c2 08 00      ret 8
```

Literal C, all three dereferences explicit:

```c
#define TEXT_POOL  ((unsigned char*)0x11178C68u)   /* Dunia base 0x10000000, loads there */

unsigned char** inner = *(unsigned char***)(TEXT_POOL + 8);   /* DEREF 1 */
unsigned char** base  = *(unsigned char***)inner;             /* DEREF 2  (i.e. inner[0]) */
int             idx   = *(int*)(pUI + 0x80);                  /* = 4 */
unsigned char*  batch = base[idx];                            /* DEREF 3, stride 4 */
```

Equivalent collapsed form, **note the three `*`**:

```c
batch = (*(unsigned char***)(*(unsigned char***)(TEXT_POOL + 8)))[ *(int*)(pUI + 0x80) ];
```

#### 6.1.1 What went wrong

The expression in my hand-off message was `(*(void***)(TEXT_POOL + 8))[idx]`. That is **DEREF 1 only**,
then indexing — it computes `inner[idx]`, not `base[idx]`. `inner` is the container header, and its
dword at `+0x10` is the registered-slot count. Hence `inner[4]` returned `0x1D` = **29** = the slot
count, which also reads directly at `pool+0x34`. Dereferencing 29 as an address is the access violation.

#### 6.1.2 Verified live, both values reproduced (PID 8644, read-only)

```
pUI = 18784A60,  pUI+0x80 (slot idx) = 4

  100758BA  mov ecx,[pool+8]   -> inner      = 185C8640
  100758BE  mov edi,[ecx]      -> array base = 19FB2900
  100758D5  add edi, idx*4     -> &array[4]  = 19FB2910
  10075961  mov eax,[edi]      -> BATCH      = 19488440

  wrong form: ((void**)inner)[4] = *(185C8650) = 0x1D        <-- exactly what the DLL logged
  pool+0x34 (registered slot count) = 29 = 0x1D              <-- same number, confirming the cause
```

Batch `0x19488440` validates on every field: `+0x04` allocator tag `0x111B7F74` (narrow `DuniaString`),
`+0x30 = 0xFFFFFFFF`, `+0x34 = -1.0f`, `+0x38 = -1.1f`, `+0x3C` = a real thread id (20436).
**Prediction met.**

**Mandatory sanity gate before any dereference or write:** `*(unsigned int*)(batch+0x30) == 0xFFFFFFFF`
**and** `*(float*)(batch+0x34) == -1.0f`. If either fails, you resolved the wrong object — bail. Keep
the `VirtualQuery` validation that was added after the crash; it is correct practice here.

### 6.2 — Read-only instrumentation (no writes)

From the hook, after the original `UpdateUI` returns and with the console open, log
`*(int*)(batch+0x24)` (queued entry count) and `*(int*)(batch+0x18)` (queued char count). Non-zero
confirms in *this* session what was observed in PID 18964 (the vector had grown to 3072 slots): `Draw`
queues, and something after it drops the text. Note the pool is **double-buffered** — `base[idx]`
alternates between two objects across frames; both carry `+0x38 = -1.1`.

### 6.3 — Cosmetic, once text renders (**data only**)

`Draw` lays text out for a half-screen console (`y ≈ 0..526` at 1080p) while the panel animates only to
300 px. Either write `*(int*)(pUI+0x5C) = 560` **after** `Update` each frame (`Update` sets it to
`0x12C` at `0x10EF3AAD`), or leave it — the text is legible either way.

### 6.4 — The next step, and it is read-only

The open question is now precise: **does `CSceneDebugTextRenderer` (instance `0x1853BD00`) consume the
pool's batches, or only the one embedded in itself at `+0xA4`?** Answer it without writing anything:

1. Find the renderer's draw entry point. Dispatch is not via a normal vtable (`0x1105E670` holds one
   code pointer, the factory `0x1040A810`), so search for callers that pass `0x1853BD00`-class objects,
   or for code referencing the resolved effect handle slot `+0x28`, or xref `0x1040A810`.
2. Read, live, whether the renderer's own embedded batch at `+0xA4` ever becomes non-pristine while the
   console is open. If it fills while the pool's slot-4 batch also fills, the renderer copies; if only
   slot 4 fills, the renderer is not reading the pool for the console's attribute.
3. Only after step 1 or 2 gives a mechanism should any field be written.

**Do not poke `+0x38` on my say-so.** It is one candidate among several and I have no consumer-side
evidence for it. The previous poke cost a crash and that is not repeated here.

### 6.3 — Cosmetic, once text renders (**data only**)

`Draw` lays text out for a half-screen console (`y ≈ 0..526` at 1080p) while the panel animates only to
300 px. Either write `*(int*)(pUI+0x5C) = 560` **after** `Update` each frame (`Update` sets it to
`0x12C` at `0x10EF3AAD`), or leave it — the text is legible either way.

### 6.4 — Not needed (do **not** waste time on these)

* Re-running `InitResources` (`pUI` vtable slot 1, `0x10EF0EF0`): it already succeeded, and calling it
  again **leaks the current pool slots** — it overwrites the handles without releasing them.
* Anything to do with fonts: `CFCXConsole` holds no font handle.
* Anything to do with the input path, `BuildCharSignalMap`, or the input context: all confirmed working.
* Re-Printf'ing: the ring already holds 143 lines including all our test strings.

---

## 7. ~~RETRACTED~~ — REINSTATED: retail has no debug-text render pass

> **⚠ 2026-07-26, later the same day: the retraction below is itself WRONG and is withdrawn.
> The original §7 conclusion — "retail ships the producer half of the 2D debug-text system but not
> the render pass" — is CORRECT and is reinstated.** `RASTERISER.md` proves it two ways: no consumer
> reads the pool (696 iteration call sites swept, positive control on the quad pool passed), and
> `CSceneDebugTextRenderer`'s draw resolves to a three-byte `ret 0xC` stub at `0x106DAA10`, verified
> live. Points 1 and 2 below are individually true but do not support the conclusion they were used
> for: existing + being instantiated + resolving a shader handle does not imply having a draw body.
> Original retraction preserved below for audit.

The original §7 said that if the `Stats_*` / FPS overlays never appear, the honest conclusion is that
**retail ships the producer half of the 2D debug-text system but not the render pass**. The overlays
were tested and did not appear. ~~**That conclusion is nevertheless wrong and is retracted**~~, on two
independent pieces of live evidence:

1. **The rasteriser exists and is instantiated.** `CSceneDebugTextRenderer` (ctor `0x1040A5F0`) has one
   live instance at `0x1853BD00`, its class descriptor `[0x1121EBF4]` is populated, and its
   `"DebugText"` effect handle at `+0x28/+0x2C` reads `{0x0F, 0}` — resolved, not the `{0,0}` miss
   value that `0x10EBA3B0` would leave. Full evidence in §5.1 and §0a.
2. **The overlay test never exercised the rasteriser.** All 29 text-pool slots are pristine except the
   console's. `gfx_ShowFPS` / `qc_ShowPlayerPos` did not fill a batch, so the negative is about those
   CVars being inert, not about the render pass.

~~**Retail 1.02 therefore does have a 2D debug-text rasterisation pass.**~~ **FALSE — see the banner
above and `RASTERISER.md`.** The renderer object exists and its effect handle resolves, but its draw
method is a compiled-out stub and nothing reads the pool. The question §6.4 posed — "does it consume
the pool's batches or only its own embedded one at `+0xA4`?" — has the answer **neither**: its own
`+0xA4` batch is live-verified pristine (`entryBase = NULL`, `cap = 0`) and its draw does nothing.

**Independently of how that resolves**, the practical fallback is unchanged and already works: keep
driving commands through
`CConsole::ExecuteLine` and read results out of the ring buffer at `g_console+0x0C` from your injected
DLL (a read-only walk — `scripts/console_text_probe.py` already implements it), rendering them yourself
or logging them to a file. That is a complete, working substitute for the output pane, and it is what
we already know works.

---

## 8. Symbols added by this analysis

All `Dunia.dll`, base `0x10000000`, runtime == static.

### Functions

| VA | name | convention | notes |
|---|---|---|---|
| `0x100040D0` | `DuniaStringA::DuniaStringA(const DuniaStringW&)` | thiscall, `ret 4` | wide→narrow via `wcstombs` `[0x110003D4]`; wide SSO threshold is **8** |
| `0x1000A8B0` | `GetCurrentThreadId` (import thunk) | — | `jmp [0x110000B0]` |
| `0x10062B00` | `PrimitivePool::Peek(handle*)` | thiscall | returns the batch **without** clearing the dirty bit |
| `0x10075600` | `TextPool::Create(out uint32[2], bool)` | thiscall, `ret 8` | allocates a `0x40`-byte batch, returns `{slotIndex, tag}` |
| `0x10075710` | `TextPool::Release(slotIndex, tag)` | thiscall, `ret 8` | |
| `0x100758B0` | `TextPool::Get(handle*, bool bInit)` | thiscall, `ret 8` | reads **word 0 only**; returns `array[slotIndex]` |
| `0x10076220` / `0x10076330` / `0x100764D0` | the same three for the **quad** pool | thiscall | |
| `0x10081480` | `CDbgQuadBatch::Clear()` | thiscall | |
| `0x10081D10` | entry-vector `push_back` (`0x30`-byte entries) | — | |
| `0x10081ED0` | `CDbgTextBatch::CDbgTextBatch()` | thiscall | `0x40` bytes; `+0x34 = -1.0f`, **`+0x38 = 0.0f`**, `+0x3C = tid` |
| `0x10082000` | append raw chars to the batch's char stream | thiscall | |
| `0x10082140` | **`CDbgTextBatch::AddText(Vec3* pos, Vec4* col, int flags, const char* s)`** | thiscall, `ret 0x10` | byte-wise `strlen`; no-ops on empty |
| `0x100821E0` | **`CDbgTextBatch::AppendText(const char* s)`** | thiscall, `ret 4` | extends the last entry |
| `0x10082230` | **`CDbgTextBatch::Clear()`** | thiscall | empties `+0x04` and `+0x20`; leaves `+0x34/+0x38` |
| `0x100A7600` | `CConsole::LockLines()` | thiscall | `EnterCriticalSection(g_console+0x88)`, `+0xA4` ++ |
| `0x100A7620` | `CConsole::UnlockLines()` | thiscall | |
| `0x100A78F0` | `DuniaStringW::find(ch, pos, dir)` | thiscall | used by `AddLine` to split on CR/LF |
| `0x100AB660` | **`CConsole::AddLine(DuniaStringW*)`** | thiscall, `ret 4` | the ring writer |
| `0x10EF0910` | `CFCXConsole::DrawPanel(quadBatch, …)` | usercall (`esi`=batch, `edi`=0x17, `xmm0`=fade) | the translucent panel |
| `0x10EF0C20` | `CFCXConsole::GetLayoutMetrics(float* one, float* zero, float* w, float* h)` | cdecl | `GetClientRect` + aspect fixup |
| `0x10EF0F50` | `CFCXConsole::ReleaseResources()` | thiscall | releases both pool handles |
| `0x103B4E70` | `GetDebugText2DMetrics()` | cdecl | `*(void**)0x111E3E54 + 0x14`; `+2` byte, `+8` w, `+0xC` h |

### Globals

| VA | meaning | live (PID 18964) |
|---|---|---|
| `0x11178C48` / `0x11178C68` | text primitive **manager** / its pool sub-object | vtable `0x11017A58` |
| `0x11178AF8` / `0x11178B18` | quad primitive **manager** / its pool sub-object | vtable `0x110179B4` |
| `0x11178CD8` | a third primitive pool | — |
| `0x11142824` | `-1.1f` — written to the console text batch `+0x38` | shared with 2 unrelated sites |
| `0x111421F0` | `14.0f` — console line spacing | |
| `0x111421F4` | `42.0f` — console top margin | |
| `0x11142820` | `" >"` — the prompt literal | |
| `0x1114281C` | `"  "` — pre-cursor pad | |
| `0x11013AB8` | `"|"` — the cursor glyph | |
| `0x111E3E54` | debug-text metrics owner | `0x1849ED20` (⇒ metrics at `0x1849ED34`, 1920×1080) |
| `0x111E3B9C` | aspect-mode owner (`+0x40`) | `0x0A0E6B10`, mode `0` |
| `0x111CAEF4` | byte gate for the `Stats_*` overlay | `0` |
| `0x1125AE90` | `OnSignal` magic-static **bit-mask** (19 bits) | `0x7FFFF` = fully initialised |

### `CConsole` layout additions

| off | field | live |
|---|---|---|
| `+0x04` | `TRingBuffer<DuniaStringW*>` (embedded) | |
| `+0x0C` | `DuniaStringW** m_ppLines` | `0x3CC98470` |
| `+0x10` | `int m_nCapacity` | `181` |
| `+0x14` | `int m_nHead` | `0` |
| `+0x18` | **`int m_nCount`** — `Draw` skips all scrollback when 0 | `143` |
| `+0x68` | **`bool m_bEchoEnabled`** — `Printf` silently returns when `flags != 0` and this is 0 | `1` |
| `+0x69` | `bool m_bUIActive` | |
| `+0x88` | `CRITICAL_SECTION` | |
| `+0xA4` | lock recursion count | |

### `CFCXConsole` layout corrections

| off | corrected meaning | live |
|---|---|---|
| `+0x34` | `DuniaStringW` prompt/scratch (**wide**) | empty |
| `+0x54` | scroll offset — `Draw` skips lines with `i < this` | `0` |
| `+0x60` | `DuniaStringW` input line (**wide**) | `"ffddfv"` |
| `+0x74` | *not a field* — it is `+0x60`'s `+0x14` length member | `6` |
| `+0x7C` | cursor column | `6` |
| `+0x80/+0x84` | **text pool handle `{slotIndex, tag}`** — not a font handle | `{4, 0}` |
| `+0x88/+0x8C` | **quad pool handle `{slotIndex, tag}`** — not a font handle | `{3, 1}` |

---

## 9. Honest limits

* **Two claims from the first issue of this document were wrong and are corrected in place** (§0a):
  the collapsed batch-addressing one-liner in my hand-off message (one dereference short — it crashed
  the game), and the suggestion that a negative overlay test would prove retail has no debug-text
  render pass (it would not, and the pass demonstrably exists). Both are now backed by live evidence
  rather than inference.
* **⚠ CLOSED SINCE, in `RASTERISER.md`:** the two "still NOT established" bullets below are now
  answered. Nothing consumes the pool; `CSceneDebugTextRenderer`'s draw is a `ret 0xC` stub; its own
  `+0xA4` batch is live-pristine; `+0x34`/`+0x38` are never read by anything, so the `-1.1f` anomaly
  is a dead end with a mechanism. Read that document rather than acting on the text below.
* **ESTABLISHED since:** the rasteriser `CSceneDebugTextRenderer` exists, is registered
  (`[0x1121EBF4]` populated), has exactly one live instance (`0x1853BD00`), and its `"DebugText"`
  effect handle resolved (`{0x0F, 0}`). The memory scan that found it carried a positive control that
  passed; an earlier narrower scan returned a false negative, which is why the control was added.
* **Still NOT established:** the renderer's draw entry point, and therefore whether it consumes the
  pool's batches (the console's slot 4) or only its own embedded batch at `+0xA4`. Consequently the
  meaning of batch `+0x34` / `+0x38` is still unknown, and the `+0x38 = -1.1f` anomaly is
  **HYPOTHESIS** — the only structural outlier and the only site in the binary that writes it, but with
  **zero consumer-side evidence**. It should not be written to until §6.4 step 1 or 2 yields a
  mechanism.
* **Still NOT established:** why `gfx_ShowFPS` / `qc_ShowPlayerPos` are inert. Evidence says they never
  reach the producer (their batches are pristine), i.e. the CVars themselves are dead — but that was
  not chased.
* **Everything in §§1–4 is CONFIRMED** by disassembly plus live read-only observation, and none of it
  depends on any hypothesis above. In particular: nothing inside `Draw` gates the text, `Printf`'s
  buffer *is* `Draw`'s buffer and our test strings are in it, `+0x80..+0x8C` are pool handles rather
  than font handles, and the input path is complete end-to-end.
* No byte of the live process was written. No game file was modified.
