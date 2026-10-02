"""
expedition_data.py - the legendary bird expeditions (Red/Blue dungeons),
Kanto only. The other regions' expeditions are in expedition_regions.py.

Each expedition is three floors of defenders, then the legendary. All three
birds unlock at 5 badges and are level 50 (in Red/Blue Zapdos and Articuno
needed Surf - usable with Koga's Soul Badge - and all three birds are Lv 50).

Defender species are the ones found in those dungeons in Red/Blue; levels are
set for a team that has just earned its fifth badge. Movesets are chosen from
each species' real level-up moves at that level (Modernized); the bird's
Red/Blue set is used with Settings > Gym Moveset: Original.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from .gym_data import GymMon

BIRD_LEVEL = 50
BIRD_BADGES = 5


@dataclass
class Floor:
    name: str
    foes: List[GymMon]
    cash: int = 300
    boss: bool = False


@dataclass
class Expedition:
    key: str
    name: str
    legendary: str
    legendary_id: int
    badges_needed: int
    blurb: str
    floors: List[Floor] = field(default_factory=list)
    region: str = "Kanto"       # you must be here, with this region's badges

    @property
    def boss(self) -> Optional[Floor]:
        return next((f for f in self.floors if f.boss), None)


EXPEDITIONS: List[Expedition] = [
    Expedition(
        "power_plant", "Power Plant", "Zapdos", 145, BIRD_BADGES,
        "An abandoned power plant off Route 10. Electric types everywhere, and "
        "the Electrode in the generator core like to explode. Ground types "
        "and something bulky will carry you; Zapdos hits hard and flies.",
        [Floor("Outer Halls",
               [GymMon("Magnemite", 36, ["Discharge", "Flash Cannon", "Thunder Wave", "Screech"]),
                GymMon("Voltorb", 36, ["Spark", "Electro Ball", "Swift", "Screech"]),
                GymMon("Pikachu", 36, ["Thunderbolt", "Iron Tail", "Quick Attack", "Thunder Wave"])],
               cash=300),
         Floor("Turbine Room",
               [GymMon("Magneton", 39, ["Electro Ball", "Flash Cannon", "Tri Attack", "Thunder Wave"]),
                GymMon("Electabuzz", 40, ["Thunder Punch", "Low Kick", "Discharge", "Screech"])],
               cash=400),
         Floor("Generator Core",
               [GymMon("Electrode", 43, ["Discharge", "Swift", "Light Screen", "Self-Destruct"]),
                GymMon("Electrode", 43, ["Electro Ball", "Charge Beam", "Screech", "Self-Destruct"])],
               cash=500),
         Floor("Zapdos",
               [GymMon("Zapdos", BIRD_LEVEL, ["Discharge", "Drill Peck", "Roost", "Agility"],
                       rb_moves=["Thunder Shock", "Drill Peck"])],
               cash=0, boss=True)]),

    Expedition(
        "seafoam", "Seafoam Islands", "Articuno", 144, BIRD_BADGES,
        "Twin islands hollowed into freezing caves and fast currents. Water "
        "and Psychic types guard the way down; Electric and Grass help, and "
        "Fire or Rock make short work of Articuno.",
        [Floor("Upper Caves",
               [GymMon("Seel", 36, ["Aurora Beam", "Aqua Jet", "Icy Wind", "Encore"]),
                GymMon("Golbat", 36, ["Poison Fang", "Air Cutter", "Bite", "Supersonic"]),
                GymMon("Slowpoke", 37, ["Water Pulse", "Zen Headbutt", "Yawn", "Slack Off"])],
               cash=300),
         Floor("Rushing Currents",
               [GymMon("Dewgong", 39, ["Aurora Beam", "Brine", "Aqua Jet", "Rest"]),
                GymMon("Kingler", 39, ["Razor Shell", "Hammer Arm", "Metal Claw", "Mud Shot"])],
               cash=400),
         Floor("Frozen Depths",
               [GymMon("Slowbro", 42, ["Surf", "Psychic", "Slack Off", "Amnesia"]),
                GymMon("Golduck", 42, ["Hydro Pump", "Zen Headbutt", "Aqua Tail", "Screech"]),
                GymMon("Dewgong", 43, ["Aurora Beam", "Brine", "Take Down", "Icy Wind"])],
               cash=500),
         Floor("Articuno",
               [GymMon("Articuno", BIRD_LEVEL, ["Ice Beam", "Ancient Power", "Roost", "Agility"],
                       rb_moves=["Peck", "Ice Beam"])],
               cash=0, boss=True)]),

    Expedition(
        "victory_road", "Victory Road", "Moltres", 146, BIRD_BADGES,
        "The boulder-strewn cave before the Pokémon League. Fighting and Rock "
        "types hit hard - Water, Grass and Psychic are your friends. Moltres "
        "waits near the top; Rock and Water types are the answer.",
        [Floor("Boulder Halls",
               [GymMon("Machoke", 37, ["Vital Throw", "Knock Off", "Low Sweep", "Scary Face"]),
                GymMon("Graveler", 37, ["Rock Blast", "Bulldoze", "Rock Polish", "Self-Destruct"]),
                GymMon("Golbat", 37, ["Poison Fang", "Air Cutter", "Bite", "Supersonic"])],
               cash=300),
         Floor("Cliff Ledges",
               [GymMon("Onix", 40, ["Rock Slide", "Dragon Breath", "Slam", "Rock Polish"]),
                GymMon("Marowak", 40, ["Bone Rush", "Stomping Tantrum", "Headbutt", "Focus Energy"])],
               cash=400),
         Floor("Summit Cave",
               [GymMon("Machoke", 43, ["Vital Throw", "Knock Off", "Bulk Up", "Low Sweep"]),
                GymMon("Venomoth", 43, ["Bug Buzz", "Psybeam", "Sleep Powder", "Quiver Dance"]),
                GymMon("Graveler", 43, ["Earthquake", "Rock Blast", "Rock Polish", "Self-Destruct"])],
               cash=500),
         Floor("Moltres",
               [GymMon("Moltres", BIRD_LEVEL, ["Heat Wave", "Air Slash", "Roost", "Agility"],
                       rb_moves=["Peck", "Fire Spin"])],
               cash=0, boss=True)]),
]


# One per other region (proof of concept), where a legendary fits the early game.
from .expedition_regions import REGION_EXPEDITIONS  # noqa: E402
EXPEDITIONS += REGION_EXPEDITIONS


def get(key) -> Optional[Expedition]:
    return next((e for e in EXPEDITIONS if e.key == key), None)
