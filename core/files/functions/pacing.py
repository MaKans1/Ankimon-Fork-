"""
pacing.py - recommended gym intervals and EXP for a daily card goal.

Target: clearing every gym (all regions) and expedition takes about four
months at the player's daily goal, whatever that goal is. So the review
intervals grow with the goal and EXP shrinks with it.

How the numbers were set (2026-10-02):
  Gyms     every gym, Elite Four member and Champion, in every region. Each
           costs one interval; about 0.6 losses per gym, each costing a
           rematch wait (a quarter of the interval), adds ~15%.
           interval = 120 days x goal / (gyms x 1.15)  ->  ~2.4 days of cards
  Rematch  about 0.6 of a day's cards; "Not now" about 0.4.
  EXP      calibrated on real play (about 17 EXP per card around Lv 28,
           1 card per round, x1.0). A team of three then needs ~20,800
           cards per (cards-per-round / multiplier) to reach Lv 62 (Kanto's
           Champion); the multiplier lands that at ~80% of the four months.
           Faster levelling is never wasted - region level caps hold it -
           but it makes gyms trivial; slower means losing to them.
"""

CONTENT_DAYS = 120          # about four months
LOSS_OVERHEAD = 1.15        # expected rematch waits on top of the gym intervals
RETRY_SHARE = 0.6           # rematch wait, in days of cards
DECLINE_SHARE = 0.4         # "Not now" wait, in days of cards
CARDS_TO_LV62 = 20800       # x cards-per-round / multiplier (see above)
LEVEL_BY = 0.8              # reach that by 80% of the content period
FALLBACK_GYMS = 44          # if the gym package isn't installed

PACED_KEYS = ("gym.reviews_per_gym", "gym.retry_cost_reviews",
              "gym.decline_cooldown_reviews", "battle.defeat_xp_multiplier")


def gym_count() -> int:
    try:
        from ..gym import gym_data
        return max(1, sum(len(v) for v in gym_data.LADDERS.values()))
    except Exception:
        return FALLBACK_GYMS


def cards_per_round(value) -> float:
    """'2' -> 2, '1-3' -> 2 (the average)."""
    try:
        s = str(value).strip()
        if "-" in s:
            a, b = (float(x) for x in s.split("-", 1))
            return max(1.0, (a + b) / 2)
        return max(1.0, float(s))
    except (TypeError, ValueError):
        return 2.0


def _round(x: float) -> int:
    step = 50 if x >= 500 else (25 if x >= 100 else 10)
    return int(max(step, round(x / step) * step))


def recommended(goal, cpr=2) -> dict:
    """{setting key: recommended value} for a daily card goal."""
    try:
        g = max(10, min(5000, int(float(str(goal).strip()))))
    except (TypeError, ValueError):
        g = 100
    c = cards_per_round(cpr)
    days_per_gym = CONTENT_DAYS / (gym_count() * LOSS_OVERHEAD)
    xp = CARDS_TO_LV62 * c / (LEVEL_BY * CONTENT_DAYS * g)
    return {
        "gym.reviews_per_gym": _round(days_per_gym * g),
        "gym.retry_cost_reviews": _round(RETRY_SHARE * g),
        "gym.decline_cooldown_reviews": _round(DECLINE_SHARE * g),
        "battle.defeat_xp_multiplier": round(max(0.1, min(10.0, xp)), 2),
    }


def hint(key, goal, cpr=2) -> str:
    """The line shown under a paced setting."""
    rec = recommended(goal, cpr).get(key)
    if rec is None:
        return ""
    try:
        g = int(float(str(goal).strip()))
    except (TypeError, ValueError):
        g = 100
    return "For your goal of %d cards a day, recommended: %s" % (g, rec)
