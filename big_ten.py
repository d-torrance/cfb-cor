"""Big Ten championship game scenarios.

For each Big Ten team, work out whether it controls its own destiny, is
eliminated, or needs help (and what help) to finish in the top two of the
conference standings.

Tiebreakers follow the Big Ten procedures in use since the 2024 season:

  Two teams:  head-to-head; record vs. common conference opponents; record
              vs. common opponents in order of finish; combined conference
              record of all conference opponents; SportSource Analytics
              ranking; random draw.
  3+ teams:   head-to-head if all played each other (otherwise a team that
              beat/lost to all the others advances/is eliminated); then the
              same steps as above.  Whenever teams are separated, each
              remaining group starts the procedure over (two-team rules if
              only two remain).

The last two steps can't be computed, so ties that survive the others are
reported as depending on the SportSource ranking.
"""

import itertools

from sympy import symbols, true
from sympy.logic import SOPform
from sympy.logic.boolalg import And, Not, Or

CONFERENCE = "Big Ten"
SPOTS = 2
NODE_BUDGET = 50000
MUST_WIN_BUDGET = 20000
MAX_ENUMERATED_GAMES = 14

IN = "in"
OUT = "out"
TOSSUP = "tossup"
# decided by the tiebreakers that look at the rest of the standings, which
# depend on games between teams that are out of the race
DEEP = "deep"
MAX_TERMS = 6
MAX_EXACT_TAIL = 10


class Unknown(Exception):
    """Search ran out of budget before finding an answer."""


def fetch_games(api_instance, year, week=None):
    games = api_instance.get_games(year=year, season_type="regular",
                                   conference="B1G")
    played = []
    remaining = []
    for game in games:
        if (not game.conference_game or
            game.home_conference != CONFERENCE or
            game.away_conference != CONFERENCE or
            "Championship" in (game.notes or "")):
            continue
        home = game.home_team
        away = game.away_team
        if (game.completed and isinstance(game.home_points, int) and
            isinstance(game.away_points, int) and
            game.home_points != game.away_points and
            (week is None or game.week <= week)):
            if game.home_points > game.away_points:
                played.append((home, away))
            else:
                played.append((away, home))
        else:
            remaining.append((home, away))
    return played, remaining


def win_pct(wins, losses):
    if wins + losses == 0:
        return 0.0
    return wins / (wins + losses)


