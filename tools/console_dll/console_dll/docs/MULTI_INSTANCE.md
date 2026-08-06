# Running two copies of Avatar at once

**Written 2026-08-05. Confirmed working in game: two instances, in the same
multiplayer match, as two different players.**

Solo multiplayer testing. Launch the game twice, host on one, join on the other.

**No game file is modified.** Not `Dunia.dll`, not `Avatar.exe`, not any
archive. Everything below happens in copy-on-write memory inside the game's own
process. Delete one text file and the game is stock again.

---

## Quick start

1. `dinput8.dll` must be in the game's `bin\` folder (that is our DLL under a
   proxy name -- `install.bat` puts it there).
2. Create an empty file next to it: `bin\avatar_multi.txt`.
3. Launch the game twice.
4. In the second copy, go to the account screen and **create a second account**.
   It starts with none, on purpose.

To turn it off: **delete `avatar_multi.txt`.** Nothing else needs undoing.

`AVATAR_MULTI_INSTANCE=1` in the environment does the same thing, for scripted
launches.

It is opt-in and never on by default. Silently changing whether a game enforces
single-instance is exactly the kind of surprise that gets blamed on something
else three weeks later.

---

## There are three separate gates, not one

This is the part worth internalising. "Run two copies" turned out to be three
independent problems, each with its own error message, discovered one at a time
by hitting them:

| # | Gate | What you see | Fix |
|---|---|---|---|
| 1 | A named mutex | *"You already have a ... instance active"* | Answer one `OpenMutexA` probe with NOT FOUND |
| 2 | One shared profile file | *"another person signed in using your account"* | Give instance 2 its own `GamerProfile2.xml` |
| 3 | Both instances on port 9000 | Lobby crawls, gameplay is fine | Move instance N to its own port block |

Gate 1 lets two copies *run*. Gate 2 lets them *play together*. Gate 3 is why
it felt broken even after it worked.

---

## Gate 1: the single-instance mutex

### Finding it

The error string is `ERROR_INSTANCE_MUTEX` -- an Oasis localised string id, not
a literal. Dunia references string *ids*, so a plain strings search for the
English sentence finds nothing in the binary. It resolves through
`Data_Win32\patch0\languages\english\oasisstrings.rml`.

The gate itself, traced in `Dunia.dll` (preferred base `0x10000000`, and the
module loads there, so static VA == runtime VA):

```asm
1000554C  push 0x11010C14        ; "AvatarInstance" - a hardcoded literal
10005564  call 0x10003590        ; std::string::assign into a local
10005577  push eax               ; lpName
10005578  push ebx               ; bInheritHandle = FALSE
10005579  push 0x001F0001        ; MUTEX_ALL_ACCESS
1000557E  call [OpenMutexA]      ; <-- THE PROBE
10005584  cmp  eax, ebx
10005586  jnz  0x10006A01        ; <-- exists => bail
1000559D  call [CreateMutexA]    ; first instance claims it
```

and the branch target proves itself:

```asm
10006A0F  push 0x11010AE0        ; "ERROR_INSTANCE_MUTEX"
```

**The whole gate is one `OpenMutexA` result test.** Return NULL for that one
name and the second instance walks straight on: `CreateMutexA` then hands back
a handle to the *existing* mutex with `ERROR_ALREADY_EXISTS`, and nothing reads
that.

> ### The decompile lied, and this is the second time
>
> The Ghidra decompile shows **two** `CreateMutexA` call sites, both with NULL
> names. On that basis I told the user there was no single-instance lock in
> Dunia at all. They pasted the actual error message.
>
> The shipped binary has **five**. Scanning for the raw call encoding
> (`FF 15 70 00 00 11`) found them in seconds.
>
> **Ground claims in the shipped bytes, not the decompile.** The decompile is a
> good map and an unreliable census. This exact failure mode has now cost time
> twice on this project.

