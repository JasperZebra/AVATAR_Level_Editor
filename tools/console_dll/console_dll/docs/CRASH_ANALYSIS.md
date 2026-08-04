# Access-violation triage — `avatar_console_dll.log` + `Crash 1.txt` / `Crash 2.txt`

18 `ACCESS_VIOLATION` records across the logs. They are **not 18 bugs** — they
group into 5 distinct faulting sites, only 2 of which are ours.

| faulting address | n | module | ours? | status |
|---|---|---|---|---|
| `1000EE10` | 2 | engine `CriticalSection_Enter` | **yes** | fixed in `b3dd212`, logs predate it |
| `6122C4DC` | 1 | `avatar_console.dll+0x1C4DC` | **yes** | **fixed here** |
| `MSVCR80+0x1500A/0x15068/0x1509C` | 7 | CRT | no | see "not ours" |
| `101B1923`, `1031AE00`, `101B43C8`, `1038BB19`, `106D8695`, `1095169E` | 8 | engine | no | see "not ours" |

---

## 1. `1000EE10` — already fixed, logs are stale

`Crash 1.txt` and `Crash 2.txt` are the same fault twice: `ESI=0`, `ECX=0x88`,
reading `0x00000088`, `freecam=1 drive=1`.

`CConsole::Printf` (`100AC0C0`) with a **NULL `this`**. Printf's first act is
`AppendLines`, whose first act is to take the console's own lock:

```
CConsole::AppendLines+0x58
  100ab6b8  lea  ecx, [esi + 0x88]     ; &this->m_pLock — LEA, no deref yet
  100ab6be  call 0x1000ee10
CriticalSection_Enter
  1000ee10  mov  eax, dword ptr [ecx]  ; <-- faults, ecx = 0 + 0x88
```

`Printf` never null-checks `arg0` on any path, so a NULL sink always lands here.
Full derivation in `ENGINE_MAP/CRASH_1000EE10.md`.

**Already fixed.** Commit `b3dd212` (Jul 29 **13:04**) gated the prints in
`DriveTurnSet` and `FaceHookSet`. Both crash logs are timestamped Jul 29
**05:08 / 05:12** — *before* the fix. Nothing to do.

I re-audited it rather than trusting the commit message: took the 5 entry points
that pass a literal NULL console (`DriveStop`, `DriveTurnSet`, `FaceHookSet`,
`FreecamLeave`, `VehExit`), computed the transitive closure over all 65
console-taking functions, and checked every `Printf` in it. **0 unguarded.**
The class is closed.

---

## 2. `6122C4DC` = `avatar_console.dll+0x1C4DC` — the live bug, fixed

The only crash in **our own code**. Triggered by `ents` (log line 11287):

```
reading address 18BC0A4C
ESI=18BC0A40  EDI=00000027
```

`0x18BC0A4C - 0x18BC0A40 = 0xC` = `OFF_TN_CLASSID`. That is exactly:

```c
unsigned long classId = *(unsigned long*)((char*)node + OFF_TN_CLASSID);
```

in `EntList`. `EDI=0x27` = 39 = `shown`, one below the 40-row cap — i.e. it died
deep into a walk that was printing rows, which is the tell.

### Why the existing guards did not catch it

The node came off `stack[--sp]`, so it **did** pass `QuickPtr && Readable` — at
**push** time. It stopped being valid between the push and the pop.

Not a thread race: commands run on the main thread inside the frame hook
(`QueuePop` → `TryModCommand`). It is the walk's own doing — `P_()` in the row
loop is `CConsole::Printf`, which allocates a ring entry and frees the line it
evicts (`Mem_Free` is in the crash's stack candidates). Running the engine's
allocator in the middle of a red-black walk lets the heap move under nodes we are
still holding, and `ents` carries up to 63 stale node pointers on its stack.

`Readable()` cannot fix this. As `RefNodeEntity`'s own comment in this file
already says: *"Readable() proves a page is COMMITTED, not that the object is
alive."* Re-checking after the pop only narrows the window.

### The fix

SEH around every load off a popped node — which is what the two sibling walkers
already did, and what `EntList` alone never did:

```
EntList        __try 0 -> 3
EntSnapshotEx  __try 1 -> 4
EntForEach     __try 0 -> 2
```

Three loads were unprotected in each walker, and the same defect existed in all
three:

1. `node + OFF_TN_CLASSID / INNERCOUNT / INNERHEAD` after the pop
2. `in + OFF_IN_NEXT` in the row loop
3. `node + OFF_TN_RIGHT` — loaded **raw** and only null-checked by the outer
   `while (node || sp)`, so a torn node fed garbage straight into the descent

`EntForEach` has the same hazard for a third reason: it calls a caller-supplied
`fn` mid-walk.

A fault now ends the walk (`break`) with partial results instead of taking the
game down. Builds clean at `/W3`, x86, `check_cmds` passes.

---

## 3. Not ours — no action

**`MSVCR80.dll+0x1500A/0x15068/0x1509C` (7 of 18).** Three different load
addresses for the same CRT offsets = the same routine across sessions where the
DLL rebased. These sit at frame counts 555k–2.17M, i.e. hours in, and are not
correlated with any console command in the surrounding log lines.

**The six engine addresses (8 of 18).** Each has engine-only stack candidates and
a plausible engine-side cause visible in the log:

- `1095169E` — during `[warp] waiting for the pawn`, right after
  `[cam] entry 0 is dead ... poisoning`. Faults reading `0x00000000` with
  `EAX=0, ESI=0`. Mid-worldload teardown.
- `106D8695` — 7s after `GameChangeWorldDefaultSpawnPoint("coop_pascal_01")`,
  reading `0x18C`. Inside the world-change path.
- `101B43C8` — reading `0x0` with `EAX=EBX=ECX=0`, after an archetype snapshot.

These are worth their own pass if they reproduce, but nothing in them points at
our code, and I did not want to invent fixes for faults I cannot attribute.

---

## Method note

The crash logger prints "stack candidates" — every stack slot that *looks* like a
code address. It is a heuristic, not a walk: `111DF27C` in `Crash 1.txt` is
`.data`, not code. Treat candidates as leads to confirm, not as frames.
