# CONSOLE_INPUT_BUG — why gameplay keys land in the console input line

> **✅ FIXED — verified in source 2026-08-04. This document is now the record of
> a solved bug, not an open one.**
>
> Hunk 1 (§5) is present: the closed→open edge drains the OS's own sticky
> `GetAsyncKeyState` low bits with `for (vk = 0x08; vk <= 0xFE; ++vk)
> (void)GetAsyncKeyState(vk);` before the first real poll pass, and clears
> `down[]`, `downAt[]` and `lastRep[]` alongside it.
>
> The **same fix was later needed a second time, at a different edge**, which is
> worth more than the original finding: the picker-open path cleared `down[]`
> and nothing else, so the pending `VK_RETURN` from the ENTER that opened it was
> still sitting in the OS. `PkKey` maps `VK_RETURN` to `PickerCommit`, so the
> picker spawned its first row the instant it appeared, every time. Same
> mechanism, different edge, found only after shipping. **Any new path that
> starts consuming keys must drain first** — the comment at that site now says so.
>
> The line counts and mtimes below describe the July source. The file is
> **19,615 lines** as of 2026-08-04. Everything else here — the mechanism, the
> ascending-VK-order evidence, the proof that fix attempt #1 was dead code —
> stands and is why the fix works.

Investigation only. Nothing under `D:\Games\Avatar The Game\` was touched, and
`avatar_console.c` / `lib.xml` / `build.bat` were **not** modified.

Subject: `C:\Test\Avatar 2009 Documentation\DevAccess\console_dll\avatar_console.c`
(16,263 lines, mtime 2026‑07‑28 18:08; the DLL next to it is 18:09, so the source
below **is** the build that still shows the bug, including both previous fix
attempts).

Corroborating runtime log:
`C:\Test\Avatar 2009 Documentation\DevAccess\console_dll\avatar_console_dll.log`

---

## 0. Verdict up front

**CONFIRMED.** One defect, fully traced from keystroke to buffer append.

> `InputThread` stops polling the keyboard entirely while the panel is closed
> (line 13717). `GetAsyncKeyState`'s low bit — "pressed since the previous call
> **for that key**" — is *sticky*: nothing clears it except a read. So every
> gameplay key you touch while the console is closed leaves its low bit set,
> unread, for the whole closed period. The instant F9 opens the panel, the first
> poll pass reads all ~240 virtual keys, sees those stale low bits, and the
> `else if (tapped)` branch at **line 13749** emits a synthetic keypress for each
> one straight into `InKey` → `g_in`.

Two consequences that match the report exactly:

1. The characters are produced **at open time**, when `g_consoleOpen` is already
   `1`. That is why fix attempt #1 (the `!g_consoleOpen` gate inside `InKey`)
   changed nothing — see §3, that gate is provably **dead code**.
2. Nothing clears `g_in` on close (§4.2), so each open/close cycle *adds* another
   handful of characters. They "accumulate invisibly and appear the next time the
   panel is opened", which is the user's description word for word.

The user's own framing — "the console is receiving input while it is closed" — is
the correct *observation* but the wrong *mechanism*. The console receives nothing
while closed; it harvests the OS's record of what happened while it was closed,
in one burst, at the moment it opens.

Ordering evidence: the poll is `for (vk = 0x08; vk <= 0xFE; ++vk)`, so the burst
comes out in **ascending VK order**. `A`=0x41, `D`=0x44, `S`=0x53, `W`=0x57 →
`adsw`. The user's screenshot shows gibberish beginning `aw`. A run that starts
with `a` and contains `w`, with no other ordering, is what this mechanism
produces and is not what a live per-keystroke leak would produce (that would be
in typing order, and would be far longer).

---

## 1. Every path by which a key event can reach the console input line

Exhaustive. I enumerated all keyboard-capable entry points and then checked which
of them can actually write `g_in` / `g_inLen` / `g_inCol`.

| # | Path | Lines | Reaches `g_in`? |
|---|------|-------|-----------------|
| 1 | **`InputThread` polling pump** → `InKey` | 13671–13795, call at **13774** | **YES — the only one** |
| 2 | `GameWndProc` (subclass on the game's HWND) | 213–332, installed 334–339 | No. Handles only `WM_ACTIVATEAPP`, `WM_ENTERSIZEMOVE`/`WM_EXITSIZEMOVE`, `WM_SETCURSOR`, `WM_MOUSEACTIVATE` and mouse buttons/wheel/move. **No `WM_KEYDOWN`/`WM_CHAR` case at all.** |
| 3 | `OverlayWndProc` (overlay + focus windows) | 15488–15521 | No. `switch (m)` covers only `WM_MOUSEMOVE`, `WM_LBUTTONDOWN`, `WM_LBUTTONUP`, `WM_MOUSEWHEEL`; everything else → `DefWindowProcW`. |
| 4 | `MsgHookProc` — `WH_GETMESSAGE` | 11987–11995, installed 11999–12008 | No. Filters for exactly one private message, `WM_WARP_NOW`, then `CallNextHookEx`. It is the warp trampoline, not an input hook. |
| 5 | `WH_KEYBOARD_LL` low‑level hook | declared 13190 (`g_kbHook`), ring `g_kq` 13201–13206 | **Dead.** `g_kbHook`, `g_kq`, `g_kqHead`, `g_kqTail`, `g_kbThread`, `g_kbTid`, `g_hookCalls`, `g_lastHookCalls` are *declared and never referenced again anywhere in the file*. No `SetWindowsHookEx(WH_KEYBOARD_LL,…)` exists. Confirmed by full-file grep — the only `SetWindowsHookExW` in the file is the `WH_GETMESSAGE` one at 12005. (Comment at 13666 says as much: it "installed cleanly and was never once invoked".) The `RawKey`/ring vocabulary is a leftover; the poll now synthesises `RawKey` directly at 13767–13774. |
| 6 | `PickerEditProc` / `PickerListProc` — real subclassed EDIT/LISTBOX | 14316–14353, 14373–14398; installed 15302–15303 | No. These feed the picker's own search box (`g_pickEd`), never `g_in`. |
| 7 | DirectInput / raw input | — | Not hooked. The DLL never touches `dinput8`/`IDirectInputDevice`/`RegisterRawInputDevices`. The only mentions are comments (170, 407–424, 12318, 15560) explaining why the *game's* DirectInput is worked around by moving the foreground. |
| 8 | Engine-side console text hooks | — | None. The only engine hook is `vtable[1]` → `hkUpdateUI` (12172, installed 12549–12550). It calls no key handler; it is the per-frame main-thread trampoline. |
| 9 | Other writers of `g_in` | `TabCompleteWorld` 13424–13426, `TabComplete` 13460–13462, `InSubmit` 13494 | All three are reached **only from inside `InKey`** (`TabComplete` at 13566; `InSubmit` at 13570). No independent entry. |

So the append surface is a single funnel: **`InputThread` → `InKey` → `g_in`.**
That is what makes the trace closable.

---

## 2. The gates, and whether they reflect panel-open state

The F9 toggle maintains **two** flags, and — contrary to the hypothesis in the
brief — they are perfectly paired. I enumerated every write:

```
g_ourPanel     writes: 15774(Rescue)  16137(open)  16143(close)  16150(panic)  16199(unload)
g_consoleOpen  writes: 15773(Rescue)  16138(open)  16144(close)  16151(panic)  16200(unload)
```

Every single site writes both, adjacently, to the same value. There is **no**
path that sets one without the other, and no "set on open but not cleared on
close" flag. `g_pickerOpen` is likewise clean (written at 14294, 15346, 15595,
and force-cleared whenever `!g_ourPanel` at 15593–15596).

The comment on line 128 — `/* cached by the overlay thread */` — is **stale**.
The overlay thread does not write `g_consoleOpen` any more. Worth correcting so
the next reader does not chase it, but it is not the bug.

Gates on the live path:

| Gate | Line | Correct? |
|------|------|----------|
| `if (g_ownInput && g_consoleOpen && g_gameWnd && mine)` — the poll | 13717 | Reflects panel state correctly. **This is the gate that creates the bug**, by not polling while closed. |
| `if (!g_consoleOpen && !g_pickerOpen) { clear; return; }` — inside `InKey` | 13515–13518 | Correct in isolation, **unreachable** (§3). |
| `g_ownInput` | 126 | Initialised `1`, **never written again** anywhere in the file. The comment "(F8)" is stale — F8 is noclip now (16087–16119). So this term is a constant `1`. Harmless, but it means the F8 comment misleads. |

---

## 3. Why fix attempt #1 could never have worked (proof)

`InKey` has exactly **one** caller: line 13774. That call site sits inside the
`if (g_ownInput && g_consoleOpen && g_gameWnd && mine)` block opened at 13717 and
closed at 13776. Therefore:

> `InKey` is never entered with `g_consoleOpen == 0`.

The guard added at 13515–13518 is dead code on both of its effects:

* its `return` can never fire — the caller already filtered;
* **its `g_in` clear can never fire either** — which is why the accumulated
  garbage is never wiped (see §4.2).

Fix attempt #2 (`SetGameInput`, lines 381 and 396) is orthogonal: it governs
whether the *game* receives input, not whether *we* append. It fixed a real
separate bug and could not have touched this one.

---

## 4. The defect, traced end to end

### 4.1 PRIMARY — stale `GetAsyncKeyState` low bits harvested on the open edge

`avatar_console.c:13717–13779`

```c
        if (g_ownInput && g_consoleOpen && g_gameWnd && mine) {
            DWORD now = GetTickCount();
            int vk;
            for (vk = 0x08; vk <= 0xFE; ++vk) {
                ...
                int async  = GetAsyncKeyState(vk);
                int tapped = (async & 0x0001) != 0;  /* pressed since last poll */
                isDown     = (async & 0x8000) != 0;  /* physically down NOW      */

                if (isDown && !down[vk]) { ... }
                else if (!isDown && down[vk]) { down[vk] = 0; continue; }
                else if (isDown && down[vk]) { ...repeat... }
                else if (tapped) {          /* <-- 13749 */
                    down[vk] = 0;
                } else {
                    continue;
                }
                { RawKey rk; ...; InKey(&rk); }     /* <-- 13774 */
            }
        } else {
            memset(down, 0, sizeof(down));          /* <-- 13778 */
        }
