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

### 2026-08-11 (n) — multiplayer match stats, recorded with no keypress

**What:** a new self-contained section, `MULTIPLAYER MATCH STATS`, that writes
one JSON line per multiplayer match to `matches.jsonl` next to the DLL.
`tools/mp_stats/stats_uploader.py` ships that file to our stats server;
`tools/mp_stats/README.md` is the design and `tools/DevAccess/MP_STATS.md` is
the format research.

**Where — five touch points, four of them one line:**

| Location | Change |
|---|---|
| ~line 157 (fwd decls) | added `MpStatsTick` / `MpStatsCmd`, next to `ProbeEnter` |
| after `DumpRing` | **the new section**, ~250 lines, self-contained |
| `UpdateUI` detour, after `FirstPersonLookTick()` | `MpStatsTick(thisptr);` |
| dispatch, after `vehstatus` | `mpstats` command |
| `kOurCmds[]`, after `"vehstatus"` | `"mpstats"` |
| `ModHelp` | one line |

**The detour call is the only edit in shared territory.** It sits with the two
existing per-frame ticks and is one line; everything else is either new text
after `DumpRing` or a single entry appended to a list. If you are merging into
this, take both sides — nothing here rewrites existing logic.

**Why it does NOT use the game-rules state machine.** The correct trigger is
`CGameRules::RegisterStateObserver`, which fires on every state transition and
is named in the Far Cry 2 symbol table. **Avatar's address for it is not
resolved**, and a guessed address in a vtable call is how you get a DLL that
looks fine and corrupts the game. So v1 uses only what this file already
proved: `WorldName()` + the existing `IsMp()` for "are we in a multiplayer
level", and the console ring for command output. **Entering an `mp_` world
starts a match, leaving it ends one.**

That is coarser than the state machine — a round restart inside one world reads
as one match — and it is deliberately the coarse version, because it cannot
crash and it produces the data needed to build the precise one.

**Capture works like F10, not like a hook.** `MpCapture` notes the console
ring's `head`/`count`, calls `RunConsoleLine`, then reads what got added — the
same ring fields `DumpRing` uses (`con+0x0C/0x10/0x14/0x18`). One trap worth
keeping: **both counters move.** Until the ring fills, `count` grows and `head`
sits still; once full, `count` pegs at capacity and `head` advances instead. The
delta is the sum of the two, and a naive `count1-count0` silently returns 0
forever on a busy ring.

**All six sampled commands are getters.** `net_EndMatch`, `net_restartmatch`,
`net_ExtendMatch` and the kick commands are deliberately absent and must stay
absent — this runs unattended, during somebody's match. Do not add them.

**It is honest about not knowing yet.** Nobody has confirmed
`net_GetGameScoreStats` prints anything; plenty of Avatar's inherited Far Cry 2
commands execute happily and do nothing. So every sample is written verbatim to
`mp_stats_raw.log` **and** embedded in the record's `raw` field, `players[]`
stays empty (valid per `match_record.py`; a wrong roster would not be), and if
nothing printed all match the log says so and names route B. The answer arrives
from someone playing rather than from someone testing.

**Untested against a running game.** It compiles clean and `check_cmds` passes
85/85, which says nothing about behaviour.

### 2026-08-06 (m) — the remote body is not in the entity tree; label and read what is

**The reverse join (l) reported its own answer, and it is not the one I
expected:**

```
[netp] 2 player(s) without a body and 1 unclaimed MP pawn(s) - ambiguous
```

**One** `PawnPlayerNetwork*` in a 1,249-entity snapshot, with two players in the
match — and that one is ours. So the remote player's body is not in this
client's entity tree under the archetype we spawn players into. Guessing the
next substring would be another round of "try one and see", so the matcher now
prints **every distinct player- or pawn-shaped name in the snapshot** when it
comes up empty. Whatever a replicated remote body is called, the next run puts
it in the log.

Two supporting corrections in the same path:

- **`NetMatchOrphanPawns` moved to AFTER the forward loop.** Run before it, it
  saw the local row's pawn as unclaimed for one sample after every roster
  rebuild — hence "2 without a body and 1 unclaimed", a true statement about a
  picture one step out of date. The elimination step's arithmetic has to be
  computed against what the forward route has already claimed.
