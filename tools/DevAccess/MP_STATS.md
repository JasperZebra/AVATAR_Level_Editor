# Multiplayer stats — where they live, and why nothing ever leaves the machine

*Avatar: The Game (2009), PC retail 1.02. Sources: `data/engine/gamemodes/gamemodesconfig.xml`
shipped with the game, static analysis of `Dunia.dll`, and the Far Cry 2 Linux dedicated-server
symbol table (same Dunia engine, **real C++ names**) at `Downloads/Far_Cry_2/FarCry2_LinuxServer_Symbols.txt`.*

*Companion files: `mp_stats.json` / `mp_stats_fc2.json` (machine-readable, generated) and
`extract_mp_stats.py` (regenerates them from each game's XML).*

---

## The one-sentence answer

**The stats are all there and fully computed — the game just has nowhere to send them.**
`CGameStatsService` tracks 84 multiplayer stats per player, replicates 37 of them live to every
peer, and fires an end-of-match event with the final numbers. Then the match ends and they are
gone, because **Avatar's `Dunia.dll` contains no account service, no leaderboard client and no
stats-upload path of any kind.**

That is the good news: nothing has to be un-broken. There is a complete, live, correct dataset in
memory and the only missing piece is a reader.

---

## What the game does *not* have

Grepped the full decompile for every online-persistence class the engine could plausibly carry:

| Searched for | Result in Avatar `Dunia.dll` |
|---|---|
| `gamespy` (any case) | **absent** |
| `CAccountService` | **absent** (exists in the FC2 server build) |
| `OnlineService`, `StatsUpload`, `PersistentStorage`, `Leaderboard` | **absent** |
| `CFCXRankService` | present — but it only turns local `xp` into a local `rank` |
| `CPersistenceMgr` | present — local savegame, single-player |

So this is not a dead endpoint that could be re-pointed at a private server. There is no client
code to redirect. **Anything that leaves the process has to be code we add.**

---

## The schema — 105 stats, and it is data-driven

Every stat is declared in **`data/engine/gamemodes/gamemodesconfig.xml`**, in the
`<GameStatsService>` block (line ~2169). Nothing is hardcoded: the service reads this file at
startup and builds its tables from it.

> **Two copies ship, and the one that loads is the other one.** `ATGE/patch/engine/gamemodes/`
> holds a second `gamemodesconfig.xml` that is **Dunia binary XML**, not text — it starts
> `00 00 FF 83`, and `ET.parse` rejects it. `patch.pak` overrides `data/`, so the binary copy is
> what retail 1.02 actually reads. Decoded it with `tools/convert_avatar_xml.py` and compared all
> 120 stat declarations attribute-by-attribute: **the two schemas are identical**. So the readable
> `data/` copy is safe to work from — but do not assume that for any other setting in this file.

```
game modes with stat lists : 11
distinct stat names        : 105
multiplayer stat names     :  84   (the other 21 are FCXSingle)
live-replicated            :  37
```

Modes inherit with `parent=`, and a child's redeclaration overrides the parent's:

```
Adversarial                          78 player stats + 1 game stat
├── TeamAdversarial                  +redTeamScore, +blueTeamScore
│   ├── FCXTeamDeathMatch            kills→score +1, suicides→score −1
│   │   └── BTZHorde                 +animalKills(xp+10), deaths(xp−5), +RespawnLeft
│   ├── FCXCTF                       diamondsStolen/Returned/Saved
│   ├── FCXVIP                       +finalVipKills, +isAvip  (80 total)
│   ├── BTZCNH                       pointsCaptured(xp+50), pointsRecovered(xp+100)
│   │   └── BTZKingOfTheHill         (inherits CNH unchanged)
│   └── BTZFinalBattle               objectRepaired/objectDestroyed
└── FCXDeathMatch                    kills→score +1, suicides→score −1
```

`FCXSingle`'s 21 stats are **inert Far Cry 2 leftovers** — `diamond_found`, `npc_machete_killed`,
`purchased_training_manual`. Same story as the FC2 console commands documented in
`../console_dll/console_dll/docs/DISTRIBUTION.md`. Ignore them.

### The interesting part: stats drive each other

A `<Modifier>` makes one stat feed another, and this is the entire scoring and XP economy:

```xml
<Stat name="headshotKills" livereplication="1" displayable="1">
  <Modifier name="kills" value="1" />     <!-- also counts as a kill -->
  <Modifier name="xp"    value="5" />     <!-- and pays 5 xp on top of kills' own 10 -->
</Stat>
```

So a headshot is worth **15 xp** (10 from `kills` + 5 from `headshotKills`), and the seven
kill-type stats each roll up into `kills`. Team kills and team executions pay **−15 xp**;
suicide is **−2**. In CTF, returning a diamond is **50 xp** and one point of team score.

There are also two derived kinds that are computed, not counted:

* `<StatRatio name="killDeathRatio" topStat="kills" subStat="deaths">`
* `<StatDiff  name="winLossSum" statA="wins" statB="losses">`

`mp_stats.json` has all of this resolved per mode, with the modifiers attached.

### You can add your own stats

Because the list is XML the game parses at runtime, a new `<Stat>` with a `<Modifier>` is a
supported edit, not a patch. Worth knowing before anyone writes C to compute something the
engine would happily count natively.

---

## Far Cry 2 has the same system — and 79 stats Avatar dropped

Same engine, same `<GameStatsService>` block, same file name. Ran the same extractor over FC2's
copy (`mp_stats_fc2.json`):

| | Avatar | Far Cry 2 |
|---|---|---|
| distinct stats | 105 | **179** |
| multiplayer stats | 84 | **158** |
| live-replicated | 37 | 33 |
| modes with stat lists | 11 | 8 |
| names shared by both | 100 | 100 |

Avatar adds only 5 of its own — `FB_objectRepaired`, `FB_objectDestroyed`, `VIP_pointsRecovered`,
`animalKills`, `RespawnLeft` — the stats for Final Battle, CNH and Horde, the modes FC2 never had.

**Every one of FC2's 79 extras is a per-weapon breakdown**, in three families:

```
Kills_ak47        Kills_mp5     Kills_dragunov   ...  (27 weapons)
Headshots_ak47    Headshots_mp5 ...                   (21 weapons)
Executions_ak47   Executions_mp5 ...                  (27 weapons)
Multikills_MGL140 Multikills_rpg-7 ...                 (5 explosives)
```

So **Avatar has no per-weapon stats at all** — you can learn that a player got a headshot, never
what they got it with. If the server wants weapon breakdowns, that gap is the reason.

FC2 proves the engine supports the pattern, and the list being XML makes *declaring* the stats
trivial. **But declaring them is not the same as filling them** — something in FC2's code
incremented `Kills_ak47`, and whether that code survives in Avatar's `Dunia.dll` is unknown and
untested. Treat "add per-weapon stats to Avatar" as an experiment, not a plan.

Cross-check that came free: the 100 shared names hash **identically** under both extractions, which
is what you would expect and worth having on the record.

---

## Where they live at runtime

| Class | Avatar `Dunia.dll` | Note |
|---|---|---|
| `CGameStatsService` | RTTI at `FUN_106db880`, factory allocates **0xC0 (192) bytes** | derives `IGameStatsService` → `IGameModeService` |
| `IGameStatsService` | `FUN_104f9430` | the interface the game mode holds |
| `CScoreboardService` | `FUN_10635b20` | display only, reads the above |
| `CGREventEndGameStatsReceived` | `FUN_1023ada0` | **game-rules event, fired with the final numbers** |
| `CPlayerStatsFullNetDataContainer` | `FUN_1023add0` | full per-player dump over the wire |
| `CPlayerStatsNetDataContainer` | `FUN_1023ae00` | |
| `CPlayerStatRefreshOneNetDataContainer` | registered in `FUN_1023aed0` | **single-stat live update** |
| `CPlayerStatsMementoNetDataContainer` | registered in `FUN_1023aed0` | snapshot/restore |

The service is reached the same way every other game-mode service is — the FC2 symbols give the
exact shape:

```cpp
CGameModeManager::ms_instance                       // singleton
CGameMode::GetGameModeService(CStringID const&, bool)   // generic accessor
CGameStatsService* CGameModeManager::GetGameModeService<CGameStatsService>(bool)  // typed wrapper
CStatServiceAdapter::GetStatInfo(CStringID const&, CStringID& out, float& outValue)  // read one stat
```

`GetStatInfo` returning `float&` is worth noting: **stats are floats**, not integers, even the
counters.

---

## The one real obstacle: the names are not in the binary

Grepping Avatar's `Dunia.dll` for the stat name strings — `"kills"`, `"score"`, `"deaths"`,
`"headshotKills"` — returns **zero matches**. The class names are all there; the stat names are not.

That is because the runtime key is `CStringID`, a **hash**. The XML is parsed once at startup, each
name is hashed, and the string is thrown away. So a memory reader cannot search for `kills` — it
has to match `0x[hash]` and map back.

We already know how to compute it: this project established that Avatar's `ComputeHash32` is
**CRC-32 (zlib, little-endian)** — the same function `canvas/spawn_builder.py` uses, and the same
one the console DLL uses for archetype lookup, where the key is `crc32(lowercase(name))`.

`mp_stats.json` therefore ships **both** spellings for all 105 names:

```json
{ "name": "headshotKills", "crc32": "...", "crc32_lower": "...", "in_modes": [...] }
```

**Neither spelling collides** across all 105 names — checked, and the check is in
`extract_mp_stats.py` so it stays checked. Either can be used as a lookup key.

> Which of the two the engine actually uses is **not yet confirmed**. The archetype table uses
> lowercase; `CStringID` in general may not. This is a five-minute question to settle against a
> live process — read one known-nonzero stat (`kills`, after a kill) and see which hash finds it.

---

## Getting them out — the options, best first

**1. Hook `CGREventEndGameStatsReceived`.** This is the event the game already fires when the
final numbers are ready, and it is exactly the moment the user described — end of match. It is a
`CGREvent`, so it goes through the game-rules event dispatch the console DLL can already reach.
Cleanest semantics: one callback, complete data, no polling.

**2. Hook the net data containers.** `CPlayerStatRefreshOneNetDataContainer` carries every live
stat change as it happens, and `CPlayerStatsFullNetDataContainer` carries whole-player dumps.
Hooking serialization gives a live feed rather than an end-of-match snapshot — better if the
server wants running scores, and it works on a client that is not the host.

**3. Walk `CGameStatsService` directly and poll.** 192 bytes, reachable from
`CGameModeManager::ms_instance`. Most work, most fragile, but needs no hook at all — and it is the
natural fit for a `mpstats` console command that dumps on demand, matching how `spawn_list` reads
the live archetype table.

For the file itself, the console DLL already writes `console_dump.txt` next to itself via `g_dir`,
so the plumbing for "write a file from the DLL" exists. **JSON keyed by player name + stat name is
the obvious wire format** given the destination is a server.

---

## What is verified, and what is not

**Verified from shipped files:**
* the complete 105-stat schema, inheritance, and every modifier — read straight from the game's XML
* the `data/` copy and the **binary** `ATGE/patch/` copy declare **identical** schemas (all 120
  declarations compared attribute-by-attribute, after decoding the patch one)
* Far Cry 2 declares 179 stats to Avatar's 105; the 79 extras are all per-weapon, and Avatar has
  no per-weapon stat of any kind
* `CGameStatsService` / `CGREventEndGameStatsReceived` / the four net containers exist in Avatar's
  own `Dunia.dll`, at the RTTI addresses listed
* `CGameStatsService` allocates 0xC0 bytes
* stat name strings are **absent** from the binary
* no GameSpy / account / leaderboard / upload code exists in Avatar
* the 105 names hash without collision under CRC-32, both cases

**From Far Cry 2's symbol table, not from Avatar** — same engine, so the *shape* is reliable but
**no address is**:
* the `GetGameModeService` / `GetStatInfo` / `CPlayerStats` method signatures
* `CFCXGameStatsSynchronize`, `UpdateEndOfGameStats`, `CFCXWaitingEndStatsPage` — these are FC2
  classes and **were not found in Avatar**; do not assume they are present

**Not established at all:**
* the byte offsets of the stat map inside `CGameStatsService`
* whether the `CStringID` key is the raw or the lowercased CRC-32
* anything about how many of these stats a **client** sees versus the **host**

Nothing here has been tested against a running game.