```

Step by step, console **closed**, player walking on WASD:

1. `g_consoleOpen == 0`, so control takes the `else` at 13777. `memset(down,…)`
   clears **our shadow array**. It does *not* read the keyboard.
2. Because nothing in the loop calls `GetAsyncKeyState('W')`, the OS's
   "pressed‑since‑last‑call" low bit for `W` is **set by the first press and
   never consumed**. Same for `A`, `S`, `D`, `Space`, `E`, `Q`, `R`, `F`,
   `1`–`9`, `Tab`, `Enter`, `Escape`, the arrows, `F1`–`F4`, and everything else
   in `0x08..0xFE` that is not in the skip list at 13722–13728.
3. The game reads the keyboard through DirectInput. DirectInput does **not**
   clear `GetAsyncKeyState`'s low bit. Only a `GetAsyncKeyState` call does. This
   is exactly the "duplicate delivery, not a steal" the user observed: the game
   gets its input *and* the bit stays pending for us.
4. User presses F9. Hotkey thread, 16136–16141: `g_ourPanel = 1`,
   `g_consoleOpen = 1`.
5. Within ≤8 ms the poll wakes (13792) and the branch at 13717 is now taken.
6. For each `vk`: `async = GetAsyncKeyState(vk)` → `isDown = 0` (key long
   released), `down[vk] = 0` (memset at step 1), `tapped = 1` (**the stale bit**).
7. First three `if`/`else if` arms all fail; **`else if (tapped)` at 13749 is
   taken**; no `continue`; falls through to 13766–13775 → `InKey(&rk)`.
8. `InKey`'s guard at 13515 passes (`g_consoleOpen` is 1 now). No picker. Not
   Tab. Reaches 13653 `ToUnicode` → 13654–13659 appends the character to `g_in`.

Trace closed. The gate is not absent and not wrong — it is *sound for the frame
it runs in* and simply cannot see that the "tap" it is honouring happened
minutes ago while the panel was shut.

**Why the comment at 13750–13761 does not cover this.** That comment justifies
the `tapped` branch as recovering a press+release that fitted inside one 8 ms
window. That reasoning holds only if the previous poll actually *happened*. On
the first pass after an open, the "previous poll" was however long ago the
console was closed, so the window is not 8 ms — it is the whole closed period.

**Which keys leak.** `0x08..0xFE`, minus the skip list at 13722–13728
(`F5`–`F12`, `PAUSE`, `END`, `SHIFT`/`CONTROL`/`MENU` and their L/R variants,
`CAPITAL`). Notably **not** skipped and therefore live:

* `W/A/S/D`, `Space` (jump), `E`, `Q`, `R`, `F`, `C`, `1`–`9` — the gibberish.
* `VK_RETURN` (0x0D) → `InKey` case 13570 → **`InSubmit()`**. A stale Enter tap
  submits whatever garbage is sitting in the line *the moment you open the
  console*. This is the "Unknown command: wfpaim look" class of report.
* `VK_ESCAPE` (0x1B) → 13571 clears the line. Escape is the game's menu key, so
  a user who pressed Escape while closed sometimes gets a clean line — this is
  why the symptom is intermittent rather than every single open.
* `VK_UP`/`VK_DOWN` (0x26/0x28) → 13595/13604, silently replaces the line with a
  history entry.
* `VK_TAB` (0x09) → 13566 `TabComplete`, rewrites the line to a command name.
* `VK_PRIOR`/`VK_NEXT` → 13589/13590, jumps the scrollback on open.

**Why it is masked in some sessions.** Two other call sites read WASD with
`GetAsyncKeyState` from the main thread and therefore *drain* the low bits:
`FlyKeys` (1072–1078, only while noclip is on) and `DriveKeysToVel` (4118–4121,
only while driving — and note it returns at 4109 before those reads when
`g_consoleOpen`). So with noclip or `drive` active the leak largely disappears,
and it is at its worst during plain on-foot walking — which is precisely the
scenario the user described ("I was playing around with the console command
turned off").

### 4.2 SECONDARY (aggravator) — `g_in` is never cleared on close

The close path at 16142–16148, the panic path at 16149–16161, and `Rescue` at
15770–15775 all clear the flags but **none of them touches `g_in` / `g_inLen` /
`g_inCol`**. The only "clear on closed" code is the one inside `InKey` at
13516 — which §3 proves is unreachable.

Effect: the ~4–10 characters harvested by defect 4.1 on each open are *added to
whatever was already there*. Ten open/close cycles produce a long garbage line.
This is the difference between "one stray letter" (annoying) and the screenshot
the user sent (a line of gibberish). On its own it is not the cause; it is the
amplifier that made the cause look like a continuous live leak.

### 4.3 Rank

| # | Defect | Produces the reported symptom? |
|---|--------|-------------------------------|
| 1 | Stale low-bit harvest on the open edge (13749 + 13777) | **Yes — this exact symptom.** Fix this one. |
| 2 | `g_in` never cleared on close (16142–16148 etc.) | Amplifies #1 from "a stray letter" to "a line of gibberish". Fix as well. |
| 3 | Shift+F9 also toggles the panel (§6) | No. Separate, cosmetic. |
| 4 | Stale comments (128, 126, 16147 log text) | No. Cost me time; worth correcting. |

---

## 5. Proposed patch (minimal, and why it fixes *this* symptom)

Two hunks, both inside `InputThread`. **Not applied — for the caller to apply.**

### Hunk 1 — drain the stale bits on the closed→open edge

`avatar_console.c`, around 13681 and 13717–13779.

Before:

```c
    int pickerWasOpen = 0;
    while (!g_shutdown) {
        HWND fg   = GetForegroundWindow();
        int  mine = (fg && (fg == g_gameWnd || fg == g_focusWnd));
```

After:

```c
    int pickerWasOpen = 0;
    int wasActive     = 0;          /* were we polling on the previous tick? */
    while (!g_shutdown) {
        HWND fg   = GetForegroundWindow();
        int  mine = (fg && (fg == g_gameWnd || fg == g_focusWnd));
```

Before:

```c
        if (g_ownInput && g_consoleOpen && g_gameWnd && mine) {
            DWORD now = GetTickCount();
            int vk;
            for (vk = 0x08; vk <= 0xFE; ++vk) {
```

After:

```c
        int active = (g_ownInput && g_consoleOpen && g_gameWnd && mine);

        /* THE LEAK INTO THE INPUT LINE LIVES HERE.
           GetAsyncKeyState's low bit is "pressed since the PREVIOUS CALL for
           this key" and is cleared only by a read. While the console is closed
           this loop does not run, so nothing reads it - and every W/A/S/D of
           normal play leaves its bit set, pending, for the whole closed period.
           The `else if (tapped)` branch below then honours all of them in one
           burst on the first pass after F9, and they land in g_in in ascending
           VK order (a, d, s, w...). That is the "gibberish that was already
           there when I opened the console".

           The branch's own justification - "a press and release fitted inside
           one 8ms poll window" - only holds if the previous poll actually
           happened. On the open edge it did not. So discard the backlog once,
           here, and let the branch mean what it says from the next tick on. */
        if (active && !wasActive) {
            int vk;
            for (vk = 0x08; vk <= 0xFE; ++vk) (void)GetAsyncKeyState(vk);
            memset(down,    0, sizeof(down));
            memset(downAt,  0, sizeof(downAt));
            memset(lastRep, 0, sizeof(lastRep));
        }
        wasActive = active;

        if (active) {
            DWORD now = GetTickCount();
            int vk;
            for (vk = 0x08; vk <= 0xFE; ++vk) {
```

(The trailing `} else { memset(down, 0, sizeof(down)); }` at 13777–13779 stays as
it is — it is still correct, just no longer sufficient on its own.)

### Hunk 2 — clear the line when the panel closes

`avatar_console.c`, hotkey thread, 16142–16148.

Before:

```c
        if (kClose) {
            InterlockedExchange(&g_ourPanel, 0);
            InterlockedExchange(&g_consoleOpen, 0);
            InterlockedExchange(&g_wantFree, 1);
            SetGameInput(1);
            logf_("[keys] F10 CLOSE console");
        }
```

After:

```c
        if (kClose) {
            InterlockedExchange(&g_ourPanel, 0);
            InterlockedExchange(&g_consoleOpen, 0);
            InterlockedExchange(&g_wantFree, 1);
            /* The clear inside InKey's !g_consoleOpen guard is unreachable -
               InKey's only caller is already behind g_consoleOpen - so closing
               used to leave whatever was in the line to accumulate. */
            InterlockedExchange(&g_wantClearIn, 1);
            SetGameInput(1);
            logf_("[keys] F9 CLOSE console");   /* it is F9, not F10 */
        }
```

with, next to the other flags near line 128:

```c
static volatile long g_wantClearIn = 0;   /* close asks; InputThread performs */
```

and drained in `InputThread`, next to the existing `g_pendingSubmit` drain at
13781:

```c
        if (InterlockedExchange(&g_wantClearIn, 0)) {
            g_in[0] = 0; g_inLen = 0; g_inCol = 0;
            g_histPos = -1; g_tabIdx = -1;
        }
```

**Do not** write `g_in` directly from the hotkey thread — `InputThread` is the
only writer today, and keeping it that way preserves the existing single-producer
invariant that lets the buffer go unlocked.

### Why hunk 1 fixes the reported symptom specifically

The symptom is "characters I typed while the console was closed are in the buffer
when I open it". Those characters are produced by exactly one statement — the
`InKey(&rk)` at 13774 — reached by exactly one branch — `else if (tapped)` at
13749 — on exactly one tick — the first tick after `g_consoleOpen` goes 0→1. The
drain loop consumes every pending low bit immediately before that tick's poll can
observe it, so on that first pass `tapped` is 0 for every key that was pressed
while closed, all four arms fall through to `continue`, and `InKey` is not called
for any of them. From the second tick onward `tapped` again means what its
comment claims (a genuine sub‑8 ms tap), so the dropped-keystroke fix it was
written for is preserved intact. Keys physically held down across the open edge
are caught by the `isDown && !down[vk]` arm on the next pass as a fresh press —
which is the same behaviour the picker transition already relies on at 13703.

Note the drain deliberately walks the *same* `0x08..0xFE` range and is a *one
shot on an edge*, not a per-tick drain while closed. A per-tick drain while
closed would look tidier and would be wrong: it would eat the low bits that
`DriveCamKeys` reads with `& 1` at 4333–4350 (`-`, `=`, `[`, `]`) and that
`DriveTick` reads at 5365/5399, all of which are gated on `!g_consoleOpen` and so
are live in exactly the period a drain would be running. Those keys would stop
responding. The edge-triggered version cannot do that.

---

## 6. Other genuine defects found (not the cause; reported for completeness)

1. **Shift+F9 toggles the panel as well as block-input.** `kTgl` is sampled once
   at 15993; `kOpen`/`kClose` are derived from it at 16001–16002 and are evaluated
   at 16136/16142 *regardless* of whether the Shift+F9 branch at 16012 already
   consumed the press. So Shift+F9 flips `g_blockGame` **and** opens/closes the
   console. Fix: `if (kTgl && GetAsyncKeyState(VK_SHIFT) < 0) { …; kOpen = kClose = 0; }`.
2. **Stale comments that actively mislead.** Line 128 `/* cached by the overlay
   thread */` (no longer true — the overlay thread never writes it); line 126
   `/* our input line vs the engine's (F8) */` (`g_ownInput` is never written
   after initialisation and F8 is noclip); the `[keys] F10 CLOSE console` log text
   at 16147 for what is a **F9** close, which made the log harder to read than it
   needed to be.
3. **Dead declarations.** `g_kbHook`, `g_kbThread`, `g_kbTid`, `g_kq`, `g_kqHead`,
   `g_kqTail`, `g_hookCalls`, `g_lastHookCalls` (13190–13206) are never used.
   They are what makes the file look like it has a low-level keyboard hook, and
   they cost real time in this investigation.
4. **The F8 edge-vs-level class check requested in the brief.** I checked every
   `& 1` reader. The single-`GetAsyncKeyState` pattern is correctly applied at
   16089 (F8) and at 13734 (the input poll). The remaining `& 1` readers —
   16039/16040, 16056/16057 (`PgUp`/`PgDn`), 4333/4334, 4349/4350 (`-`/`=`/`[`/`]`),
   16019 (F7), 16024 (F6), 15993–16007 (F9/F10/F1/F11/F12/End/Pause) — each read
   their key exactly once per pass, and no two of them read the *same* key. The
   one cross-thread contention that does exist is benign and is already
   documented at 13785–13791: `FlyKeys`/`DriveKeysToVel` on the main thread read
   `W/A/S/D` and so can consume a low bit before the input poll sees it, which is
   why the poll interval was dropped to 8 ms. **No second instance of the F8 bug
   class was found.**

---

## 7. What I could not determine statically, and how to settle it

I consider the trace closed, but three things are inference from Win32 semantics
rather than from this source, and one cheap log line settles all of them.

1. **That the low bit really does survive an arbitrarily long unread period.**
   MSDN specifies the bit as "set if the key was pressed after the previous call
   to `GetAsyncKeyState`" with no expiry, and nothing else in this process reads
   those VKs while the console is closed. But the bit's exact scope (per-thread
   vs per-queue) is famously under-documented, and if it were reset by something
   else — a focus change, DirectInput acquisition — the burst would be smaller
   than predicted rather than absent.
2. **Whether the game's DirectInput path clears it.** Believed not to; not
   verifiable from this source.
3. **The exact composition of the burst** (how many keys, in what order).

**The one diagnostic that settles all three.** Add this inside the new
edge-triggered drain of Hunk 1, *before* the fix takes effect, and read the log
after one walk-around-then-F9:

```c
        if (active && !wasActive) {
            int vk, n = 0;
            char st[256]; int m = 0;
            for (vk = 0x08; vk <= 0xFE; ++vk) {
                int a = GetAsyncKeyState(vk);
                if (a & 1) { ++n; if (m < 240) m += _snprintf(st + m, 240 - m, "%02X ", vk); }
            }
            st[m] = 0;
            logf_("[in  ] open-edge: drained %d stale taps: %s", n, st);
            memset(down, 0, sizeof(down));
            memset(downAt, 0, sizeof(downAt));
            memset(lastRep, 0, sizeof(lastRep));
        }
```

Predictions, stated in advance so the log can falsify them:

* `n` is **> 0** on every open that follows a period of movement, and **0** on an
  open that immediately follows a close (nothing was pressed in between).
* The VK list contains `41 44 53 57` (`A D S W`) after walking, and `20` if the
  player jumped.
* `n` is roughly the number of *distinct* keys touched while closed, **not** the
  number of keypresses — one bit per key, not a counter. If the log shows `n`
  scaling with the number of presses rather than the number of distinct keys,
  my model is wrong and the finding should be downgraded.
* `n` drops to near 0 for `41/44/53/57` specifically when the same test is run
  with `drive` or noclip active, because `DriveKeysToVel`/`FlyKeys` drain those
  four from the main thread.

A second, zero-risk confirmation that needs no rebuild: open the console, press
F9 to close, walk with WASD **without pressing anything else**, press F9. The
line should contain `adsw` (in that order, at most one of each), not a long run.
If it contains a long run of repeated letters, there is a second live leak and
this finding is incomplete.

---

## 8. Files referenced

* `C:\Test\Avatar 2009 Documentation\DevAccess\console_dll\avatar_console.c` — subject
* `C:\Test\Avatar 2009 Documentation\DevAccess\console_dll\avatar_console_dll.log` — runtime corroboration (F9 open/close pairs are balanced throughout, which is what ruled out the flag-desync hypothesis)
* `C:\Test\Avatar 2009 Documentation\DevAccess\console_dll\build.bat` — built `/TP` (C++), so the mixed declarations in the patch above compile as-is