- **`hp 16775`.** The sheet's health is not on a 0-100 scale, so the raw number
  says nothing about whether somebody is hurt — which is the only question that
  column is asked. The panel shows **per cent** of the maximum; `admin_gui
  names` prints the raw pair it came from. (Slots 32/35 are unchanged and still
  the verified getters; nothing here claims the 16775 is wrong, only that it is
  unreadable on its own.)

**The team column now labels players who have not spawned.** Measured:
`Zebra 0250BB11` with a `..._Corp` body, `Jasper 9516534B` with no body at all.
Avatar's multiplayer is RDA against Na'vi and nothing else, so once one id is
identified from a pawn, a player carrying a *different* id is on the opposite
side. Gated on the roster holding exactly two distinct ids — three, and it
declines and shows `-` rather than inventing a team.

| Where | What | Risk | New symbols |
|---|---|---|---|
| After `AdmSideById` | **Added** the opposite-side rule | Low | `AdmOtherSide`, `AdmSideByElimination` |
| `AdmBuildRows`, `AdmCollect` source 0 | **Modified** — fall through to it | Low | — |
| `NetMatchOrphanPawns` | **Added** the no-candidate readout | Low | — |
| `AdmCollect` source 0 | **Moved** the call below the loop | Low | — |
| `PkPaint` HP column | **Modified** — per cent | Low | — |
| `admin_gui names` | **Modified** — prints `hp/max` | Low | — |

**Tested off-game**: the labelling was compiled standalone and run through the
measured match — no label before anything is seen, `Corp` → RDA, the opponent
labelled from that alone, a team-mate of a known id, a third id refusing to
guess, an `Avatar` body proving Na'vi directly, and a vehicle archetype
producing no side at all.

### 2026-08-06 (l) — match the remote player from his body, not from his record

**Measured in a live two-player match, with (k) installed:**

```
[netp] roster -> 2 name(s) from Player::GetName
[netp] pawn route: player+0x194 -> +0xC -> entity 19754200 (…PawnPlayerNetwork_Corp)
[netp] team id 0250BB11 is RDA
[netp] no pawn route on the player object (1351F440) - 1247 entities, names present
```

So the forward route is right and it resolves **exactly one** of the two: the
local player. A client owns its own pawn and merely replicates everyone else's,
so there is no reason for a remote's session record to carry a pointer the
client never follows — searching harder in that direction is looking for
something that is not there. (Two hops, a full kilobyte, both players: nothing.)

The pawns themselves are all present, because the game draws them. So the join
now runs **from the entity side** for whoever the forward route missed:

1. **Back-pointer.** Scan each unclaimed `PawnPlayerNetwork*` entity for a word
   that *is* one of the unmatched session records, one hop deep as well.
2. **Elimination**, only when it is arithmetic: one player left without a body,
   one body left without a player. Two of each is a coin toss, so it declines
   and the rows keep saying they do not know.

**The uniqueness rule is load-bearing.** `Readable()` answers at page
granularity, so a kilobyte walk from a smaller object reads its heap
neighbours, and a stale pointer there reads exactly like proof. The offline
harness hit this on its first run — a fixture entity was `0x200` bytes and the
scan sailed past it into freed memory that still held a record pointer. A
back-pointer is therefore only believed when it is unique **both ways**: a body
that appears to claim two players is dropped, and two bodies claiming one player
match neither.

A body matched by elimination is flagged (`PlayerRow.inferred`): `~` on the
panel row, spelled out in `admin_gui names`. A later proof clears it.

| Where | What | Risk | New symbols |
|---|---|---|---|
| `PlayerRow` | **Added** one field | Low | `inferred` |
| After `NetPlayerPawn` | **Added** the reverse join | Low — new code between functions | `NETPL_ORPH_MAX`, `NetIsMpPawn`, `NetPawnPointsAt`, `NetMatchOrphanPawns` |
| `NetPlayerPawn` | **Modified** — the "no route" line now says what happens next | Low | — |
| `AdmCollect` source 0 | **Added** the call, before the loop | Low | — |
| `PkPaint` rows, `admin_gui names` | **Modified** — the `~` flag | Low | — |