class Season:
    """Standings and tiebreakers for one set of results.

    The results may be partial as long as every team that can still reach
    the cutoff has finished its schedule.  In that case, check the deep
    flag afterwards: it's set if the answer depended on the tiebreakers
    that look at the rest of the standings."""

    def __init__(self, teams, results):
        self.teams = teams
        self.deep = False
        self._standings = None
        self.wins = dict.fromkeys(teams, 0)
        self.losses = dict.fromkeys(teams, 0)
        self.beat = {}  # (winner, loser) -> number of wins
        self.opponents = {team: [] for team in teams}
        for winner, loser in results:
            self.wins[winner] += 1
            self.losses[loser] += 1
            self.beat[(winner, loser)] = self.beat.get((winner, loser), 0) + 1
            self.opponents[winner].append(loser)
            self.opponents[loser].append(winner)

    def record_vs(self, team, opponents):
        wins = sum(self.beat.get((team, opp), 0) for opp in opponents)
        losses = sum(self.beat.get((opp, team), 0) for opp in opponents)
        return win_pct(wins, losses)

    def standings(self):
        """Teams grouped by conference wins, best first.  Everyone plays the
        same number of conference games, so this matches win percentage."""
        if self._standings is None:
            groups = {}
            for team in self.teams:
                groups.setdefault(self.wins[team], []).append(team)
            self._standings = [groups[wins]
                               for wins in sorted(groups, reverse=True)]
        return self._standings

    def common_opponents(self, tied):
        common = set(self.opponents[tied[0]])
        for team in tied[1:]:
            common &= set(self.opponents[team])
        return common - set(tied)

    def head_to_head(self, tied):
        if len(tied) == 2:
            a, b = tied
            return {a: self.record_vs(a, [b]), b: self.record_vs(b, [a])}
        if all(a in self.opponents[b] for a, b in
               itertools.combinations(tied, 2)):
            return {team: self.record_vs(team, [t for t in tied if t != team])
                    for team in tied}
        # not a full round robin: only beating (or losing to) everyone counts
        key = {}
        for team in tied:
            others = [t for t in tied if t != team]
            if all(self.beat.get((team, t), 0) and
                   not self.beat.get((t, team), 0) for t in others):
                key[team] = 1
            elif all(self.beat.get((t, team), 0) and
                     not self.beat.get((team, t), 0) for t in others):
                key[team] = -1
            else:
                key[team] = 0
        return key

    def common_record(self, tied):
        common = self.common_opponents(tied)
        return {team: self.record_vs(team, common) for team in tied}

    def ordered_common_record(self, tied):
        common = self.common_opponents(tied)
        for group in self.standings():
            group = [opp for opp in group if opp in common]
            if not group:
                continue
            key = {team: self.record_vs(team, group) for team in tied}
            if len(set(key.values())) > 1:
                return key
        return dict.fromkeys(tied, 0)

    def opponent_strength(self, tied):
        key = {}
        for team in tied:
            wins = sum(self.wins[opp] for opp in self.opponents[team])
            losses = sum(self.losses[opp] for opp in self.opponents[team])
            key[team] = win_pct(wins, losses)
        return key

    def break_tie(self, tied, spots):
        """Order tied teams competing for the given number of spots; returns
        a list of groups, best first.  Groups are only split as far as
        needed to fill the spots."""
        if len(tied) <= spots or spots <= 0:
            return [tied]
        for step in (self.head_to_head, self.common_record,
                     self.ordered_common_record, self.opponent_strength):
            if step in (self.ordered_common_record, self.opponent_strength):
                self.deep = True
            key = step(tied)
            if len(set(key.values())) > 1:
                result = []
                for value in sorted(set(key.values()), reverse=True):
                    bucket = [team for team in tied if key[team] == value]
                    result += self.break_tie(bucket, spots)
                    spots -= len(bucket)
                return result
        return [tied]

    def status(self):
        """Map each team to IN, OUT, or TOSSUP (unresolved at the cutoff)."""
        result = dict.fromkeys(self.teams, OUT)
        spots = SPOTS
        for group in self.standings():
            if spots <= 0:
                break
            if len(group) <= spots:
                for team in group:
                    result[team] = IN
                spots -= len(group)
                continue
            for subgroup in self.break_tie(group, spots):
                if spots <= 0:
                    break
                if len(subgroup) <= spots:
                    for team in subgroup:
                        result[team] = IN
                else:
                    for team in subgroup:
                        result[team] = TOSSUP
                spots -= len(subgroup)
            break
        return result