The mutex name carries **no `Global\` prefix**, so it lives in the caller's
session namespace. A genuinely separate Windows session (fast user switching)
already gets its own copy and needs none of this.

### The fix

One dword written into Dunia's Import Address Table, at `0x11000074` -- the
slot holding `OpenMutexA`. It now points at:

```c
static HANDLE WINAPI hkOpenMutexA(DWORD access, BOOL inherit, LPCSTR name)
{
    if (g_multiOn && name && _stricmp(name, MULTI_MUTEX_NAME) == 0) {
        InterlockedIncrement(&g_omSwallow);
        if (!InterlockedExchange(&g_omSaid, 1))
            logf_("[mult] OpenMutexA(\"%s\") answered NOT FOUND - the "
                  "single-instance gate is open for this process", name);
        SetLastError(ERROR_FILE_NOT_FOUND);
        return 0;
    }
    return g_omOrig ? g_omOrig(access, inherit, name) : 0;
}
```

Every other mutex in the process is passed straight through. Only the exact
name `AvatarInstance` is answered NOT FOUND.

**Why an IAT swap and not a byte patch.** Patching the `jnz` at `0x10005586`
works and is six bytes -- but it edits `Dunia.dll` on disk, which this project
has a standing rule against, and it would apply to every launch including the
ones where the check is wanted. The IAT swap is per-process, opt-in, and
reversible by deleting a text file.

### The timing question -- and why it is not a race

The check runs during Dunia's init, long before a level exists. Our worker
thread waits for `g_console`, so it is far too late. The hook therefore installs
from **`DllMain`**.

That only works if `OpenMutexA`'s thunk is already resolved when our `DllMain`
runs. It is, and this is checkable rather than hopeful: **KERNEL32 is import
descriptor 1 in Dunia's import table; DINPUT8 is descriptor 10.** The loader
walks them in order, so by the time it reaches DINPUT8 -- which is what pulls
*us* in, under the proxy name -- KERNEL32's thunks including this one are
already snapped. Nine descriptors of margin.

The install still refuses to write unless the slot is mapped **and already holds
a real function pointer**, so if that ordering were ever wrong it would decline
rather than write a value the loader is about to overwrite. And
`VerifyUnhooked` reads the slot back at startup and logs `INTACT` or
`*** CLOBBERED ***` with both pointer values -- because that reasoning is about
a loader we do not control.

The log confirms it every launch:

```
[mult] multi-instance ARMED - IAT slot 11000074 holds 6FB368F0, ours is 6FB368F0 : INTACT
[mult] OpenMutexA("AvatarInstance") will answer NOT FOUND, so the single-instance gate cannot close
```

**Injecting after startup does nothing** -- the gate has already run. The log
says so explicitly rather than failing silently. Use the `dinput8.dll` proxy for
multi-instance.

---

## Gate 2: both copies were the same player

Two instances now ran. Joining a match kicked the first one:

```
E_SESSION_ERROR_ACCOUNT_KICKED_BY_DUPLICATE_LOGON
"You have been returned to the main menu because another person signed in
 using your account."
