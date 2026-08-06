# What we changed in `avatar_console.c` -- and how to merge with it

**Written 2026-08-05. Baseline: commit `6d677c9f`, `avatar_console.c` at 20,256
lines.**

This file exists for one reason: **two people are editing `avatar_console.c` at
the same time.** It is a 20,000-line single translation unit, so a careless
merge is expensive. This document says exactly which regions we touched, which
we did not, and where the two genuinely overlapping edits are.

Read the "Merge cheat-sheet" first. Everything after it is detail.

> ## THIS FILE IS MANDATORY TO UPDATE
>
> **AGENTS.md Rule 10.** Any change to `avatar_console.c` updates this file **in
> the same task, before committing.** A change is not complete without it.
>
> This is not a courtesy changelog. It is the only record of who touched what,
> so it is the thing that makes a merge possible at all -- and a stale entry
> here is *worse* than a missing one, because it is trusted.
>
> Every entry carries four things:
>
> 1. **Where** -- function or section name, **and** the line range at that
>    commit. Line numbers go stale by design, so always name the anchor comment
>    or symbol as well; that survives the other author's edits shifting
>    everything.
> 2. **Added / modified / rewrote** -- an insertion between two untouched
>    functions is a non-event to merge; a rewrite of existing lines is what
>    actually collides.
> 3. **Collision risk, honestly** -- None / Low / Medium, *and why*. Do not mark
>    everything Medium to be safe; that destroys the signal this table exists to
>    carry.
> 4. **New `static` symbols**, listed -- so the other author can check for name
>    clashes without reading the diff.
>
> And when a change reaches them, update these too:
>
> - **A command or link verb added/removed/renamed** -> the counts in
>   `DevAccess/CONSOLE_AUDIT.md` (sections 1.1 and 1.2) and the entry in
>   `DevAccess/COMMANDS.md`. They have drifted once already (68->76 commands,
>   8->11 verbs) and needed a dated freshness banner to stay usable.
> - **`hello` / pipe / protocol shape** -> say whether `LNK_PROTO` was bumped.
> - **Multi-instance or profile behaviour** -> `MULTI_INSTANCE.md` as well.
>
> `check_cmds.py` fails the build when the dispatch chain and `kOurCmds[]`
> disagree, so *code* drift is caught automatically. **Nothing catches doc
> drift.** That is what this rule is for.

---

## Merge cheat-sheet

### 2026-08-05 (b) — `players` command, MP admin work

| Where | What | Risk | New symbols |
|---|---|---|---|
| `PlayersList()`, anchor `/* ---- players: enumerate the WHOLE player list` — 8985-9105 | **Added**, between `RayAabb`'s end and the `PickSelect` forward decls | **None** — new text between untouched neighbours | `PL_SANE_MAX`, `PlayersList()` |
| `kOurCmds[]` last entry, ~16800 | **Modified** — `"mkpawn",` became `"mkpawn", "players",` | **Medium** — one-line table both authors append to | — |
| Dispatch, after the `playerinfo` arm, ~14199 | **Added** 6 lines | Low | — |
| `ModHelp`, ~1714 | **Added** 1 line | Low | — |

`kOurCmds[]` is the one to watch: it is a single flat table and `check_cmds.py`
**fails the build** if it disagrees with the dispatch chain. That is a feature —
a bad merge here is caught at build time rather than shipping a command that
tab-completes but does nothing. If the build fails on `check_cmds`, the fix is
to make sure every dispatched command appears in the table exactly once.

Counts after this change: **76 dispatched, 76 in `kOurCmds[]`** (as
`check_cmds.py` counts — it discards `?` and adds `warp`).

### 2026-08-05 (a) — multi-instance

