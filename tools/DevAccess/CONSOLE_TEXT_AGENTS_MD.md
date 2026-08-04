# Paste-ready `agents.md` sections — console text rendering

Style-matched to the existing `agents.md` / `CONSOLE_GATE_AGENTS_MD.md` sections. Source of record:
`DevAccess/CONSOLE_TEXT.md`. Verified 2026-07-26 against `Dunia.dll` retail 1.02 (base `0x10000000`,
static == runtime) and live `Avatar.exe` PID 18964, read-only.

---

## Avatar 2009 — the console panel opens but draws no text (CONFIRMED diagnosis, fix UNPROVEN)

`CConsole::SetUIActive(g_console, 1)` opens the console and the translucent panel renders. No text
appears. **The cause is not in `CFCXConsole::Draw` and not in `CConsole::Printf` — both work.**

Confirmed live, in order:

* `CConsole::Printf` (`0x100AC0C0`, **cdecl**, `(this, int flags, const char* fmt, ...)`) lands. The
  literal test string `"DEVACCESS printf test - flags=3 - if you can read this, output works"` was read
  back out of the live ring buffer.
* That ring **is** the one `Draw` reads. `CConsole::AddLine` (`0x100AB660`) writes `g_console+0x0C`
  (array) / `+0x10` (capacity) / `+0x14` (head) / `+0x18` (count); `Draw` reads the same four at
  `0x10EF2E7A`, `0x10EF2E7D`, `0x10EF2EA1`, `0x10EF2EAF`. Live: 143 lines.
* `Draw` **is** executing — it sits inside the *same* `height > 0` gate (`0x10EF3B1B`) as the panel
  draw call (`0x10EF0910`), and the panel is visibly on screen.
* `Draw` **is** queuing glyphs — the console's render batch has grown to **3072 entry slots / 2979
  character capacity**. Every other text batch in the process is pristine.
* Typing works. `pUI+0x60` held the wide string `"ffddfv"`, `len=6`, cursor `pUI+0x7C = 6`, and the
  input context `pUI+0x30` = `0x3E8` (it was `0xFFFFFFFF` before `SetActive`).

**⇒ The break is strictly downstream of `Draw`: the queued text batch is never rasterised.**

### The one anomaly

`CFCXConsole::Update` (`0x10EF3A80`) writes `-1.1f` into the **text** batch's `+0x38`, and `-1.0f` into
the **quad** batch's `+0x88`. The quad batch draws the panel you can see; the text batch draws nothing.

```
10EF3AF5  f3 0f 10 05 24 28 14 11   movss xmm0, [0x11142824]   ; -1.1f
10EF3B01  f3 0f 11 46 38            movss [esi+0x38], xmm0     ; textBatch->+0x38 = -1.1f
10EF3B06  f3 0f 10 05 b4 3a 01 11   movss xmm0, [0x11013AB4]   ; -1.0f
10EF3B0E  f3 0f 11 81 88 00 00 00   movss [ecx+0x88], xmm0     ; quadBatch->+0x88 = -1.0f
```

Constructor default for `+0x38` is `0.0f` (`0x10081F27`), and **every other live text batch reads
`0.0`**. `0x10EF3AF9` is the only site in the whole `.text` that stores `-1.1f` into a text batch.
**HYPOTHESIS only** — the render-side consumer of these batches was not located, so the meaning of
`+0x38` is unknown.

### Retail DOES have a 2D debug-text rasteriser — do not close this as a negative

`gfx_ShowFPS 1` and `qc_ShowPlayerPos 1` produce no on-screen overlay in retail (also confirmed inert
via config/XML). **That does not mean the text layer is dead.** Confirmed live:

* `CSceneDebugTextRenderer` — ctor `0x1040A5F0`, factory `0x1040A810`, descriptor `0x1105E670`,
  class-name string `0x1105E648`, registration `0x1040A560`, destructor `0x1040A5A0`.
* Lazy class descriptor `[0x1121EBF4] = 0x1105E648` **live** (control: `[0x11227F80]`, `CFCXConsole`,
  reads `0` — never queried).
* **Exactly one live instance at `0x1853BD00`**, found by scanning all 581.6 MB of committed writable
  memory. The scan carried a positive control — `CFCXConsole` vtable `0x11142220` — which returned
  exactly one hit at the independently-known address. *A first, narrower scan restricted to
  `MEM_PRIVATE` returned zero: a false negative. Always carry a positive control when scanning this
  process.*