```

Both copies read the same file:

```
Documents\My Games\Avatar\GamerProfile.xml
```

whose identity is one line:

```xml
<Accounts><Account Name="Jasper" Pass="4B91C8A741C4D946" Active="1" /></Accounts>
```

The Oasis id sits next to a block of `E_SESSION_ERROR_RENDEZVOUS_*` strings --
this is Ubisoft's Rendez-Vous session layer, and it is **identity-based**. Same
account, two connections, one gets kicked. There is nothing to bypass here; the
second instance genuinely needs to be a different player.

### Instance numbering

Not a counter in a file -- a file goes stale the moment the game crashes.

Each process walks `AvatarConsoleInst1`, `AvatarConsoleInst2`, ... and claims
the first one it can create without `ERROR_ALREADY_EXISTS`, then **holds that
mutex for its whole lifetime**. The OS reclaims it on exit however the process
died -- crash, kill, power loss. Self-healing by construction.

Instance 1 keeps the stock profile, so **a normal single launch is byte-for-byte
untouched.**

### The redirect

`CreateFileW` and `CreateFileA` are hooked on Dunia's IAT (`0x11000138` and
`0x110000E4`). Any path ending in `GamerProfile.xml` becomes
`GamerProfile<N>.xml` for instance N >= 2.

**Where the seam is:** `"\GamerProfile.xml"` is a literal at `0x110ABEF0`,
concatenated onto a folder path at `0x107334D4` -- but that code only *builds*
the string, it does not open it. Dunia's imports show exactly **one**
`CreateFileW` call site (`0x100F0306`) and five `CreateFileA` sites, i.e. file
opens funnel through a small number of wrappers. Both APIs are hooked.

Whether the profile actually arrives via `CreateFileW`, `CreateFileA`, or the
CRT's `fopen` -- which resolves inside MSVCR80's own import table and **not**
through Dunia's, so these hooks would miss it entirely -- was not settled by
reading. Rather than guess, the hooks log the first few paths containing
"GamerProfile" *whether or not they redirect*. One launch then answers it.

It answered `CreateFileW`:

```
[prof] CreateFileW redirected -> C:\Users\sambe\Documents\My Games\Avatar\GamerProfile2.xml
```

### Seeding -- and the bug the first version shipped with

Instance 2's profile is seeded by copying instance 1's, because the file also
carries video settings and the entire key-binding table; starting blank would
throw all of it away.

**But a plain copy carries the account across verbatim** -- which is precisely
the duplicate that causes the kick. A per-instance profile holding the same
account is no better than sharing one file. The user caught this immediately on
inspecting the seeded file.

`StripAccountsW` removes every `<Account ... />` element from the copy, leaving
`<Accounts></Accounts>`. The game then treats instance 2 as a machine with no
account yet and offers to create one.

The strip is textual, not a real XML parse, deliberately: the edit is "delete
every self-closing `<Account />` element", the file is a few KB of ASCII we
ourselves just copied, and pulling in a parser to delete one element is more
code and more to get wrong. Compaction is in place and safe because the write
index never overtakes the read pointer.

**The password is not reused or transplanted.** It is a stored credential; the
point is a *different* account, and the game writes its own when one is created.

```
[prof] seeded instance 2's profile from the original
[prof] stripped 1 account(s) from the seeded profile - instance 2 starts with
       none, so create a fresh one in the game's account screen
