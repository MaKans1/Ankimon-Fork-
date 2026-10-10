# wild: changelog

## Battles
- **Smarter moves on both sides:** buffs, debuffs and status when they help, otherwise the best attack. Your Pokémon uses only the moves you tick in the Buddy menu (click its sprite in the reviewer).
- The battle log shows the move actually used, in its category's colour.
- **No more "survive at 1 HP":** a Pokémon at full HP used to survive any single hit. With team rotation your whole team fights each wild Pokémon, so it's gone.
- **Hidden fair-play rules:**
  - a wild Pokémon can heal at most half its HP per encounter;
  - support moves are limited to two uses per life;

## Team rotation
- When the Pokémon in front faints, the next team member (buddy first, then slots 1-6) comes in against the same wild Pokémon, which keeps its damage. If the whole team is worn out, you hurry away.
- When the encounter ends (win, catch, flee or whiteout), everyone is healed and your buddy is back in front.
- **EXP split:** the final blow earns 50%, the rest is shared between the others who fought; fighting alone earns 100%.
- **Switch In…** in the Buddy menu sends a team member in for this fight only.
- Changing your buddy or team in the middle of a fight (to swap out a fainted Pokémon, say) makes the wild Pokémon flee. Changing it before the first round is fine.
- **Popups:** each wild-battle popup has its own toggle (damage and heals, faints and switches, EXP, level-ups and new moves, catches, the battle log). All are off by default.

## Levels
- **Wild Levels Follow Badges:** wild Pokémon get stronger with the badges you hold in the region you're in, like the routes in Red/Blue, with the odd stronger one. Off: they stay near your Pokémon's level.
- Above a region's level cap your buddy fights at the cap, and the HUD shows the capped level and HP. It still gains EXP and levels for real, and shows its own level again once the cap passes it.
- Baby-evolution species appear at sensible levels (Pikachu, Clefairy…), and big ones like Snorlax and Chansey from Lv 20.

## Travel
- **Game > Travel:** you're always in exactly one region. Only its Pokémon appear in the wild, and its gyms, badges, wild levels and level cap apply. Start anywhere and clear the regions in any order.
- The Travel menu shows each region's badge count.
- **Area Zero** joins the Travel menu once you've cleared an Area Zero expedition (gyms package). It's inside Paldea; its wild Pokémon are the Paradox Pokémon, who no longer appear anywhere else in Paldea.

## Pokédex
- A **registered Pokédex:** every species you've owned stays registered, even after it evolves.
- A region filter and a progress count.
- A **badge** for registering every Pokémon of a region (mythicals not required).

## Rare encounters and evolutions
- Starters appear in the wild about once in 100 encounters, in their home region.
- **Roaming legendaries, mythicals and Mewtwo** (needs the gyms package): very rarely, a powerful Pokémon crosses your path while you review. You're asked whether to battle it: pick three team members for a gym-style battle (auto or manual, as your gym setting), your three against it. Beat it to catch it; say no, or lose, and it flees. No rematches.
  - **Roamers** (about 1 in 150 encounters while one roams your region): Raikou and Entei (after Burned Tower), Latias, Mesprit, Cresselia, Tornadus and Thundurus, and Galarian Articuno, Zapdos and Moltres (after Galar's Champion). They keep their damage between meetings.
  - **Rare roamers** (as rarely as Mewtwo): the other half of a legendary pair you chose on an expedition (Zacian or Zamazenta, Regieleki or Regidrago, Koraidon or Miraidon), while you own your choice; and after Paldea's Champion, Okidogi, Munkidori, Fezandipiti, Ogerpon, Terapagos and Pecharunt.
  - **Mythicals and Mewtwo** (about 1 in 750, once their condition is met - badges and/or particular legendaries, nothing outside the game): Mewtwo (8 Kanto badges, 100 Kanto Pokémon registered), Celebi, Jirachi, Deoxys, Manaphy, Phione, Darkrai, Shaymin, Arceus, Victini, Keldeo, Meloetta, Genesect, Diancie, Hoopa, Volcanion, Zarude (after Galar's Champion).
  - Their level is the top of your wild level range in the region + 12. One of each per save.
  - Your region's Expeditions page says when powerful Pokémon may be in the wild.
- Legendaries can't be knocked out: beat one and you catch it.
- **Kubfu** (Galar, once one has joined you; gyms package): about four times as often as Mewtwo, and more often shiny. It can be found again and again.
- **Herba Mystica** (from Paldea's Titans): eat one from the bag and shiny Pokémon are more likely for your next encounters.
- After fleeing, the next Pokémon is never shiny.
- **Trade evolutions without trading:** Pokémon that evolve by trade (with no item) evolve at Lv 37 with high friendship.

## Alpha spawns
- The odd stronger wild Pokémon can now be up to **12 levels** above the usual range, and is never weak.

## Moves the wild engine can't run
- In wild battles, neither side uses moves the wild engine can't handle properly:
  - two-turn and recharge moves (Fly, Dig, Solar Beam, Hyper Beam…) and lock-in moves (Outrage, Thrash…);
  - Disable, Encore, Yawn, Perish Song, Attract, Torment, Imprison, Embargo, and confusion moves (Confuse Ray, Supersonic, Swagger…).
- The Buddy menu greys them out as "(gyms only)". They still work in gyms, which use the real games' rules.
- If none of a Pokémon's moves are usable, it uses its normal moves.

## Works with
- **gyms:** badge-based wild levels, region level caps, travel to each region's gyms, and expeditions.
- Without this package, the core uses classic wild battles (random moves, no caps, no rotation).