* Its `"DebugText"` effect handle (`0x1040A7EE`, name string `0x1105E674`, via `0x10EBA3B0` on
  `[0x1125A1D8]`) reads `{0x0000000F, 0x00000000}` at `+0x28/+0x2C`. `0x10EBA3B0` zero-initialises its
  out-param (`0x10EBA3B5`/`0x10EBA3B8`), so `{0,0}` is the miss value — **the shader resolved.**

Why the overlay test proved nothing: **all 29 text-pool slots are pristine except the console's**
(`+0x20 = NULL`, `strcap 15`, `+0x38 = 0.0`). Those commands never filled a batch, so the producer
never ran, let alone the rasteriser. The CVars themselves are inert — the same retail-strip pattern as
the dead `toggle_console` / `cheat_menu` signal cases.

**Open question, now narrow:** does the renderer consume the *pool's* batches (the console's slot 4) or
only its own `CDbgTextBatch` embedded at `+0xA4`? Its dispatch is not a normal vtable — `0x1105E670`
holds a single code pointer (the factory) — so the draw entry point must be found another way. Close
this **read-only** before writing any field.

### Addressing a render batch — the model, derived from `0x100758B0`

`CFCXConsole::Update` does not compute the address inline; `esi` at `0x10EF3B01` is the **return value**
of `0x100758B0` (called at `0x10EF3AC9`). That function dereferences **three** times after `pool+8`:

```
100758B4  8b 00      mov eax,[eax]     ; idx   = handle[0]              (pUI+0x80 = 4)
100758BA  8b 4e 08   mov ecx,[esi+8]   ; inner = *(pool + 8)            <-- DEREF 1
100758BE  8b 39      mov edi,[ecx]     ; base  = *inner                 <-- DEREF 2
100758CA  8d 2c 85   lea ebp,[eax*4]   ; idx * 4   (array of POINTERS, stride 4)
100758D5  03 fd      add edi,ebp
10075961  8b 07      mov eax,[edi]     ; batch = *(base + idx*4)        <-- DEREF 3
```

```c
#define TEXT_POOL ((unsigned char*)0x11178C68u)      /* Dunia base 0x10000000, loads there */
unsigned char** inner = *(unsigned char***)(TEXT_POOL + 8);   /* DEREF 1 */
unsigned char** base  = *(unsigned char***)inner;             /* DEREF 2 (== inner[0]) */
unsigned char*  batch = base[ *(int*)(pUI + 0x80) ];          /* DEREF 3, stride 4 */
```

**Trap — this cost a crash once.** `(*(void***)(TEXT_POOL+8))[idx]` is one dereference short: it
yields `inner[idx]`, and `inner+0x10` holds the registered-slot count, so it returns **`0x1D` = 29**
(= `pool+0x34`). Dereferencing 29 as an address is an access violation.

Verified live (PID 8644): `inner = 185C8640`, `base = 19FB2900`, `&base[4] = 19FB2910`,
`batch = 19488440` — `+0x04` tag `0x111B7F74`, `+0x30 = FFFFFFFF`, `+0x34 = -1.0f`, `+0x38 = -1.1f`,
`+0x3C` = a real thread id. Wrong form: `*(185C8650) = 0x1D`. Both values reproduced exactly.

**Mandatory gate before dereferencing or writing:** `*(uint*)(batch+0x30) == 0xFFFFFFFF` **and**
`*(float*)(batch+0x34) == -1.0f`. The pool is **double-buffered** — `base[idx]` alternates between two
objects across frames; both carry the same `+0x38`.

### The `+0x38 = -1.1f` anomaly — HYPOTHESIS ONLY, do not poke on spec

Ctor default is `0.0f` (`0x10081F27`); every other live text batch reads `0.0`; `0x10EF3AF9` is the
only site in `.text` that writes `-1.1f` into a text batch. It is the only structural outlier — but
there is **no consumer-side evidence** that it is what suppresses the text, because the consumer path
has not been read. Establish a mechanism first.

**Do not patch the constant at `0x11142824`** — it is shared with `0x10EFB480` (array base) and
`0x10F482FA` (a `±1.1` clamp).

**Do not re-call `InitResources`** (`0x10EF0EF0`) — it already ran successfully, and calling it again
leaks the pool slots (it overwrites the handles without releasing them).

---

## Avatar 2009 — corrections to `CONSOLE_GATE.md`