| Where | What we did | Collision risk |
|---|---|---|
| Lines 10066-10592, one contiguous block | **Added** two new self-contained sections | **None** -- it is new text between two untouched functions |
| `DllMain`, ~line 20244 | **Added** 2 lines | Low -- but it is `DllMain`, so read it |
| Worker unload paths, 3 sites | **Added** 2 lines each | **Medium** -- see below |
| `hello` reply, ~line 11894 | **Added** 2 JSON fields | Low, but it is a *protocol* change |
| `LinkThread` pipe naming, ~line 12926-12948 | **Rewrote** ~20 lines | **Medium** |
| `SweepIatHooks` / `VerifyUnhooked` | **Added** one block each | Low |
| `build.bat` | Toolchain discovery | **None** (separate file) |

**Nothing else in the file was touched.** No console command, no hotkey, no
picker code, no D3D overlay, no per-frame detour logic. If your buddy has been
working on the entity picker, the spawn commands, or the overlay, the two sets
of changes do not intersect at all.

**The single most likely conflict** is the three unload paths, because they are
three near-identical five-line blocks and a diff tool will happily apply the
same hunk to the wrong one. See "The three unload paths" below -- all three
need the change, so the fix is always "make sure all three have it", never
"pick one".

---

## 1. The two new sections (lines 10066-10592)

One contiguous block, inserted between `RemoveDebugStringHook()` (which ends at
10064) and the `pawntype` section (which now starts at 10596). Both original
neighbours are unmodified.

### 1a. `MULTI-INSTANCE` (10066-10210)

Lets a second copy of the game launch. Full explanation in
**[`MULTI_INSTANCE.md`](MULTI_INSTANCE.md)** -- do not duplicate it here.

New symbols, all `static`, none of which existed before:

```
IAT_OPENMUTEXA_VA  MULTI_MARKER  MULTI_MUTEX_NAME
fnOpenMutexA  g_omOrig  g_omOrigEver  g_omSlot
g_multiOn  g_omSwallow  g_omSaid
hkOpenMutexA()  MultiInstanceWanted()
InstallMultiInstanceHook()  RemoveMultiInstanceHook()
```

### 1b. `PER-INSTANCE GAMER PROFILE` (10212-10592)

Gives instance 2+ its own `GamerProfile2.xml` so the two copies are different
players. Also in `MULTI_INSTANCE.md`.

New symbols:

```
PROFILE_LEAF_W  PROFILE_LEAF_A  INST_MUTEX_FMT  INST_MAX
IAT_CREATEFILEW_VA  IAT_CREATEFILEA_VA
g_instIndex  g_instMutex  g_profSaid
g_cfwOrig  g_cfwOrigEver  g_cfwSlot
g_cfaOrig  g_cfaOrigEver  g_cfaSlot
ClaimInstanceIndex()  TailIsProfileW()  TailIsProfileA()
SetXmlAttrLong()  StripAccountsW()  SeedProfileW()
hkCreateFileW()  hkCreateFileA()  HookIatSlot()
InstallProfileRedirect()  RemoveProfileRedirect()
```

`HookIatSlot()` (line 10531) is the one worth knowing about: it is a **generic
IAT-slot swapper** extracted while writing the above. If your buddy needs to
hook another imported API, use it rather than writing a fourth copy of the
`GetModuleHandle` / rebase / `VirtualProtect` dance:

```c
if (HookIatSlot(IAT_SOMETHING_VA, (void*)hkSomething,
                (void**)&g_origSomething, &g_slotSomething))
    g_origSomethingEver = g_origSomething;
```

The pre-existing `OutputDebugStringA` and `Present` hooks were **not**
retrofitted onto it -- they work, and rewriting working hook installation to
save duplication is a bad trade in a file this load-bearing.

---

## 2. `DllMain` -- two added lines (~20244)

```c
        InitializeCriticalSection(&g_cs);
        InterlockedExchange(&g_csAlive, 1);

        InstallMultiInstanceHook();      /* <-- added */
        InstallProfileRedirect();        /* <-- added */

        CreateThread(0, 0, Worker, 0, 0, 0);
```

**Three constraints, all load-bearing. If you move these lines, read this
first:**

1. **They cannot go in `Worker`.** Dunia's single-instance check and its profile
   read both happen during Dunia's own init, long before `g_console` exists.
   `Worker` waits for `g_console`. It is far too late.
