#!/usr/bin/python3

import argparse
import datetime
import dateutil.parser
import CFBScrapy as cfb
import itertools
import networkx as nx

parser = argparse.ArgumentParser()
parser.add_argument("--single-team", "-s", help="dot file for single team")
parser.add_argument("--year", "-y", help = "pick specific year")
parser.add_argument("--num-teams", "-n", help = "number of teams (default: 25)")
args = parser.parse_args()

if args.single_team:
    single_team = args.single_team
else:
    single_team = ""

today = datetime.datetime.now()
if args.year:
    year = args.year
else:
    if today.month < 8: # go with last season if before august
        year = today.year - 1
    else:
        year = today.year

if args.num_teams:
    num_teams = int(args.num_teams) + 1
else:
    num_teams = 26

G = nx.DiGraph()

actual_wins = {}
actual_losses = {}

def find_games(season_type):
    games = cfb.get_game_info(year=year, seasonType = season_type)

    for i, game in games.iterrows():
        if dateutil.parser.parse(game['start_date']).replace(tzinfo=None) > today:
            continue
        team1 = game['home_team']
        team2 = game['away_team']
        if game['home_points'] > game['away_points']:
            if team1 in actual_wins:
                actual_wins[team1] += 1
            else:
                actual_wins[team1]= 1
                if team2 in actual_losses:
                    actual_losses[team2] += 1
                else:
                    actual_losses[team2] = 1
                    G.add_edge(team1, team2)
        elif game['home_points'] < game['away_points']:
            if team2 in actual_wins:
                actual_wins[team2] += 1
            else:
                actual_wins[team2]= 1
                if team1 in actual_losses:
                    actual_losses[team1] += 1
                else:
                    actual_losses[team1] = 1
                    G.add_edge(team2, team1)

find_games('regular')
find_games('postseason')

wins = {}

for team in G:
    wins[team] = 0

for team in G:
    if team not in actual_wins:
        actual_wins[team] = 0
    if team not in actual_losses:
        actual_losses[team] = 0

for teams in itertools.combinations(G, 2):
    try:
        n = nx.shortest_path_length(G, source=teams[0], target=teams[1])
        wins[teams[0]] += 2**(1 - n)
        wins[teams[1]] += -2**(1 - n)
    except nx.NetworkXNoPath:
        pass

    try:
        n = nx.shortest_path_length(G, source=teams[1], target=teams[0])
        wins[teams[1]] += 2**(1 - n)
        wins[teams[0]] += -2**(1 - n)
    except nx.NetworkXNoPath:
        pass

sorted_wins = list(reversed(sorted(wins.items(), key=lambda kv: kv[1])))

if len(sorted_wins) + 1 < num_teams:
    num_teams = len(sorted_wins) + 1

for i in range(1, num_teams):
    print(str(i) + " - " + sorted_wins[i-1][0] + " (" +
          str(actual_wins[sorted_wins[i-1][0]]) + "-" +
          str(actual_losses[sorted_wins[i-1][0]]) + ") (" +
          str(sorted_wins[i-1][1]) + ")  ")

if single_team != "":
    single_team_graph_teams = list(nx.descendants(G, single_team)) + \
                              list(nx.ancestors(G,single_team)) + [single_team]
    single_team_graph = G.subgraph(single_team_graph_teams)
    nx.nx_agraph.write_dot(single_team_graph, "single_team.dot")