### `CFCXConsole+0x80..+0x8C` are pool handles, **not** font/render resource handles

`CFCXConsole::InitResources` (`0x10EF0EF0`) stores **two `{slotIndex, tag}` pairs** for two
render-primitive pools:

| off | pool | Create / Get / Release | live |
|---|---|---|---|
| `+0x80`,`+0x84` | text pool `0x11178C68` | `0x10075600` / `0x100758B0` / `0x10075710` | `{4, 0}` |
| `+0x88`,`+0x8C` | quad pool `0x11178B18` | `0x10076220` / `0x100764D0` / `0x10076330` | `{3, 1}` |

`Get` reads **word 0 only** (`0x100758B4: mov eax,[eax]`) and returns `array[slotIndex]`. **`+0x84 = 0`
is not a missing handle** — it is the release tag. `CFCXConsole` holds **no font handle at all**; fonts
belong to the text-primitive system. `InitResources` ran fully: both handles resolve to live batch
objects (`0x19EFD280`, `0x19979480`) with well-formed slot records.

### `DuniaString` comes in two flavours; console lines are the **wide** one

| | narrow `DuniaStringA` | wide `DuniaStringW` |
|---|---|---|
| allocator tag `+0x00` | `0x111B7F74` | `0x111B7F75` |
| `+0x14` / `+0x18` | length / capacity in **chars** | in **wchars** |
| SSO threshold | `capacity >= 0x10` ⇒ heap | **`capacity >= 8`** ⇒ heap |

The console scrollback ring, `pUI+0x34` and `pUI+0x60` are all **wide**. `ExecuteLine` /
`DuniaString::DuniaString(const char*)` (`0x10003E20`) take the **narrow** one — the existing
`CONSOLE_GATE.md` §5.3 recipe is unaffected and remains correct.

`Draw` converts correctly: `0x100040D0` is `DuniaStringA::DuniaStringA(const DuniaStringW&)`,
allocating `2·len+2` bytes and calling `wcstombs` (`[0x110003D4]`). Encoding is not a bug.

### `[0x1125AE90] = 0x7FFFF` is expected, not suspicious

It is an MSVC **bit-mask** magic-static guard inside `CFCXConsole::OnSignal` — one bit per cached
CRC32. `OnSignal` contains **exactly 19** stores to it (`0x10EF32A5` … `0x10EF346A`), so 19 bits set =
`0x7FFFF` = *all statics initialised*. It means `OnSignal` executed to completion. Same pattern as
`[0x1125AE40]`, which is a single-bit guard.

### `CFCXConsole+0x74` is not a field

It is `pUI+0x60`'s (`DuniaStringW`) `+0x14` length member. `+0x54` **is** a real field: the scroll
offset, compared against the line index at `0x10EF2E94`.

### New `CConsole` fields

| off | field | note |
|---|---|---|
| `+0x04` | embedded ring buffer of `DuniaStringW*` | |
| `+0x0C` / `+0x10` / `+0x14` / `+0x18` | array / capacity / head / **count** | `Draw` skips all scrollback when count is 0 (`0x10EF2E8A`) |
| `+0x68` | **`m_bEchoEnabled`** | `Printf` silently returns at `0x100AC0DD` when `flags != 0` and this is 0 |
| `+0x88` | `CRITICAL_SECTION` guarding the ring | `Lock 0x100A7600` / `Unlock 0x100A7620` |
| `+0xA4` | lock recursion counter | |

### Console text layout (for when it renders)

From `0x10EF0C20` + `Draw`: `x = 1.0`, colour white, scrollback starts at
`y = clientHeight * 0.5 - 42` (or `* 0.3` if `[metrics+2] == 0`) and walks **up** 14 px per line;
prompt `" >"` / input line / cursor `"|"` at `y = clientHeight * 0.5 - 14`. At 1080p that is
y ≈ 0..526, while the panel only animates to 300 px (`0x10EF3AAD`) — expect overflow. Cosmetic only;
optionally write `*(int*)(pUI+0x5C) = 560` after `Update` each frame.

---

## Avatar 2009 — new symbols (Dunia.dll, base `0x10000000`)

