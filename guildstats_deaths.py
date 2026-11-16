import json
import re
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GUILD_API_URL = "https://api.tibiadata.com/v5/guild/The%20Haunted"
TIBIA_CHARACTER_URL = (
    "https://www.tibia.com/community/?subtopic=characters&name={name}"
)
REQUEST_DELAY_SECONDS = 0.15
MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


class DeathTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_row = False
        self.in_cell = False
        self.cell_text = ""
        self.row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
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


def parse_death_date(value):
    match = re.fullmatch(
        r"([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{4}),\s+"
        r"(\d{2}):(\d{2}):(\d{2})\s+(CET|CEST)",
        " ".join(value.split()),
    )
    if not match or match.group(1) not in MONTHS:
        return None

    month, day, year, hour, minute, second, zone = match.groups()
    return datetime(
        int(year),
        MONTHS[month],
        int(day),
        int(hour),
        int(minute),
        int(second),
        tzinfo=timezone(timedelta(hours=2 if zone == "CEST" else 1)),
    )


def fetch_guild_members():
    request = Request(
        GUILD_API_URL,
        headers={"User-Agent": "GuildStatsReport/1.0"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    members = payload.get("guild", {}).get("members")
    if not isinstance(members, list):
        raise ValueError("TibiaData returned an unexpected guild member list.")

    names = []
    seen = set()
    for member in members:
        name = member.get("name") if isinstance(member, dict) else None
        if isinstance(name, str) and name.strip() and name.casefold() not in seen:
            name = name.strip()
            names.append(name)
            seen.add(name.casefold())
    if not names:
        raise ValueError("TibiaData returned no guild member names.")
    return names


def fetch_character_deaths(name):
    url = TIBIA_CHARACTER_URL.format(name=quote(name, safe=""))
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8")

    parser = DeathTableParser()
    parser.feed(html)
    deaths = []
    for row in parser.rows:
        if len(row) < 2 or not re.search(r"\bDied at Level\b", row[1]):
            continue
        death_date = parse_death_date(row[0])
        if death_date is None:
            raise ValueError(f"Could not parse a death date for {name!r}.")
        deaths.append(death_date)
    return deaths


def fetch_death_rankings(days):
    return fetch_death_rankings_for_periods((days,))[days]


def fetch_death_rankings_for_periods(period_days):
    periods = tuple(dict.fromkeys(period_days))
    if not periods or any(days <= 0 for days in periods):
        raise ValueError("Death report periods must be greater than zero days.")

    members = fetch_guild_members()
    now = datetime.now().astimezone()
    cutoffs = {days: now - timedelta(days=days) for days in periods}
    rankings = {days: [] for days in periods}

    for index, name in enumerate(members):
        if index:
            time.sleep(REQUEST_DELAY_SECONDS)
        try:
            deaths = fetch_character_deaths(name)
        except (HTTPError, URLError, TimeoutError, UnicodeError, ValueError) as error:
            raise RuntimeError(
                f"Could not retrieve death history for {name!r}: {error}"
            ) from error
        for days, cutoff in cutoffs.items():
            count = sum(cutoff <= death_date <= now for death_date in deaths)
            if count:
                rankings[days].append((name, count))

    for days, counts in rankings.items():
        counts.sort(key=lambda player: (-player[1], player[0].casefold()))
        if len(counts) > 3:
            third_place_count = counts[2][1]
            rankings[days] = [
                player for player in counts if player[1] >= third_place_count
            ]
    return rankings


def format_death_report(death_rankings, days):
    if days == 1:
        period = "ostatnie 24 godziny"
    elif days == 7:
        period = "ostatnie 7 dni"
    else:
        period = f"ostatnie {days} dni"
    lines = [f"**💀 TOP 3 ZGONÓW — The Haunted ({period})**"]
    if not death_rankings:
        lines.append("Brak zgonów w tym okresie.")
    else:
        previous_count = None
        rank = 0
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for index, (name, count) in enumerate(death_rankings, start=1):
            if count != previous_count:
                rank = index
                previous_count = count
            medal = medals.get(rank, f"{rank}.")
            lines.append(f"{medal} {name} — {count} zgonów")
    return "\n\n" + "\n".join(lines)