2. **They must come after `InitializeCriticalSection(&g_cs)`**, because the
   logging they can reach uses it.
3. **`InstallProfileRedirect` must come after `InstallMultiInstanceHook`.**
   `ClaimInstanceIndex()` calls `CreateMutexA` itself; installing the mutex hook
   first means our own probes are already distinguishable from Dunia's.

Neither call does real work under the loader lock -- one writes a dword and
logs nothing, the other writes two dwords. The reporting is deferred to
`Worker`, which is a normal thread. **Do not add logging to these two
functions.**

---

## 3. The three unload paths -- THE LIKELY CONFLICT

Both new `Remove*` calls have to appear at **all three** places the DLL can
unload. As of this writing:

| Line | Path |
|---|---|
| ~15788 | the normal shutdown |
| ~19644 | early bail: `g_console` never appeared |
| ~19661 | early bail: `InstallHook()` failed |

Each reads:

```c
        RemoveDebugStringHook();
        RemoveMultiInstanceHook();
        RemoveProfileRedirect();
        RemoveCrashReporter();
```

**Why all three and not just the normal one:** both hooks are installed from
`DllMain`, so they are armed *before* either early-bail path can be reached.
An early unload that skipped them would leave two IAT slots in Dunia pointing
into a DLL that is about to be unmapped -- the next `OpenMutexA` or
`CreateFileW` anywhere in the process jumps into freed address space. That is
not a leak, it is a crash with a garbage call stack.

> If you merge and only one or two sites have the calls, **that is the bug.**
> Add them to the others. There is no case where a site should be missing.

The two early-bail insertions were originally mis-indented (4 spaces inside an
8-space block); that was corrected on 2026-08-05 and is the only difference
between this and what is in commit `6d677c9f`.

---

## 4. Editor-link changes

### 4a. `hello` gained two fields (~11894)

```
"pipe":"\\\\.\\pipe\\avatar_editor",   /* which pipe THIS process is serving */
"multi":1                              /* is the multi-instance hook armed */
```

`LNK_PROTO` is **still 1**, deliberately. Adding fields to a JSON object is
backward compatible -- an old client ignores keys it does not know. Bump
`LNK_PROTO` only when you remove or repurpose a field.

If your buddy also added `hello` fields, this merges cleanly as long as both
sides keep the format string and the argument list in the same order. That
pairing is the classic way to break it: `LnkPut` is `printf`-shaped, so a
mismatched arg list is a garbage read, not a compile error. **Count the `%`
conversions against the arguments after merging.**

### 4b. The pipe is no longer always `avatar_editor` (~12926-12948)

The pipe is created with `nMaxInstances = 1`. Before, a second game's
`CreateNamedPipeA` failed with `ERROR_ACCESS_DENIED`, and the retry loop slept
2 seconds and tried the identical name again, forever.

Now: on `ERROR_ACCESS_DENIED`, and once only, it renames itself to
`avatar_editor_<pid>` and retries **immediately** -- no sleep, because that
error is a certainty, not a transient. Instance 1 keeps the canonical name, so
any existing tool that connects to `avatar_editor` still works unchanged.

New state: `g_lnkPipe[64]` (the name actually in use) and `g_lnkPidNamed` (the
once-only latch). Every log line that used to hardcode the name now prints
`g_lnkPipe`.

**A client that wants a specific instance** reads `pid` from `hello`, or
connects to `avatar_editor_<pid>` directly.

---

## 5. Unload safety additions

- **`SweepIatHooks`** (~19377) gained a block for the `OpenMutexA` slot, in the
  same shape as the existing `OutputDebugStringA` one: if the slot still points
  into us at unload, restore it from `g_omOrigEver` and log it.
- **`VerifyUnhooked`** (~19553) gained an *arming* report: it reads the slot
  back and prints whether it holds our hook, re-arms if not, and states the
  instance number. It also prints the "requested but NOT armed" case, which is
  what you see if the DLL was injected after startup instead of proxy-loaded.

