# Ankimon 2.0

A fan-made overhaul of [Ankimon](https://ankiweb.net/shared/info/1908235722), the Anki add-on that turns your reviews into a Pokémon adventure. Ankimon 2.0 adds gym ladders in all nine regions, travel between regions, smarter wild battles, legendary expeditions, and a progression curve built to last months at your own daily card goal.

It's split into a **core** (general patches: fixes and quality-of-life changes) and three optional **packages** for the big systems, so you can install only what you want. Each one has a README and a CHANGELOG:
[core](core/CHANGELOG.md) · [gyms](packages/gyms/CHANGELOG.md) · [wild](packages/wild/CHANGELOG.md) · [showdown](packages/showdown/CHANGELOG.md)

| Part | What it adds | Needs |
|---|---|---|
| **core** | Ankimon 2.03 plus the 2.0 fixes and quality-of-life changes (always installed) | – |
| **gyms** | Gym ladders in every region, badges, level caps, legendary expeditions | – (better with showdown, wild) |
| **wild** | Smarter wild battles, wild levels that follow your badges, team rotation, travel, a registered Pokédex | – (better with gyms) |
| **showdown** | Gym and expedition battles use Pokémon Showdown's simulator, so every move, ability and item follows the real games' rules | gyms |

## Install

1. Download **Ankimon-2.0.ankiaddon** from the [Releases](../../releases) page.
2. Double-click it, or in Anki use Tools > Add-ons > Install from file. If you already have Ankimon, Anki asks to replace it. Your Pokémon, items and progress are kept.
3. Restart Anki.

The first time a gym battle starts, Ankimon offers a one-time download (about 40 MB) so gyms follow the real games' battle rules. Choose "Not now" and gyms use the built-in engine.

### Only want some of it?
1. Install **Ankimon-2.0-core.ankiaddon** instead of the full file.
2. For each package you want, download its zip (`Ankimon-2.0-gyms.zip`, `-wild.zip`, `-showdown.zip`) and unzip it.
3. In Anki, open Tools > Add-ons, select Ankimon and click **View Files**. Drag the unzipped contents into that folder.
4. Restart Anki.

showdown needs gyms.

### Updates
Anki won't offer to "update" back to the official 2.03 on AnkiWeb, because 2.0 counts as newer. If Ankimon's authors later publish a newer version on AnkiWeb, Anki will offer it, and accepting would replace 2.0 (your save is kept).

## Set your daily goal first

Settings > Study > **Goal of Daily Average Cards**. The gym intervals and EXP are tuned so clearing every gym and expedition takes about four months at your goal, whether that's 100 cards a day or 1,000. Change the goal and the recommended values are filled in for you; each setting shows "For your goal of N cards a day, recommended: X". You can still adjust them.

## What's in each part

### Core
- Real Pokémon names everywhere (Iron Hands, Mr. Mime, Farfetch'd, Nidoran♀), and "Pokémon" spelled the same way throughout.
- Item and Pokédex descriptions use the newest games' text, so no more "POKéMON".
- Move descriptions match Ankimon's one-on-one battles. Howl "Raises the user's Attack by 1"; moves that need a partner say they fail. Only the text changes, not the mechanics.
- Item bag rework:
  - Item info on hover.
  - Heals, cures, revives and X items work.
  - Evolution items list only the Pokémon they apply to; ones too low-level for it are greyed out.
  - TMs have a proper teach screen.
  - Optional level gate for evolution items.
- Pokémon PC:
  - Search by name, nickname or type word ("fire").
  - Stable sorting.
  - A **Can evolve** filter.
  - Enter in the search box only searches.
- Catch upgrades: catching a better copy of a species you own replaces yours instead of piling up duplicates.
- Settings:
  - Short, plain descriptions.
  - Pacing recommendations by daily goal.
  - Settings that no longer did anything are retired.
- The Mart always stocks basic healing items, and there's no daily cash cap.

### gyms
- **Kanto:** the exact Red/Blue ladder (8 gyms, the Elite Four, the Champion) with the leaders' real teams and levels.
- **Johto, Hoenn, Sinnoh, Unova, Kalos, Alola, Galar and Paldea:** the first 3-4 gyms of each region, rosters from the original games.
- **Movesets:** a balanced "Modernized" set by default, or each leader's moves from the original games (setting).
- **Badges and level caps:** each region has its own badges and its own review count toward its next gym; travelling pauses it. In each region your Pokémon fight at no higher than the next leader's ace + 5. They keep their real level, and badges raise the cap.
- **Expeditions:** three floors of trainers' Pokémon, then a legendary; beat it to catch it. Damage carries between floors, and you can use items between them.
  - Kanto: Zapdos, Articuno and Moltres.
  - One more each in Johto (Entei), Hoenn (Regirock), Sinnoh (Azelf), Unova (Virizion), Alola (Tapu Koko) and Paldea (Wo-Chien).
- **Badge case** with art for every badge.
- **Without wild:** gyms are Kanto-only and expeditions can't be opened, because travel and the Expeditions menu live in the wild package.

### wild
- **Smarter moves:** both sides choose moves sensibly (buffs, status, the right attack). Your Pokémon uses only the moves you tick in the Buddy menu.
- **Levels:** wild levels follow your badges like the routes in Red/Blue, with the odd stronger Pokémon. Above a region's level cap, your buddy fights at the cap and the HUD shows it.
- **Team rotation:** when your buddy faints, your team steps in against the same wild Pokémon. EXP is split: 50% to the final blow, the rest shared. Changing your team mid-fight makes the wild Pokémon flee.
- **Travel** (Game > Travel): one region at a time. Only its Pokémon appear, and each region keeps its own gym progress.
- **Registered Pokédex** with a region filter, plus a badge for completing each region's Pokédex.
- **Rare encounters:** starters (1%), and Mewtwo once you've earned it.
- **Evolutions:** trade evolutions happen at Lv 37 with high friendship.
- **Popups:** every wild-battle popup can be switched on or off; all are off by default.

### showdown
Gym and expedition fights run on [Pokémon Showdown](https://github.com/smogon/pokemon-showdown)'s simulator (via [@pkmn/sim](https://github.com/pkmn/ps)). Abilities, items, weather, screens, sleep turns and two-turn moves all behave as in the main games. If the helper is missing or fails, the fight falls back to the built-in engine automatically.

## Repository layout

```
core/
    README.md, CHANGELOG.md    the general patches
    files/                     the add-on core (always installed)
packages/<name>/               gyms, wild, showdown
    README.md, CHANGELOG.md    what it adds, what changed
    package.json               what it needs
    files/                     laid out like the add-on folder; build.py copies it in
build.py                       maintainers: python build.py -> dist/release (the files for a GitHub release)
```

## Credits and license

- **Ankimon** by Unlucky-Life and h0tp, licensed GPL-3.0. Ankimon 2.0 is a modified version under the same license (see `LICENSE`).
- **Pokémon Showdown** (MIT) by the Smogon team, and **@pkmn/sim** (MIT) by pkmn. Both are downloaded by the setup script, not included here.
- **Gym rosters** come from the original games, via the pret disassemblies (pokered, pokecrystal, pokeruby) and published references for later generations.
- Pokémon and all related names are trademarks of Nintendo, Creatures Inc. and GAME FREAK inc. This is an unofficial fan project, not affiliated with or endorsed by them or by the Ankimon authors.
