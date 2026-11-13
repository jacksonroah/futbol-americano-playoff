"""Pull the ESPN league and write site/data.js for the playoff simulator page.

Run: python3 fetch.py   (league must be public, or add espn_s2/SWID cookies)
"""
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

LEAGUE_ID = 1323188
SEASON = 2026
BASE = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{SEASON}/segments/0/leagues/{LEAGUE_ID}"
OUT = Path(__file__).parent / "site" / "data.js"

raw = json.load(urlopen(f"{BASE}?view=mSettings&view=mTeam&view=mStandings&view=mSchedule&view=mMatchupScore"))
sched = raw["settings"]["scheduleSettings"]
reg_weeks = sched["matchupPeriodCount"]

# The simulator only implements: one division, one-week matchups, record first, then points for.
assert len(sched["divisions"]) == 1, f"divisions not supported: {sched['divisions']}"
assert sched["matchupPeriodLength"] == 1, "multi-week matchups not supported"
assert sched["playoffSeedingRule"] == "TOTAL_POINTS_SCORED", sched["playoffSeedingRule"]

regular = [m for m in raw["schedule"] if m["matchupPeriodId"] <= reg_weeks]
played = [m for m in regular if m["winner"] != "UNDECIDED"]
remaining = sorted((m for m in regular if m["winner"] == "UNDECIDED"), key=lambda m: (m["matchupPeriodId"], m["id"]))
through = max(m["matchupPeriodId"] for m in played)

# --- Method: season scoring average --------------------------------------------------------
# Season average pulled toward the league average by an amount estimated from the data
# (empirical Bayes). One shared weekly SD.
scores = {t["id"]: [] for t in raw["teams"]}
for m in played:
    for side in ("home", "away"):
        scores[m[side]["teamId"]].append(m[side]["totalPoints"])
n_games = statistics.mean(len(s) for s in scores.values())
avg = {tid: statistics.mean(s) for tid, s in scores.items()}
league_avg = statistics.mean(avg.values())
within_var = statistics.mean(statistics.variance(s) for s in scores.values())
talent_var = max(statistics.variance(avg.values()) - within_var / n_games, 0)
keep = talent_var / (talent_var + within_var / n_games)
season_mean = {tid: league_avg + keep * (a - league_avg) for tid, a in avg.items()}
season_sd = math.sqrt(within_var)

# --- Method: ESPN projections, best legal lineup --------------------------------------------
# Scoring slots from league settings (20 = bench, 21 = IR don't score).
slots = {int(s): n for s, n in raw["settings"]["rosterSettings"]["lineupSlotCounts"].items() if n and int(s) not in (20, 21)}


def projected(player, week):
    return next(
        (s["appliedTotal"] for s in player["stats"]
         if s["seasonId"] == SEASON and s["statSourceId"] == 1 and s["statSplitTypeId"] == 1 and s["scoringPeriodId"] == week),
        0.0,
    )


def best_lineup(players, week):
    """Highest projected total for a legal lineup. Fills the slots with the fewest eligible
    players first (QB, K, D/ST, TE...) so FLEX gets the best player left over."""
    pool = sorted(players, key=lambda p: -projected(p, week))
    used, total = set(), 0.0
    for slot in sorted(slots, key=lambda s: sum(s in p["eligibleSlots"] for p in players)):
        for _ in range(slots[slot]):
            pick = next((p for p in pool if p["id"] not in used and slot in p["eligibleSlots"]), None)
            if pick:
                used.add(pick["id"])
                total += projected(pick, week)
    return total


# Calibrate on completed weeks: how far actual scores landed from the best-lineup projection.
residuals = []
for week in range(1, through + 1):
    box = json.load(urlopen(f"{BASE}?view=mBoxscore&view=mMatchupScore&scoringPeriodId={week}"))
    for m in box["schedule"]:
        if m["matchupPeriodId"] == week:
            for side in ("home", "away"):
                entries = m[side]["rosterForCurrentScoringPeriod"]["entries"]
                players = [e["playerPoolEntry"]["player"] for e in entries]
                residuals.append(m[side]["totalPoints"] - best_lineup(players, week))
proj_bias = statistics.mean(residuals)
proj_sd = statistics.stdev(residuals)