**Why `g_omOrigEver` exists alongside `g_omOrig`:** the sweep runs *after*
`RemoveMultiInstanceHook` has zeroed `g_omOrig`, so a repair conditioned on
`g_omOrig` could never fire. Same defect and same fix as the pre-existing
`g_rdPresentEver` and `g_odsOrigEver`. If you add a fourth IAT hook, it needs
the `Ever` twin too.

---

## 6. `build.bat` -- unrelated to the DLL's behaviour, but it bit us

The `vswhere` query was missing **`-prerelease`**, and without it vswhere does
not report Insiders/Preview installs *at all*. On a machine whose only VS is
"Visual Studio 18 Insiders", the query returns nothing, every hardcoded
fallback path misses, and the script says the toolchain is absent while the
compiler is sitting right there.

Measured: without `-prerelease`, the query printed nothing. With it,
`C:\Program Files\Microsoft Visual Studio\18\Insiders`.

The fallback loop was also widened to `for %%y in (2022 2019 18 19)` and the
edition list gained `Insiders` and `Preview`. Retail installs are still
preferred -- vswhere sorts them ahead of prerelease.

Also: run it by **absolute path**. `.` is not on `PATH` on this machine, so a
bare `build.bat` reports "not recognized". `tools/go.bat` already documents
this trap.

---

## 7. Docs we edited (not code)

- **`DevAccess/CONSOLE_AUDIT.md`** -- added a dated freshness banner. Three
  counts had drifted and one warning had become false:
  - "68 top-level console commands" -> **76 dispatch arms** (75 completable)
  - "8 editor-link verbs" -> **11** (`bones`, `addr`, `cvar` were added after
    the audit was written)
  - "16,263 lines" -> was 19,615, now 20,256
  - The "STALE DLL" warning was **wrong** and is marked so; section 9.3 is
    marked historical.
- **`DevAccess/CONSOLE_INPUT_BUG.md`** -- marked FIXED at the top.

The audit itself was written **without running the game**. Every claim in it is
from reading. That is stated in its own header and it is worth keeping in mind:
we have now falsified several of its inferences by actually launching.

---

## 8. What we deliberately did NOT do

So nobody re-does it, and so nobody assumes it is half-finished:

- **No game file is modified.** Not `Dunia.dll`, not `Avatar.exe`, not any
  archive. Everything is copy-on-write memory in our own process. Patching the
  `jnz` at `0x10005586` also works and is six bytes, but it edits `Dunia.dll` on
  disk -- which this project has a standing rule against, and which would apply
  to *every* launch including the ones where the check is wanted.
- **The RTE tool** (`tools/rte_tool/`) is **parked, not dead.** It works and is
  committed; the user chose to focus elsewhere. Do not delete it, and do not
  keep building on it without asking.
- **The picker bug-fixes were never started.** Three known bugs are still open
  in the entity picker: a race where DELETE can hit the wrong entity, an
  unlocked snapshot, and an every-frame `CreateTexture` retry. They were scoped
  and then superseded. They are still real.
- **`LnkPut`'s dropped end-sentinel** is still there:
  `if (len >= LNK_OUT_MAX - 600) return;` drops the terminator on replies near
  1 MB, so a client waiting for the sentinel hangs. Only reachable with very
  large `list` results.

---

## 9. Rebuilding

```
"C:\...\tools\console_dll\console_dll\build.bat"
```

produces `dist/avatar_console.dll`, and `install.bat` copies it to the game's
`bin\` as **`dinput8.dll`** (proxy load). The two files in `dist/` are
byte-identical by design -- the DLL checks its own filename at runtime and
switches into proxy mode when it is called `dinput8.dll`.

**Never load it both ways at once.** The `dinput8.dll` drop-in and `inject.py`
must not both be used on the same launch; you get two copies of every hook and
the unload paths fight each other.

`dist/*.dll` and `dist/*.map` are **gitignored** -- they are 4.5 MB, rebuilt
constantly, and binaries in git never shrink again. `inject.py` and
`install.bat` *are* tracked, deliberately: an unknown `.exe` that injects into a
game process reads as malware at a glance, so the injector ships as readable
Python.