`NetIsMpPawn` is deliberately stricter than `NetLooksLikePawn`: eliminating
against "player or pawn anywhere in the name" would count paper dolls and spawn
points and get the arithmetic wrong.

**Tested off-game**: back-pointer match two hops out, elimination with one of
each, two-of-each refusing to guess, two bodies claiming one player matching
neither, and an already-claimed body never being handed out twice.

### 2026-08-06 (k) — a pawn route worth the name, and the team column stops lying

Two things the roster (entry (j)) exposed the moment it started returning names.

**"(not spawned)" for everybody who was standing right there.** With the list
populated, the log still had **no** `pawn pointer found at player+0x…` line, so
`NetPlayerPawn` was failing on every row. It only ever looked one hop deep — a
field on the player object that *is* the entity — and the object the session
enumerates is not the `CPlayer` the local list holds: `GetName` reaches its name
through a refcounted holder at `+0x0C`, and `net_GetPlayerListByTeam` reads a
team id at `+0x08`. That is a session record, so its pawn link is behind another
object.

The search now follows **two** hops, and the second covers the engine's own
idiom — a ref node whose `+0x0C` is the `CEntity*`, which is exactly how
`GetPlayerEntity` already reaches the local pawn. A candidate is only accepted
when the entity it lands on carries a **player-shaped archetype name**: a blind
pointer sweep will otherwise settle on a vehicle or a trigger, and since the
route is cached and applied to every row, one false hit would put the same wrong
pawn on the whole list.

That widened search is only affordable because membership stopped being a linear
walk: ~5,000 probes against a 1,250-row snapshot was 6M comparisons *per player
per sample*. The rows are now sorted once per snapshot (`g_entGen`) and probed
with a binary search.

**`APR` and `UFLL` are Far Cry 2's factions.** `net_GetPlayerListByTeam` walks a
three-entry table at `0x1122A0F8` and prints each team's name above its members;
the middle entry is the inline literal `"APR"`, and the `.rdata` beside the
handler holds `"TEAM UFLL:"` / `"TEAM APR:"` next to `"Prosper Kouassi"`,
`"UFLL SwampBoat"` and `"APR_FinalWarlordName"`. Dunia shipped in Far Cry 2
first and the team table never got replaced, so those labels mean nothing in a
match between the RDA and the Na'vi. The panel stops showing them.

What *is* real is the team id the same handler buckets on — `*(int*)(player+8)`
— it just has no trustworthy name attached. So the name comes from the **pawn**:
Avatar's networked player archetypes are
`player.MainCharacter.PawnPlayerNetwork_Corp` and `..._Avatar` (plus `.Female`
and the `Plaza_` lobby pair), measured in the shipped `gamemodesconfig.xml` and
the world entity libraries. Corp is the RDA, Avatar is the Na'vi. Once one
player on a side has been seen with a body, the id → side pair is learned and
everyone carrying that id is labelled — **including players who have not
spawned**.

| Where | What | Risk | New symbols |
|---|---|---|---|
| `EntRow` block (~1994) | **Added** the snapshot generation counter | Low | `g_entGen` |
| `EntSnapshotEx` end (~8578) | **Added** one line, bumps it | Low | — |
| `PlayerRow` (~14375) | **Added** two fields | Low | `teamId`, `side` |
| After it | **Added** the id → side table | Low | `g_admSide`, `g_admSideN`, `AdmSideOfArchetype`, `AdmLearnSide`, `AdmSideById`, `ADM_SIDE_MAX` |
| `AdmBuildRows` | **Added** the team-id read and the side fallback | Low | — |
| `NetPlayerPawnAt` / `NetIsKnownEntity` | **Replaced** | **Medium** | `EntKey`, `g_entKey*`, `EntKeyCmp`, `NetEntIndexBuild`, `NetEntRow`, `NetLooksLikePawn`, `NetWordAt`, `NetPawnRoute`, `NETPL_HOP2_MAX`, `g_netPawnOff2` |
| `NetPlayerPawn` | **Rewrote** — two hops, validated, rate-limited, logged | **Medium** | — |
| `NetPlayersCmd` | **Modified** — reports the route; `dump` follows pointers | Low | — |
| `AdmTick` source 0 | **Added** the side derivation | Low | — |
| `PkPaint` PLAYERS rows, `admin_gui names` | **Modified** — print `side`, not `team` | Low | — |