| VA | name |
|---|---|
| `0x100040D0` | `DuniaStringA::DuniaStringA(const DuniaStringW&)` — wide→narrow, `ret 4` |
| `0x1000A8B0` | `GetCurrentThreadId` import thunk |
| `0x10062B00` | `PrimitivePool::Peek(handle*)` |
| `0x10075600` / `0x100758B0` / `0x10075710` | text pool Create / Get / Release |
| `0x10076220` / `0x100764D0` / `0x10076330` | quad pool Create / Get / Release |
| `0x10081480` | `CDbgQuadBatch::Clear()` |
| `0x10081D10` | entry-vector `push_back` (`0x30`-byte entries) |
| `0x10081ED0` | `CDbgTextBatch::CDbgTextBatch()` — `0x40` bytes, `+0x34=-1.0f`, `+0x38=0.0f`, `+0x3C=tid` |
| `0x10082140` | `CDbgTextBatch::AddText(Vec3*, Vec4*, int flags, const char*)`, thiscall `ret 0x10` |
| `0x100821E0` | `CDbgTextBatch::AppendText(const char*)`, thiscall `ret 4` |
| `0x10082230` | `CDbgTextBatch::Clear()` |
| `0x100A7600` / `0x100A7620` | `CConsole::LockLines` / `UnlockLines` |
| `0x100A78F0` | `DuniaStringW::find(ch, pos, dir)` |
| `0x100AB660` | **`CConsole::AddLine(DuniaStringW*)`** — Printf's ring writer |
| `0x10EF0910` | `CFCXConsole::DrawPanel` (usercall: `esi`=quad batch, `edi`=0x17, `xmm0`=fade) |
| `0x10EF0C20` | `CFCXConsole::GetLayoutMetrics(float*,float*,float*,float*)`, cdecl |
| `0x10EF0F50` | `CFCXConsole::ReleaseResources()` |
| `0x103B4E70` | `GetDebugText2DMetrics()` — `+2` half-height flag, `+8` width, `+0xC` height |
| `0x1040A560` | `CSceneDebugTextRenderer::Register()` — sampler `"DiffuseSampler0"`, sets `[0x1121EBF4]` |
| `0x1040A5A0` | `CSceneDebugTextRenderer::ReleaseSlots()` — 2 refcounted slots at `+0x94` |
| `0x1040A5F0` | **`CSceneDebugTextRenderer::CSceneDebugTextRenderer()`** — sets `[this] = 0x1105E670` |
| `0x1040A810` | `CSceneDebugTextRenderer` factory (only caller of the ctor, at `0x1040A813`) |
| `0x10EBA3B0` | `EffectLibrary::FindByName(const char*)` → 64-bit handle in `edx:eax`; zero-inits, so `{0,0}` = miss |
| `0x10EC7E40` | vertex-declaration element add (semantic tags `0x5CE9B562`, `0xDF785C7B`, `0xA79767ED`) |

Globals: `0x11178C48`/`0x11178C68` text primitive manager/pool · `0x11178AF8`/`0x11178B18` quad ·
`0x11178CD8` third pool · `0x11142824` `-1.1f` (**shared**, do not patch) · `0x111421F0` `14.0f` line
spacing · `0x111421F4` `42.0f` top margin · `0x11142820` `" >"` prompt · `0x1114281C` `"  "` ·
`0x11013AB8` `"|"` cursor · `0x111E3E54` metrics owner · `0x111E3B9C` aspect-mode owner ·
`0x111CAEF4` `Stats_*` overlay gate.

Also: `0x1105E648` `"CSceneDebugTextRenderer"` · `0x1105E660` `"DiffuseSampler0"` · `0x1105E670`
renderer descriptor · `0x1105E674` `"DebugText"` effect name · `0x1121EBF4` renderer class-desc (lazy,
**populated** live) · `0x1125A1D8` effect library · `0x1125A280` vertex-decl library · `0x1125A288`
(→ renderer `+0x90`) · `0x11017A44` `"CSceneDebugText"` (the pool manager class) · `0x110179D0`
`"CSceneParticleAttributes"` (the quad pool manager class).

Tooling, both read-only, in `DevAccess/scripts/`:

* `console_text_probe.py` — live dump of the console ring buffer (decodes the wide strings), the
  `CFCXConsole` fields, and both render batches, using the **correct** three-deref pool addressing.
  Confirms whether Printf landed and whether `Draw` queued anything.
* `dunia_objscan.py` — scans all committed writable memory for instances of a given vtable/descriptor,
  **with a mandatory positive control** so a too-narrow region filter cannot produce a false negative.
  This is how `CSceneDebugTextRenderer @ 0x1853BD00` was found after a first scan wrongly returned zero.