```

---

## Gate 3: the lobby was crawling

Symptom, reported after the above worked: **laggy in the lobby, completely
smooth once in a match.**

**Rendering was ruled out first, and the symptom itself is the evidence.** If
two instances were fighting over the GPU, actual gameplay -- vastly heavier than
a menu -- would be *worse* than the lobby, not better. It was the opposite. So
the cost is something the lobby does and gameplay does not.

Every profile ships with:

```xml
OnlineEnginePort="9000" OnlineServicePort="9001"
ScanFreePorts="1" ScanPortStart="9000" ScanPortRange="1000"
```

Both instances want 9000/9001. The second finds them taken and **scans** -- up
to a thousand ports -- and it does that while the lobby is polling for sessions.
A lobby-only cost that vanishes once a match is running. Matches the symptom
exactly.

Fix: while seeding the profile, rewrite the ports to a per-instance block.

```c
base = 9000 + (g_instIndex - 1) * 100;
out = SetXmlAttrLong(buf, out, cap, "OnlineEnginePort",  base);
out = SetXmlAttrLong(buf, out, cap, "OnlineServicePort", base + 1);
out = SetXmlAttrLong(buf, out, cap, "ScanPortStart",     base);
```

100 apart, so each instance keeps a clean block and the scan range never has to
walk into its neighbour's.

**This was a hypothesis, not a measurement.** It fit the evidence and cost
nothing, but nobody profiled the lobby. The user confirmed *"lag is fixed"*,
which is good enough to keep -- and if it ever returns, the next suspect is the
session layer retrying dead Rendez-Vous endpoints.

One implementation note: `SetXmlAttrLong` can make the file *grow* (a 4-digit
port becoming 5), so the buffer is allocated with `cap = n + 256` of headroom.
A buffer sized exactly to the input would have nowhere to put it.

---

## Gate 3.5: the editor pipe

Not a gate, but it broke for the same reason.

The named pipe `\\.\pipe\avatar_editor` is created with `nMaxInstances = 1`. A
second game's `CreateNamedPipeA` failed with `ERROR_ACCESS_DENIED` and the retry
loop slept two seconds and tried the identical name again -- forever.

Now, on that error and once only, the second instance renames itself to
`avatar_editor_<pid>` and retries immediately (that error is a certainty, not a
transient -- sleeping on it is pure delay). Instance 1 keeps the canonical name,
so existing tools are unaffected.

The `hello` reply reports both, so a client always knows what it reached:

```json
{"ok":true,"cmd":"hello","pid":12345,"pipe":"\\\\.\\pipe\\avatar_editor","multi":1, ...}
```

---

## What is actually modified, in full

| Thing | Modified? |
|---|---|
| `Dunia.dll` on disk | **No** |
| `Avatar.exe` | **No** |
| Any `.pak` / `.fat` / game data | **No** |
| `Dunia.dll`'s IAT in memory (3 slots, per-process, copy-on-write) | Yes |
| `Documents\My Games\Avatar\GamerProfile2.xml` | Created (new file) |
| `GamerProfile.xml` (the original) | **No** |
| `bin\avatar_multi.txt` | You create it; delete to disable |
| `bin\dinput8.dll` | Our DLL, added |

All three IAT slots are restored at every unload path, and a sweep at exit
re-checks them and repairs any that are still ours.

---

## Troubleshooting

Log: `bin\avatar_console_dll.log`.

**"multi-instance was REQUESTED but is NOT armed"** -- the DLL was injected
after startup instead of proxy-loaded. The gate runs during Dunia's init; only
`dinput8.dll` is early enough.

**Second instance still refuses to launch** -- is `avatar_multi.txt` in the same
folder as `dinput8.dll` (the game's `bin\`, not the game root)? Grep the log for
`[mult] multi-instance ARMED`.

**Still kicked for duplicate logon** -- the second instance is still on the
shared account. Look for `[prof] CreateFileW redirected`. If instead you see
`[prof] ... saw the profile (instance N, not redirected)`, the tail match
failed; if you see *nothing* about the profile, the game reached it via `fopen`
and the hook needs to move to MSVCR80's import table.

**Both instances think they are instance 1** -- they cannot both hold
`AvatarConsoleInst1`. Almost certainly one of them did not load the DLL at all.

**Ports** -- instance N is on `9000 + (N-1)*100`. Instance 2 is 9100/9101. Only
written into a *freshly seeded* profile, so if you already have a
`GamerProfile2.xml` from before this change, delete it and let it re-seed.

**Max 8 instances** (`INST_MAX`). Beyond that, extra copies behave like instance
1 -- they run, but they share the profile.

---

## Source map

All in `avatar_console.c`. See
[`CHANGES_MERGE_NOTES.md`](CHANGES_MERGE_NOTES.md) if someone else is editing
the same file.

| Region | Lines (at 20,256) |
|---|---|
| `MULTI-INSTANCE` section | 10066-10210 |
| `PER-INSTANCE GAMER PROFILE` section | 10212-10592 |
| `DllMain` install | ~20244 |
| Unload paths (three of them) | ~15788, ~19644, ~19661 |
| Exit sweep / arm report | ~19377, ~19553 |
| Pipe renaming | ~12926-12948 |