**A failed search now says so, once**, with the entity count and whether the
snapshot had names: `[netp] no pawn route on the player object …`. If that line
is in the log, the link is further than two hops and the next step is the
session service, not another sweep.

**Tested off-game**: the search, the index and the acceptance rule were compiled
standalone against a fake world — a two-hop route with a decoy vehicle pointer
planted in front of it, a one-hop route, a cached route reused for a second
player with no re-search, a player with no pawn, a vehicle-only field, and the
blank-name case in both directions (a proven route survives, a new search
refuses to run). All pass.

### 2026-08-06 (j) — the captured string is WIDE; the PLAYERS list fills

**The PLAYERS tab has never been able to show a player, and nothing downstream
of the capture was at fault.** `net_GetPlayerList` printed the names to the
console (the detour forwards everything it does not swallow) and
`hkSink` decoded **zero bytes** out of every line it was handed, so
`g_admNameN` was 0, so `g_plRowN` was 0, so the panel drew "No players" while
the console right behind it listed them. The whole 2.9 MB log has **not one**
`net_GetPlayerList -> N name(s)` line in it — the count went 0 → 0 every
refresh, so the "log only when it changes" guard never fired. That absence is
the fingerprint.

**Entry (h) below got the argument type wrong.** It is not a narrow MSVC
`std::string`. It is a **wide** Dunia string, and the offsets are different:

| | (h) assumed | actually |
|---|---|---|
| characters | inline at `+0x00`, `char` | `+0x04`, `wchar_t` (or a `wchar_t*` in that slot) |
| length | `+0x10` | `+0x14` |
| capacity | `+0x14` | `+0x18` |
| heap when | capacity ≥ 16 | capacity ≥ 8 |

`+0x10` is the **tail of the inline buffer**, so the "length" it read was two
packed UTF-16 characters — `"ra"` is `0x00610072`, which fails the 64 KB sanity
test — and the reader bailed on every line the console has ever printed.

Three independent readers in the retail 1.02 image agree, and the disassembly
is not ambiguous:

