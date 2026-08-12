# Getting match stats out of the game and onto our server

The stat schema and where the game keeps it: `../DevAccess/MP_STATS.md`.
This folder is the transport half.

```
  game process                    game machine                  our server
 ┌──────────────┐   append    ┌──────────────────┐   POST    ┌─────────────┐
 │ console DLL  │ ─────────▶  │  matches.jsonl   │ ────────▶ │  stats site │
 │ (writes,     │  one line   │                  │  retries  │             │
 │  then closes)│  per match  │ stats_uploader   │  offline  │  dedupes by │
 └──────────────┘             │  (separate proc) │  queue    │  match_id   │
                              └──────────────────┘           └─────────────┘
```

---

## "Can we do the hosts-file trick in reverse?"

**No — and it is worth being precise about why, because the reason also says what to do instead.**

The hosts file works for *joining* because it hijacks a request **the game already makes**. Avatar
has hardcoded hostnames it looks up, you can't change them, so you change what they resolve to.
DNS redirection is interception: it needs existing traffic to intercept.

For stats there is no traffic to intercept. `Dunia.dll` contains **no stats upload of any kind** —
no GameSpy, no account service, no leaderboard client. Nothing ever tries to send a match result
anywhere, so there is no hostname to redirect and no request to capture. (The one HTTP-ish thing in
the binary is `http://ubi.com` with `visitor_id` / `userid` — Ubisoft's tracking-cookie reader,
which uploads nothing of ours.)

**The good news is that this makes it easier, not harder.** Redirecting someone else's protocol
means reverse-engineering their wire format and matching it exactly. Here we are writing the client
ourselves, so we choose the format, the endpoint and the auth — and **no hosts-file edit is needed
at all**. Our uploader can point straight at an IP or a domain we control. That is one less thing
for every player to configure, and one less thing to go wrong.

---

## Why the upload does not live in the DLL

The DLL appends a line to a file and closes it. Everything that can fail happens in a separate
process. Three reasons, in order of how much they'd hurt:

1. **A blocking POST on a game thread hitches or hangs the game.** The console DLL runs on hooked
   engine threads. A server that is slow, down, or behind a captive portal would become a game
   freeze at the exact moment the match ends. Nobody would blame the server.
2. **It keeps network code out of a DLL that already has to explain itself.** `console_dll` ships
   its injector as readable Python specifically because an unknown binary touching a game process
   reads as malware. A binary that also opens outbound sockets is a harder sell for no benefit.
3. **The API can change without rebuilding the DLL.** Rebuilding means MSVC x86 and a working
   toolchain; changing the uploader means editing a Python file.

The cost is one more process to run. That is the right trade.

---

## The contract

One match per line, appended, never rewritten — see `match_record.py`. JSON Lines because the
writer is a C DLL: append one line, close, done. A crash mid-write costs at most the line being
written, and the reader **tracks a byte offset** so a half-written trailing line is left alone
until it is complete rather than being parsed as garbage.

```json
{"schema":1,"match_id":"...","recorded_utc":"...","map":"mp_swamp",
 "gamemode":"FCXTeamDeathMatch","duration_s":600,
 "players":[{"name":"Jake","team":"navi","stats":{"kills":12,"headshotKills":4}}],
 "game_stats":{"redTeamScore":50,"blueTeamScore":43}}
```

Stat names are **exactly as spelled in `gamemodesconfig.xml`** — `headshotKills`, not
`headshotkills`. The engine keys them by CRC-32 of the exact-case string; see `MP_STATS.md`.

Stat *values* are numbers, not integers: `CStatServiceAdapter::GetStatInfo` hands back a `float&`,
so the schema accepts floats throughout.

Delivery is **at-least-once**, deduplicated server-side by `match_id`:

| Response | Meaning | Uploader does |
|---|---|---|
| `201` | stored | advance |
| `200` | already had it | advance — **this is not an error** |
| `400` | malformed | advance, log, never retry (do not wedge the queue) |
| `401` | bad token | advance, log |
| `408` `429` `5xx` | try again | keep offset, exponential backoff to 5 min |

## Running it

```
# reference receiver, for testing before the real site exists
python stats_receiver.py --port 8778 --store matches/ --token SECRET

# on each player's machine
python stats_uploader.py --file "<game>/bin/matches.jsonl" \
                         --url  https://stats.example/api/matches \
                         --token SECRET
```

`--once` drains and exits, for a scheduled task instead of a resident process.
Progress lives in `<file>.uploaded`; delete it to re-send everything (the server dedupes).
Both are stdlib-only — no `pip install`, same as `inject.py`.

`stats_receiver.py` is a **reference implementation, not the production site**. It exists so the
game side can be tested before the real server exists, and so the real server has an unambiguous
statement of the contract. It stores one JSON file per match and has no UI beyond `GET /matches`.

### Verified

End-to-end against the real receiver: a partial trailing line is not consumed; a malformed line is
skipped without blocking the queue; a restart resumes from the offset without re-sending; a
deliberate duplicate returns `200`; a wrong token returns `401`.

---

## Making it automatic — the game already has the state machine

Nothing here needs a keypress, and nothing needs a command typed. The engine
runs the match as an explicit state machine, and every trigger we need is a
transition in it. From `avatar_class_hierarchy.tsv`:

