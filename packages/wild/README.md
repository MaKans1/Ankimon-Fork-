# wild

Smarter wild battles and exploration.

- `wild/wild_rules.py`: wild levels by badges, level caps, team rotation and the EXP split, rare encounters, and the trade-evolution rule.
- `wild/wild_ai.py`: move choice for both sides.
- `wild/wild_menus.py`: Game > Travel, the Buddy menu (moves, switch-in, flee), and Expeditions.
- `wild/dex.py`: the registered Pokédex and region badges.
- `user_files/sprites/badges/68-76.png`: the region badges.

Works on its own: wild levels stay near your Pokémon's level and there are no level caps. With **gyms**, wild levels follow your badges and each region has its own cap.

Without this package, the core uses `functions/wild_fallback.py`: classic random-move wild battles.
