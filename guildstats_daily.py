import os
import re
import sys
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from guildstats_deaths import fetch_death_rankings, format_death_report
from guildstats_discord import post_report


DATA_URL = "https://guildstats.eu/include/guild/tab.php?guild=The+Haunted&tab=timeonline"
PERIOD_DAYS = 1
RANGES = (
    ("0-300", 0, 300),
    ("301-400", 301, 400),
    ("401-500", 401, 500),
    ("501-600", 501, 600),
    ("601-700", 601, 700),
    ("701+", 701, None),
)


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.cell_text = ""
        self.row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
        elif self.in_table and tag == "tr":
            self.in_row = True
            self.row = []
        elif self.in_row and tag in ("td", "th"):
            self.in_cell = True
            self.cell_text = ""

    def handle_data(self, data):
        if self.in_cell:
            self.cell_text += data

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.in_cell:
            self.row.append(" ".join(self.cell_text.split()))
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            self.rows.append(self.row)
            self.in_row = False
        elif tag == "table":
            self.in_table = False


def fetch_rankings():
    request = Request(
        DATA_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; GuildStatsDaily/1.0)",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    with urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8")

    parser = TableParser()
    parser.feed(html)
    if not parser.rows or any(
        column not in parser.rows[0]
        for column in ("Lvl", "Nick", "Exp yesterday")
    ):
        raise ValueError("GuildStats returned an unexpected table format.")

    level_column = parser.rows[0].index("Lvl")
    nick_column = parser.rows[0].index("Nick")
    exp_column = parser.rows[0].index("Exp yesterday")
    rankings = {name: [] for name, _, _ in RANGES}

    for row in parser.rows[1:]:
        if len(row) <= max(level_column, nick_column, exp_column):
            continue
        if not row[level_column].isdigit():
            continue
        name = re.sub(r"\s*Compare character\s*$", "", row[nick_column]).strip()
        if not name:
            continue

        level = int(row[level_column])
        for range_name, minimum, maximum in RANGES:
            if level >= minimum and (maximum is None or level <= maximum):
                exp_text = row[exp_column].replace(",", "").replace(" ", "")
                if exp_text == "-Levelistoolowtogetexperiencedata":
                    continue
                if not re.fullmatch(r"[+-]?\d+", exp_text):
                    raise ValueError(f"Could not parse daily experience for {name!r}.")
                rankings[range_name].append((name, int(exp_text)))
                break

    for range_name, players in rankings.items():
        players.sort(key=lambda player: player[1], reverse=True)
        if len(players) < 3:
            raise ValueError(f"Fewer than three players found in level range {range_name}.")
    return rankings


def format_report(rankings, death_rankings):
    medals = ("🥇", "🥈", "🥉")
    report_date = datetime.now().astimezone().date() - timedelta(days=1)
lines = [
    f"**🏆 TOP 3 ⚡ XP — The Haunted ({report_date.strftime('%d.%m.%Y')})**"
]
    for range_name, _, _ in RANGES:
        lines.extend(("", f"🔹 Przedział {range_name}"))
        for medal, (name, exp) in zip(medals, rankings[range_name][:3]):
            lines.append(f"{medal} {name} — {exp:+,} XP")
    report = "\n".join(lines) + format_death_report(death_rankings, PERIOD_DAYS)
    if len(report) > 2000:
        raise ValueError("The Discord message exceeds the 2000-character limit.")
    return report


def main():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise ValueError("Set the DISCORD_WEBHOOK_URL environment variable first.")

    rankings = fetch_rankings()
    death_rankings = fetch_death_rankings(PERIOD_DAYS)
    report = format_report(rankings, death_rankings)
    print(report)
    post_report(report, webhook_url)
    print("\nReport posted to Discord.")


if __name__ == "__main__":
    try:
        main()
    except (HTTPError, URLError, TimeoutError, ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