- `100AC1F0` (the console's print) formats with the **wide** `vsnprintf` —
  `0x7FF` chars into a `0x1000`-**byte** buffer — then
  `lea ecx,[esp+0xc]` / `push ecx` / `mov ecx,esi` / `call 100AB660`, which also
  confirms the sink is `thiscall(console, string*)` as we hook it. Its cleanup
  is `cmp [obj+0x18], 8` / `free([obj+4])`.
- `100A78F0` (the string's own `find`) does `cmp dword [ecx+0x18], 8` to choose
  heap vs inline, `add ecx, 4` to reach the characters, and indexes them
  `[ecx + eax*2]` — **scale 2**.
- `106F0DD0` (`net_GetPlayerListByTeam`) reads the same three fields the same
  way before printing.

| Where | What | Risk | New symbols |
|---|---|---|---|
| `StdStrRead` (~14016) | **Replaced** by a wide reader that writes into the caller's buffer | **Medium** | `DuniaStrRead`, `DSTR_BUF_OFF`, `DSTR_SIZE_OFF`, `DSTR_RES_OFF`, `DSTR_INLINE` |
| `hkSink` | **Modified** — decodes into a local, appends that | Low | — |
| `hkGetName` | **Modified** — forwards first, then records the name off the return | Low | `g_netEnumName` |
| Roster block | **Added** the paired Player\* array | Low | `g_admPlayer` |
| `AdmBuildRows` | **Modified** — one line, reads `g_admPlayer` | Low | — |
| `AdmRefreshNames` | **Rewrote** — hook first, console text as fallback | **Medium** | — |
| `PkPaint` PLAYERS header | **Modified** — one line, counts `g_plRowN` | Low | — |

**The names now come off the engine, not out of the console.**
`Player::GetName` is `ret 4` and ends `mov eax, edi` — it hands back the string
it just filled — and `net_GetPlayerList`'s handler does nothing with it except
print it. So the detour reads the return value and gets exactly what the console
was about to show, one step earlier: no echo to reject, no punctuation
heuristic, and a name paired with its `Player*` by construction instead of by
counting lines. The text parse stays as the fallback for a build where the
`GetName` prologue does not match and the hook refuses to install.

`STDSTR_SIZE_OFF` / `STDSTR_RES_OFF` are **gone** — check for them before
merging anything that used them.

**Tested off-game**: `DuniaStrRead` was compiled standalone against objects
built to the measured layout — inline, heap, the capacity-8 boundary, a garbage
length, an unreadable pointer, and truncation into a short buffer. It also
reproduces the old reader's failure on the same objects (`"JasperZ"` → length
90, capacity 7 → rejected), which is what makes the diagnosis above a
measurement rather than a story.

### 2026-08-06 (i) — the panel is the tool; detection stops depending on the local list

| Where | What | Risk | New symbols |
|---|---|---|---|
| Admin state block | **Added** the wide flag | Low | `g_admWide` |
| `AdmLooksLikePlayer` | **Widened** — `player`/`pawn`, plus a wide mode | **Medium** | — |
| After it | **Added** the reject recorder | Low | `AdmCand`, `g_admCand`, `g_admCandN`, `AdmNoteCandidate`, `ADM_CAND_MAX/DIST` |
| `AdmCollect` entity scan | **Un-gated** — no longer `if (n <= 1)` | **Medium** | — |
| `AdminGui` dispatch | **Added** `wide` | Low | — |
| `PkPaint` PLAYERS block | **Rewritten** — coords, counts, reject block | **Medium** | — |
| `PkClick` PLAYERS buttons | **4 → 5 buttons** | Medium | — |

**The entity scan was gated behind `if (n <= 1)` and that was backwards.**
`PLAYERLIST` is the *local* player list — it measured `count=1` in a live
two-player match — so the gate skipped the broad scan in exactly the sessions
where the list was working, and the overlay could only box people the local
client already tracked. It now always runs and merges; `AdmAlreadyHave` dedupes
by world position, so a player found twice costs one comparison while a player
found zero times is the entire failure this tool exists to prevent.

**The three original substrings were a filter derived from two samples.**
`remoteplayer` / `pawnplayer` / `playerpawn` came from the two archetypes a
*modded* client reported, so of course they found those two. The default net is
now `player` **or** `pawn` anywhere in the name or class, and `admin_gui wide`
(the WIDE button) adds `character/avatar/navi/soldier/human`.

Wide is a toggle, not the default: a wider filter boxes props, and an overlay
that marks scenery as people is one an admin stops believing — which costs more
than a miss.

**Rejected candidates within 120 m are shown in the panel.** The question
"what does a player *without* our DLL look like in the entity list?" can only be
answered while standing next to one, and nobody alt-tabs to a log file
mid-match. The unmatched block is the measurement, on screen, where the work is.

**The pawn rows carry world X/Y/Z now, not just a distance.** Distance says how
far, never where — useless for "is he inside the rock" or "did he cross the map
in one second", which is what the list is for. Names are trimmed to the last
dotted segment because the archetypes are identical for their first thirty
characters.

> BOXES moved onto the panel (button 3). Arming the overlay from the GUI is the
> difference between an admin tool and a readout that needs a console command
> before it does anything.

### 2026-08-06 (h) — capture the console SINK, not `Printf`; kick is case-sensitive

**`CConsole::Printf` was the wrong hook.** It installed fine
(`[cap ] CConsole::Printf hooked at 100AC0C0` in the log) and captured
**nothing** — a whole session produced zero `net_GetPlayerList -> N name(s)`
lines while the names printed to the console normally. Printf is only *one of
five* call sites into the line writer, and the player list uses another.

| Where | What | Risk | New symbols |
|---|---|---|---|
| Address block (~line 55) | **Added** the sink address | Low | `FN_CON_SINK` = `0x100AB660` |
| `fnPrintfFwd` | **Replaced** by a thiscall-shaped typedef | Low | `fnSinkFwd` |
| `hkPrintf` | **Replaced** by `hkSink` | **Medium** | `hkSink`, `StdStrRead`, `STDSTR_*_OFF` |
| `InstallPrintfHook` | **Modified** — patches the sink, new prologue | Medium | — |
| `AdminKick` | **Added** case correction against the roster | Low | — |

**How the sink was found.** Disassemble `Printf` at `0x100AC0C0`; it makes five
direct calls. Counting `E8 rel32` encodings across `.text` for each target:
`0x10003590` 3369 callers, `0x10EE24B0` 8584 (CRT), `0x10004290` 62, and
**`0x100AB660` just 5** — the shape of a private sink, reached with
`mov ecx, esi` (the console) and one pushed argument.

> **WRONG — corrected by (j) above.** The paragraph that follows described the
> argument as a narrow `std::string` with size at `+0x10`. It is a **wide**
> string with length at `+0x14`, capacity at `+0x18` and characters at `+0x04`,
> and this mistake is why the capture returned nothing for the two days between
> these entries. `StdStrRead` no longer exists. Left in place because the *hook
> site* it describes is correct and still current.

**The argument is a plain MSVC `std::string`,** read off `Printf`'s own call
site: the object is built at `esp+0x28`, `mov [esp+0x40], 0xf` sets capacity and
`mov [esp+0x3c], ebx` sets size, and `esp+0x2c` is what gets pushed — so from
the received pointer, size is at `+0x10`, capacity at `+0x14`, characters inline
until capacity reaches 16. `StdStrRead` bounds-checks all of it and returns NULL
on anything implausible, in which case the line is forwarded untouched.

Prologue `83 EC 24 53 56 57` (`sub esp,0x24` / `push ebx,esi,edi`) — six bytes,
none relative, so the existing trampoline machinery relocates it unchanged.

**The hook adds its own `\n`.** The sink is called once per *line* and the text
carries no terminator, so without it the parser saw `JasperQuiet_JokerZebra` as
one name.

> Hooking the sink means **every** console line passes through our code, not
> just `Printf`'s. That is the point — but it also means a mistake here is
> visible everywhere, so `StdStrRead` fails safe and the suppression is ANDed
> with `g_capOn`.

**`net_kickClient` matches the account name CASE-SENSITIVELY.** Measured three
times in a live match: `kick quiet_joker` → "Player not found.",
`kick Quiet_Joker` → "Kicking player Quiet_Joker.", `kickban jasper` → "Player
not found." Nothing in the shipped usage string says so, and the failure is a
lookup miss that reads exactly like "that player is not here" — so the natural
response to a lowercase attempt is to try a different *name*, not a different
*case*. `AdminKick` now matches the roster case-insensitively and sends the
exact spelling the session reported; an unknown name is passed through so the
engine can answer for itself.

### 2026-08-06 (g) — PLAYERS tab: click a name, kick it

The kick path itself was already right (proved in a live match by typing
`net_GetPlayerList` then `kick <name>`). **Everything broken here was in the
panel between the roster and the button.**

| Where | What | Risk | New symbols |
|---|---|---|---|
| `PK_MODE_SPAWN`/`_ENTS` define site | **Moved** `PK_MODE_PLAYERS` up to join them | Low — same value | — |
| Capture state | **Added** quiet flag | Low | `g_capQuiet` |
| `hkPrintf` | **Modified** — returns early on a quiet capture | Low | — |
| `CaptureRun` | **Signature changed** — gained `int quiet` | **Medium** — one call site | — |
| `AdmRefreshNames` | **Signature changed** — gained `int quiet`; logs only on change | Medium | — |
| `AdminGui` dispatch | **Added** `pick`; `names` now prefix-matched with `quiet` | Low | — |
| `hkUpdateUI` (before the `QueuePop` loop) | **Added** 4 s roster refresh while the tab is open | Low | — |
| `PkClick` PLAYERS block | **Fixed** — bounds by `g_admNameN`; buttons explain themselves | **Medium** | — |
| `PkClick` tab switch | **Added** — entering PLAYERS queues a quiet refresh | Low | — |
| `PkPaint` PLAYERS block | **Modified** — one highlight, divider, messages moved | Medium | — |

**The bug that made KICK look dead.** Row selection was bounded by
`g_admRectN` — the *ESP box* count — while the button indexed `g_admNames[]`,
bounded by `g_admNameN`. Two lists, two lengths, one index. With the roster
showing two players and the entity sampler finding none, `g_admRectN` was 0, so
**no row was ever selectable** and KICK returned without a word. The mirror case
(more rects than names) let you select a row with no name behind it, and KICK
bailed out just as silently. Selection is now bounded by the array the buttons
actually read.

**The position rows are deliberately not selectable.** They carry archetypes
like `PawnPlayerNetwork_Avatar`; kick matches account names, so selecting one
could only ever produce a refusal. They are now under a `-- positions (not
kickable) --` divider, and the paint no longer highlights them at
`g_pkPlSel` — that index belongs to the name list, and drawing it in both
places meant one selection lit up two rows.

**No silent failures on the buttons.** A dead button is indistinguishable from a
kick the server refused. KICK/BAN with nothing chosen now queue `admin_gui pick`
(roster present) or `admin_gui names` (no roster yet).

**The roster refreshes itself**: on tab entry, and every 4 s while the tab is
open, because people join and leave while staff are reading the list and a stale
name is worse than no name — it will be clicked. Both are *quiet*
(`g_capQuiet`): `net_GetPlayerList` prints every name every call, and forwarding
that several times a minute would bury the console. A list the user *asked* for
still prints in full.

> **If you touch `CaptureRun` or `AdmRefreshNames`, both gained a trailing
> `quiet` parameter.** That is the whole conflict surface for this change.

### 2026-08-05 (e) — resizable panel, entity-scan fix, self-box

| Where | What | Risk | New symbols |
|---|---|---|---|
| `PK_W`/`PK_H` definition site | **Rewrote** — constants became macros over `g_pkW`/`g_pkH` | **Medium** — every layout expression follows it | `PK_W_DEF/MIN/MAX`, `PK_H_*`, `PK_GRIP`, `g_pkW`, `g_pkH` |
| Picker snapshot globals | **Added** | Low | `g_pkSnapW`, `g_pkSnapH`, `g_pkSizing` |
| `PkEnsureGdi` | **Modified** — DIB and snapshot allocate at MAX | **Medium** | — |
| `PkPaint` tail | **Modified** — row-strided alpha + publish; grip drawn | **Medium** | — |
| `DrawOverlayD3D` picker block | **Modified** — sizes from the snapshot, not `PK_W/PK_H` | **Medium** | — |
| `PkClick` / `PkDrag` | **Added** grip hit-test and resize drag | Medium | — |
| `AdmCollect` fallback | **Modified** — takes its own `EntSnapshotEx(1)` | Low | — |
| Admin state / `AdmDrawD3D` / `AdminGui` | **Added** | Low | `g_admListN`, `g_admEnts`, `g_admDrawn`, `g_admSelf` |

**THE SURFACE IS ALLOCATED ONCE AT MAX AND NEVER REALLOCATED.** This is the
safety argument for the whole resize feature, not an optimisation. Three threads
touch the picker surface with **no lock**: `PkPaint` writes it on the overlay
thread, `PkClick`/`PkDrag` resize on the input thread, `DrawOverlayD3D` reads it
on the render thread. That is survivable only because a torn read of a
fixed-size buffer is a torn *frame*. Reallocating or freeing it from the input
thread would turn the same benign race into a use-after-free. Resizing therefore
changes only how much of the surface is *used*; rows are copied with an explicit
`PK_W_MAX` stride.

The snapshot publishes its own `g_pkSnapW/H`, and the render thread sizes its
texture and quad from **those**, never from the live `PK_W/PK_H` the input
thread can change mid-frame. Dimensions are stored *before* the ready/dirty
flags, so a new frame is never described by stale dimensions. Same pattern
`DrawOverlayD3D` already used for the console panel.

**The grip is hit-tested first and painted last**, and those two orders have to
agree — otherwise it is a target you can see but not press.

**Two real bugs fixed here, both of which produced convincing silence:**

1. `AdmCollect`'s entity fallback scanned `g_entRows`, which is only filled by
   `EntSnapshot` on demand. In a fresh session `g_entCount` was 0, so it examined
   nothing and reported "1 player" — indistinguishable from an empty lobby. It
   now takes its own snapshot, throttled to 3 s because a full metadata snapshot
   is ~95 ms.
2. `AdmDrawD3D` skipped `r->local`, so with one player in the session it drew
   **nothing** and looked broken. The local player is now boxed in green by
   default (`admin_gui self`) — it is also the only target whose projection you
   can independently verify, which makes it the calibration check for
   world→screen and `pickfov`.

### 2026-08-05 (d) — kick / kickban

| Where | What | Risk | New symbols |
|---|---|---|---|
| `AdminKick()`, anchor `/* ---- kick / kickban`, just above `AdminGui` | **Added** | **None** | `AdminKick()` |
| Dispatch, after the `admin_gui` arm | **Added** 10 lines | Low | — |
| `kOurCmds[]`, `ModHelp` | **Modified** / **Added** | Medium / Low | — |

**`kickban` must be tested before `kick`** in the dispatch chain — `kick` is a
prefix of it, and testing the shorter name first makes `kickban` unreachable.
If you reorder those arms, that is the bug you just introduced.

**The argument is a player NAME.** Established from strings shipped in
`Dunia.dll`, not from disassembly:

```
"Kick the specified player. Usage: \"net_kickClient <player name>\"."
"Kick/Ban the specified player. Usage: \"net_kickBanClient <player name>\"."
"Kicking player %s."   "Cannot kick player."   CKickBanService
```

Two routes failed before that one worked, and both are worth knowing: the
addresses in `DevAccess/COMMANDS.md` are the **name-string literals**, not
descriptors, and the registration site at `0x106F1897` only hands the console a
`std::string` — there is no per-command function pointer to follow.

We do **not** reimplement the kick — `AdminKick` builds the line and runs it
through `RunConsoleLine` (the engine's own `ExecuteLine` idiom), so all of the
session layer's authority checks still apply. `kick <n>` resolves an index from
the last `admin_gui` sample and always prints the resolved name before sending.

Counts after this change: **79 dispatched, 79 in `kOurCmds[]`**.

### 2026-08-05 (c) — admin overlay: player boxes + movement tracking

| Where | What | Risk | New symbols |
|---|---|---|---|
| Admin state block, anchor `/* ---- ADMIN OVERLAY state`, just above `TryModCommand` | **Added** | **None** — new block between untouched functions | `ADM_MAX`, `ADM_NLEN`, `ADM_NEAR`, `ADM_LOG_NAME`, `AdmRect`, `g_admRect`, `g_admRectN`, `g_admCs`, `g_admCsInit`, `g_admOn`, `g_admLog`, `g_admEvery`, `g_admSrc`, `g_admSeen`, `AdmEnsureCs()`, `AdminGui()` |
| Sampling block, anchor `/* ---- ADMIN OVERLAY: who is in the session`, just above `hkUpdateUI` | **Added** | **None** | `AdmView`, `AdmProject()`, `AdmBoxFor()`, `StrIStr_()`, `AdmLooksLikePlayer()`, `AdmAlreadyHave()`, `AdmLogRow()`, `AdmCollect()`, `AdmTick()` |
| Draw block, anchor `/* ---- ADMIN OVERLAY: the drawing half`, just above `hkRDPresent` | **Added** | **None** | `AdmDrawD3D()` |
| `hkUpdateUI`, after `InterlockedIncrement(&g_frames)` | **Added** 1 call (`AdmTick()`) | **Medium** — hot path both authors edit | — |
| `hkRDPresent` | **Added** a second `__try` block after the existing one | **Medium** — same reason | — |
| `kOurCmds[]`, dispatch, `ModHelp` | **Modified** / **Added** | Medium / Low | — |

**Why the state is split from the code that uses it:** `TryModCommand` is at
~13727 and the sampling code is ~2,000 lines later, so the dispatcher cannot see
state declared next to its own functions. The alternative was a forward
declaration per symbol. If you move either block, keep the state above
`TryModCommand`.

**The threading split is not optional.** `AdmTick` runs on the **main thread**
from the per-frame detour because it calls `GetWorldAABB` — an engine call, and
this file's oldest rule is that those are main-thread-only. It publishes
finished *screen rectangles* under `g_admCs`; `AdmDrawD3D` runs on the **render
thread** and reads only those. No engine pointer crosses the boundary. Same
split `DrawOverlayD3D` already uses.

**`AdmDrawD3D` is deliberately NOT behind the `g_ourPanel` test** in
`hkRDPresent` — the boxes must show while the console panel is closed, so it
needs its own condition and its own `__try`.

Counts after this change: **77 dispatched, 77 in `kOurCmds[]`**.

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
