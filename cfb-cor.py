#!/usr/bin/python3

from bs4 import BeautifulSoup
import itertools
import networkx as nx
import requests

# get current year + week
doc = requests.get("https://www.ncaa.com/scoreboard/football/fbs")
soup = BeautifulSoup(doc.content, "lxml")
div = soup.find("div", class_="selected")
year = div.find("a")["href"].split("/")[4]
week = div.get_text(strip=True)

G = nx.DiGraph()

for i in range(1, int(week) + 1):
    doc = requests.get("https://www.ncaa.com/scoreboard/football/fbs/" + year
                       + "/" + str(i).zfill(2) + "/all-conf")
    soup = BeautifulSoup(doc.content, "lxml")
    games = soup.find_all("ul", class_="gamePod-game-teams")
    for game in games:
        teams = game.find_all("li")
        team1 = teams[0].find("span",
                              class_="gamePod-game-team-name").get_text()
        team2 = teams[1].find("span",
                              class_="gamePod-game-team-name").get_text()
        if teams[0]["class"][0] == "winner":
            G.add_edge(team1, team2)
        elif teams[1]["class"][0] == "winner":
            G.add_edge(team2, team1)

wins = {}

for team in G:
    wins[team] = 0

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

for i in range(1, 26):
    print(str(i) + " - " + sorted_wins[i-1][0] + " (" +
          str(sorted_wins[i-1][1]) + ")")