```
CGRStateIdle
CGRStateLoad ─► CGRStateLoadWorld ─► CGRStateLoadPlayer
CGRStateAdversarialLobby / CGRStateTeamAdversarialLobby    ← players joining
CGRStatePreRound  (CFCXGRStatePreRound)                    ← about to start
   │
   ├─ CFCXGRStateDeathMatchInRound        ◄── ARM HERE
   ├─ CFCXGRStateTeamDeathMatchInRound         (one class per game mode,
   ├─ CFCXGRStateCTFInRound                     so the state itself tells
   ├─ CFCXGRStateVIPInRound                     us which mode is running --
   ├─ CBTZGRStateCNHInRound                     no separate lookup)
   ├─ CBTZGRStateHordeInRound
   └─ CBTZGRStateFinalBattleInRound
   │
CGRStatePostRound (CFCXGRStatePostRound)                   ◄── WRITE HERE
```

So the whole lifecycle the stats need is:

| Transition | What the DLL does |
|---|---|
| → any `*InRound` | new match: stamp start time, generate `match_id`, note the mode (from *which* InRound state it is), read map/host once |
| during the round | nothing, if the numbers survive to PostRound — otherwise sample periodically |
| → `PostRound` | collect the final stats, append **one** line to `matches.jsonl`, close |

`PostRound` is the right place to write because it is where the engine itself
considers the round finished and the scoreboard final — the same moment
`CGREventEndGameStatsReceived` exists for.

### The engine hands us the transitions — we do not have to watch for them

An earlier draft of this file proposed polling the state every second. **Don't.**
The engine has a built-in observer interface for exactly this, and the Far Cry 2
symbol table names it outright:

```cpp
CGameRules::RegisterStateObserver(IGameRulesStateObserver*)
CGameRules::UnRegisterStateObserver(IGameRulesStateObserver*)
CGameModeManager::GetGameRules() const      // how we reach it
CGameRules::ProcessEvent(CGREvent const&)   // where the events go
```

Register an observer and the engine calls us **on every state transition** —
no timer, no vtable scanning, no sampling window to miss a short round in. This
is the intended extension point rather than something we are sneaking past.

Two more that come free from the same object, and save guessing at durations:

```cpp
CGameRules::GetElapsedTime()   CGameRules::GetTimeLeft()   CGameRules::GetTimeOut()
```

`CGameRules` and `CGRState` are both confirmed present in Avatar's `Dunia.dll`
(RTTI registration at decompile line 61653 / 61671). **The Avatar addresses for
these are not yet resolved** — that is the remaining RE, and per AGENTS.md it
wants the shipped DLL disassembled rather than the decompile trusted.

Identity comes from the RTTI class-descriptor globals, which are lazily
initialised per class and unique:

| State | class-descriptor global |
|---|---|
| `CFCXGRStateDeathMatchInRound` | `DAT_1122AB38` |
| `CFCXGRStateTeamDeathMatchInRound` | `DAT_1122A6FC` |
| `CGRStatePostRound` | `DAT_1122A55C` |

**Not yet found: how to reach the current `CGRState` from a global.** That is
the one piece of plumbing the automatic version still needs, and it is the same
kind of pointer-chase the DLL already does for `CConsole` and `CBTZGame`.

### Who runs the uploader

**The host, not every player.** In a match the host has the authoritative
numbers; a client only ever sees what was replicated to it (37 of the 84 stats
carry `livereplication="1"`). So the machine that should be writing and
uploading `matches.jsonl` is the one hosting — which is also the machine where
requiring Python is nothing, because it is ours.

That keeps the player-facing story exactly as it is today: **drop in
`dinput8.dll`, start the game, play.** No Python, no terminal, no hosts edit
for stats. This matters — `DISTRIBUTION.md` promises the drop-in needs nothing
else, and stats must not be what breaks that promise.

---

## The open end: getting the numbers out of the game

Everything above works today. **What does not exist yet is the DLL code that writes
`matches.jsonl`** — and there are two candidate routes. Which one to build is a five-minute test,
not a design argument.

**Route A — the console commands.** The engine registers `net_GetGameScoreStats`,
`net_GetPlayerList` and `net_GetPlayerListByTeam` (confirmed in the registration block at
`~0x1135665`, and present in `console_dll/data/console_cmds.txt`). `console_dll` can already
execute a command and capture console output. If those commands print what their names suggest,
this is the whole job — no memory layout, no offsets, no addresses to break on a patch.

**Route B — read `CGameStatsService` directly.** Its vtable `0x110A5258` is written **exactly once
in the entire binary**, so identity-checking it is safe, and that is the same pattern the DLL
already uses for `CConsole` and `CBTZGame`. But the per-player stat container's offsets are not
established, and this is precisely what AGENTS.md warns about: *"for anything load-bearing,
disassemble the shipped DLL rather than trusting the decompile."*

**The DLL probes itself — no keypresses.** `probe_cmds.txt` in this folder is the command list,
but it is not something anyone should have to run by hand. The DLL already executes console
commands and already captures console output, so the collector runs those commands itself at
`PostRound` and writes what came back. If Route A works, that *is* the record. If the commands turn
out inert — plenty of Avatar's inherited Far Cry 2 commands are, exactly like `Cheat_godmode` —
the DLL logs "produced nothing" and we know to build Route B, without anyone having had to test
anything.

The one thing that cannot be automated away is **somebody playing a multiplayer match once** with
the new DLL loaded. That is not a manual step so much as it is the only way any of this gets
exercised at all — the whole system is unverified until a real match runs through it. Score a
couple of kills when it happens: **zeroes everywhere are indistinguishable from "the command does
nothing"**, which is the one outcome that would tell us nothing.

`probe_cmds.txt` stays as the vetted command list — every line a getter, with `net_EndMatch`,
`net_restartmatch` and the kick commands deliberately excluded. It doubles as the manual fallback
if the automatic path itself needs debugging.

Nothing in Route A or B has been run against a running game.