# Current rosters, projected for each remaining week (ESPN zeroes byes, IR and players ruled out).
proj_mean = {}
for week in range(through + 1, reg_weeks + 1):
    rosters = json.load(urlopen(f"{BASE}?view=mRoster&scoringPeriodId={week}"))
    for t in rosters["teams"]:
        players = [e["playerPoolEntry"]["player"] for e in t["roster"]["entries"]]
        proj_mean[t["id"], week] = best_lineup(players, week) + proj_bias


def method_games(mean, sd):
    return [
        {
            "home": round(mean(m["home"]["teamId"], m["matchupPeriodId"]), 2),
            "away": round(mean(m["away"]["teamId"], m["matchupPeriodId"]), 2),
            # P(home outscores away) when both scores are Normal(mean, sd)
            "pHome": round(0.5 * (1 + math.erf((mean(m["home"]["teamId"], m["matchupPeriodId"]) - mean(m["away"]["teamId"], m["matchupPeriodId"])) / (2 * sd))), 4),
        }
        for m in remaining
    ]


methods = [
    {
        "id": "espn",
        "name": "ESPN projections, best lineup",
        "about": (
            "Each week, every team starts its highest-projected legal lineup from ESPN's player projections. "
            "ESPN projects players on bye, on IR or ruled out at 0 and brings injured players back when it expects them to return."
        ),
        "sd": round(proj_sd, 2),
        "games": method_games(lambda tid, wk: proj_mean[tid, wk], proj_sd),
    },
    {
        "id": "season",
        "name": "Season scoring average",
        "about": (
            f"Each team's season scoring average, pulled {round(100 * (1 - keep))}% of the way toward the league average of {league_avg:.1f}, "
            f"because after {through} games that share of the gap between teams is estimated to be luck. "
            "It does not know about trades, injuries or byes."
        ),
        "sd": round(season_sd, 2),
        "games": method_games(lambda tid, wk: season_mean[tid], season_sd),
    },
    {
        "id": "coin",
        "name": "Coin flip",
        "about": "Every remaining game is 50/50. This shows what the current records and schedule alone imply.",
        "sd": round(season_sd, 2),
        "games": method_games(lambda tid, wk: league_avg, season_sd),
    },
]

teams = sorted(raw["teams"], key=lambda t: t["playoffSeed"])
data = {
    "league": raw["settings"]["name"],
    "season": SEASON,
    "pulled": datetime.now(timezone.utc).isoformat(timespec="minutes"),
    "throughWeek": through,
    "regularSeasonWeeks": reg_weeks,
    "playoffTeams": sched["playoffTeamCount"],
    "teams": [
        {
            "id": t["id"],
            "name": t["name"],
            "abbrev": t["abbrev"],
            "wins": t["record"]["overall"]["wins"],
            "losses": t["record"]["overall"]["losses"],
            "ties": t["record"]["overall"]["ties"],
            "pf": round(t["record"]["overall"]["pointsFor"], 2),
        }
        for t in teams
    ],
    "games": [{"week": m["matchupPeriodId"], "home": m["home"]["teamId"], "away": m["away"]["teamId"]} for m in remaining],
    "methods": methods,
}

OUT.write_text("window.LEAGUE = " + json.dumps(data, indent=1) + ";\n")

print(f"{data['league']}: through week {through} of {reg_weeks}, {len(remaining)} games left")
print(f"season avg: league {league_avg:.1f}, weekly SD {season_sd:.1f}, keep {keep:.0%} of each team's gap")
print(f"ESPN best lineup: actual - projected = {proj_bias:+.1f} on average, SD {proj_sd:.1f} ({len(residuals)} team-weeks)\n")
weeks_left = range(through + 1, reg_weeks + 1)
print(f"{'':>5} {'rec':<6} {'avg':>6} {'season':>7} {'ESPN/wk':>8}   ESPN by week {list(weeks_left)}")
for t in data["teams"]:
    by_week = [proj_mean[t["id"], w] for w in weeks_left]
    print(f"{t['abbrev']:>5} {t['wins']}-{t['losses']:<4} {avg[t['id']]:6.1f} {season_mean[t['id']]:7.1f} {statistics.mean(by_week):8.1f}   "
          + " ".join(f"{p:5.1f}" for p in by_week) + f"  {t['name']}")
print(f"\nwrote {OUT}")