class Scenarios:
    def __init__(self, played, remaining):
        self.played = played
        self.remaining = remaining
        self.teams = sorted({team for game in played + remaining
                             for team in game})
        self.wins = dict.fromkeys(self.teams, 0)
        self.losses = dict.fromkeys(self.teams, 0)
        for winner, loser in played:
            self.wins[winner] += 1
            self.losses[loser] += 1
        self.left = dict.fromkeys(self.teams, 0)
        for home, away in remaining:
            self.left[home] += 1
            self.left[away] += 1

    def season(self, outcome):
        """outcome: list of winners (or None if undecided), one per
        remaining game."""
        results = self.played + [
            (winner, away if winner == home else home)
            for (home, away), winner in zip(self.remaining, outcome)
            if winner is not None]
        return Season(self.teams, results)

    def evaluate(self, outcome):
        return self.season(outcome).status()

    def exists(self, team, want, fixed=None, cap=None, budget=NODE_BUDGET):
        """Is there an outcome of the remaining games in which team's status
        is in want?  fixed maps game index -> winner; cap maps a team to the
        most additional games it may lose, apart from the fixed ones."""
        fixed = fixed or {}
        cap = cap or {}
        hoping_in = IN in want or TOSSUP in want
        n = len(self.remaining)
        best = {t: self.wins[t] + self.left[t] for t in self.teams}
        order = sorted(
            range(n),
            key=lambda i: (team not in self.remaining[i],
                           -max(best[t] for t in self.remaining[i])))
        wins = dict(self.wins)
        left = dict(self.left)
        lost = dict.fromkeys(self.teams, 0)
        outcome = [None] * n
        nodes = [0]

        def choices(i):
            home, away = self.remaining[i]
            if i in fixed:
                return [fixed[i]]
            if team in (home, away):
                other = away if team == home else home
                return [team, other] if hoping_in else [other, team]
            # try the more dangerous team losing first when hoping to get in
            if (best[home] >= best[away]) == hoping_in:
                return [away, home]
            return [home, away]

        def search(depth):
            nodes[0] += 1
            if nodes[0] > budget:
                raise Unknown()
            low = wins[team]
            high = wins[team] + left[team]
            above = sum(1 for t in self.teams
                        if t != team and wins[t] > high)
            if above >= SPOTS:
                return OUT in want
            threats = sum(1 for t in self.teams
                          if t != team and wins[t] + left[t] >= low)
            if threats < SPOTS:
                return IN in want
            if depth == n:
                return self.evaluate(outcome)[team] in want
            # if only games between teams that can't catch us are left, they
            # can only matter through the deeper tiebreakers; unless there
            # are few enough to go through, call that DEEP
            if left[team] == 0 and all(wins[t] + left[t] < low
                                       for t in self.teams if left[t]):
                season = self.season(outcome)
                status = season.status()
                if not season.deep:
                    return status[team] in want
                if n - depth > MAX_EXACT_TAIL:
                    return DEEP in want
            i = order[depth]
            home, away = self.remaining[i]
            for winner in choices(i):
                loser = away if winner == home else home
                if (i not in fixed and loser in cap and
                    lost[loser] >= cap[loser]):
                    continue
                outcome[i] = winner
                wins[winner] += 1
                left[home] -= 1
                left[away] -= 1
                if i not in fixed:
                    lost[loser] += 1
                found = search(depth + 1)
                wins[winner] -= 1
                left[home] += 1
                left[away] += 1
                if i not in fixed:
                    lost[loser] -= 1
                outcome[i] = None
                if found:
                    return True
            return False

        return search(0)

    def games_of(self, team):
        return [i for i, game in enumerate(self.remaining) if team in game]

    def record(self, team):
        return f"{self.wins[team]}-{self.losses[team]}"

    def describe(self, team):
        mine = self.games_of(team)
        win_out = {i: team for i in mine}

        try:
            if not self.exists(team, {OUT, TOSSUP, DEEP}):
                return "clinched a spot in the championship game"
        except Unknown:
            pass
        try:
            if not self.exists(team, {OUT, TOSSUP, DEEP}, win_out):
                return "controls its own destiny"
            if not self.exists(team, {OUT, TOSSUP}, win_out):
                return ("controls its own destiny, unless it ends up in a "
                        "tie that goes deep into the tiebreakers")
        except Unknown:
            pass
        try:
            if not self.exists(team, {IN, TOSSUP, DEEP}):
                return "eliminated"
            if not self.exists(team, {IN}):
                return ("can only get in through a tie that goes deep into "
                        "the tiebreakers")
        except Unknown:
            pass

        must_beat = []
        for i in mine:
            home, away = self.remaining[i]
            other = away if team == home else home
            try:
                if not self.exists(team, {IN, TOSSUP, DEEP}, {i: other},
                                   budget=MUST_WIN_BUDGET):
                    must_beat.append(other)
            except Unknown:
                pass
        if must_beat and len(must_beat) == len(mine):
            parts = ["must win out"]
        elif must_beat:
            parts = ["must beat " + ", ".join(must_beat)]
        else:
            parts = []
        prefix = "needs" if len(must_beat) == len(mine) else \
            "if it wins out, needs"
        parts.append(prefix + ": " + self.help_needed(team, win_out))
        return "; ".join(parts)

    def help_needed(self, team, win_out):
        final = self.wins[team] + self.left[team]
        threats = {t for t in self.teams if t != team and
                   self.wins[t] + self.left[t] >= final}
        variables = [i for i, (home, away) in enumerate(self.remaining)
                     if i not in win_out and (home in threats or
                                              away in threats)]
        if len(variables) > MAX_ENUMERATED_GAMES:
            return self.help_summary(team, win_out)

        # hold everything else fixed: the home team wins
        base = [home for home, away in self.remaining]
        for i, winner in win_out.items():
            base[i] = winner
        in_rows = []
        other_rows = []  # SportSource ranking or deeper tiebreakers
        for bits in itertools.product([0, 1], repeat=len(variables)):
            outcome = list(base)
            for i, bit in zip(variables, bits):
                home, away = self.remaining[i]
                outcome[i] = home if bit else away
            season = self.season(outcome)
            status = season.status()[team]
            if status == TOSSUP or (status != OUT and season.deep):
                other_rows.append(list(bits))
            elif status == IN:
                in_rows.append(list(bits))

        if not in_rows:
            if other_rows:
                return "help from others, and then a tie that goes deep " \
                    "into the tiebreakers"
            return "help from others (only paths involve losing a game)"
        syms = symbols(f"g0:{len(variables)}")
        expr = SOPform(syms, in_rows, other_rows)
        if expr == true:
            text = "nothing specific, just to win the tiebreakers"
        else:
            if isinstance(expr, Or) and len(expr.args) > MAX_TERMS:
                return self.help_summary(team, win_out)
            text = self.render(expr, dict(zip(syms, variables)), top=True)
        if other_rows:
            text += " (some of these also come down to deeper tiebreakers)"
        return text

    def render(self, expr, games, top=False):
        if isinstance(expr, Or):
            text = " or ".join(self.render(arg, games) for arg in expr.args)
            return text if top else f"({text})"
        if isinstance(expr, And):
            text = " and ".join(self.render(arg, games) for arg in expr.args)
            return text if top else f"({text})"
        if isinstance(expr, Not):
            home, away = self.remaining[games[expr.args[0]]]
            return self.loses(home, away)
        home, away = self.remaining[games[expr]]
        return self.loses(away, home)

    def loses(self, loser, winner):
        return f"{loser} loses to {winner}"

    def help_summary(self, team, win_out):
        """Too many games to enumerate: list the teams that could finish
        with a better record, all but one of which have to fall back."""
        final = self.wins[team] + self.left[team]
        ahead = []
        for other in self.teams:
            if other == team:
                continue
            # games against us are already counted as losses
            best = self.wins[other] + self.left[other] - \
                sum(1 for i in win_out if other in self.remaining[i])
            if best > final:
                ahead.append((best - final, other))
        if len(ahead) < SPOTS:
            return "to win any tiebreakers against teams that tie it"
        ahead.sort(key=lambda x: (-x[0], x[1]))
        teams = ", ".join(f"{other} (lose {m}+ more)" for m, other in ahead)
        return (f"all but one of {teams} to finish no better than "
                f"{final}-{self.losses[team]}")


def print_scenarios(api_instance, year, week=None):
    played, remaining = fetch_games(api_instance, year, week)
    scenarios = Scenarios(played, remaining)
    heading = f"Big Ten championship game scenarios ({year}"
    if week is not None:
        heading += f", through week {week}"
    print(heading + ")")
    print()
    teams = sorted(scenarios.teams,
                   key=lambda t: (-win_pct(scenarios.wins[t],
                                           scenarios.losses[t]),
                                  scenarios.losses[t], t))
    for team in teams:
        print(f"{team} ({scenarios.record(team)}): "
              f"{scenarios.describe(team)}  ")
