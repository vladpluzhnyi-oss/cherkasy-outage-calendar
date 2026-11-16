import json
import os
import re
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo

# Official public news API of Cherkasyoblenergo. No login or API key.
NEWS_API = (
    "https://www.cherkasyoblenergo.com/api/v1/posts/"
    "category/news?lang=uk&page=0&size=40"
)
TZ = ZoneInfo("Europe/Kyiv")
QUEUE = "6.1"
OUTPUT = "docs/calendar.ics"

MONTHS = {
    "січня": 1, "лютого": 2, "березня": 3, "квітня": 4,
    "травня": 5, "червня": 6, "липня": 7, "серпня": 8,
    "вересня": 9, "жовтня": 10, "листопада": 11, "грудня": 12,
}
DATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s+(січня|лютого|березня|квітня|травня|червня|"
    r"липня|серпня|вересня|жовтня|листопада|грудня)\b",
    re.IGNORECASE,
)
QUEUE_RE = re.compile(r"^\s*([1-6])\s*[.,]\s*([12])\.?\s*:?\s*(.*?)\s*$")
TIME_RE = re.compile(r"(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})")
SCHEDULE_WORDS = ("гпв", "графік погодинних відключень", "графік відключень")


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("p", "div", "br", "li", "tr", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in ("p", "div", "li", "tr", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

    def get_text(self):
        return "\n".join(self.parts)


def fetch_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "CherkasyOutageCalendar/3.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError(f"HTTP {response.status} from {url}")
        return json.loads(response.read().decode("utf-8"))


def parse_published_at(value):
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed.astimezone(TZ)


def schedule_date_from_title(title, published_at):
    match = DATE_RE.search(title.lower())
    if not match:
        return None
    day = int(match.group(1))
    month = MONTHS[match.group(2).lower()]
    candidates = []
    for year in (published_at.year - 1, published_at.year, published_at.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            pass
    if not candidates:
        return None
    return min(candidates, key=lambda d: abs((d - published_at.date()).days))


def build_detail_url(slug):
    return (
        "https://www.cherkasyoblenergo.com/api/v1/posts/"
        + urllib.parse.quote(str(slug), safe="-_")
        + "?lang=uk"
    )


def html_to_text(content):
    parser = TextExtractor()
    parser.feed(content or "")
    return parser.get_text().replace("\u00a0", " ").replace("\u202f", " ")


def parse_queue_rows(content):
    rows = {}
    for raw_line in html_to_text(content).splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        match = QUEUE_RE.match(line)
        if not match:
            continue
        queue_id = f"{match.group(1)}.{match.group(2)}"
        value = match.group(3).strip().rstrip(",.;")
        rows[queue_id] = value
    return rows


def fetch_schedules(days):
    response = fetch_json(NEWS_API)
    if not response.get("success"):
        raise ValueError("Офіційний сайт повернув success=false")

    posts = response.get("data", {}).get("content", [])
    if not isinstance(posts, list):
        raise ValueError("Невідомий формат списку новин Черкасиобленерго")

    target_days = set(days)
    candidates = []

    for post in posts:
        title = str(post.get("title", ""))
        if not any(word in title.lower() for word in SCHEDULE_WORDS):
            continue
        slug = post.get("slug")
        published_raw = post.get("publishedAt")
        if not slug or not published_raw:
            continue
        try:
            published_at = parse_published_at(published_raw)
        except Exception as exc:
            print(f"Пропускаю новину з некоректною датою {title!r}: {exc}")
            continue
        schedule_day = schedule_date_from_title(title, published_at)
        if schedule_day in target_days:
            candidates.append((published_at, schedule_day, title, slug))

    candidates.sort(key=lambda item: item[0], reverse=True)
    schedules = {}

    for published_at, schedule_day, title, slug in candidates:
        if schedule_day in schedules:
            continue
        detail = fetch_json(build_detail_url(slug))
        if not detail.get("success"):
            print(f"Не вдалося отримати текст новини: {title}")
            continue
        content = detail.get("data", {}).get("content", "")
        rows = parse_queue_rows(content)

        # Require the target queue and a substantial set of queue rows;
        # this guards against unrelated news being treated as a schedule.
        if QUEUE not in rows or len(rows) < 6:
            print(f"У новині не знайдено повного графіка: {title}")
            continue

        schedules[schedule_day] = {"title": title, "queues": rows}
        print(f"Знайдено графік на {schedule_day}: {title}")

    return schedules


def parse_clock(value, schedule_day):
    hour, minute = map(int, value.split(":"))
    if hour == 24 and minute == 0:
        return datetime.combine(schedule_day + timedelta(days=1), time.min, TZ)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Некоректний час: {value}")
    return datetime.combine(schedule_day, time(hour, minute), TZ)


def escape_ics(value):
    return (
        str(value).replace("\\", "\\\\").replace(";", "\\;")
        .replace(",", "\\,").replace("\n", "\\n")
    )


def main():
    today = datetime.now(TZ).date()
    days = [today + timedelta(days=offset) for offset in range(3)]
    schedules = fetch_schedules(days)

    # Never replace the existing calendar with an empty/invalid result.
    if not schedules:
        raise ValueError(
            "На офіційному сайті не знайдено актуального графіка. "
            "Старий календар не перезаписано."
        )

    events = []
    for schedule_day in sorted(schedules):
        value = schedules[schedule_day]["queues"].get(QUEUE, "")
        for start_text, end_text in TIME_RE.findall(value):
            start = parse_clock(start_text, schedule_day)
            end = parse_clock(end_text, schedule_day)
            if end <= start:
                end += timedelta(days=1)
            uid = (
                f"6-1-{schedule_day}-"
                f"{start.strftime('%H%M')}-{end.strftime('%H%M')}"
                "@cherkasy-calendar"
            )
            events.append((uid, start, end))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Cherkasy Outage Calendar//UK",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Черкаси 6.1 — відключення",
        "X-WR-TIMEZONE:Europe/Kyiv",
    ]

    for uid, start, end in events:
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{start.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{end.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            f"SUMMARY:{escape_ics('6.1 черга — відключення')}",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8", newline="") as file:
        file.write("\r\n".join(lines) + "\r\n")

    print(
        f"Календар оновлено. Днів із підтвердженим графіком: {len(schedules)}. "
        f"Подій для черги 6.1: {len(events)}."
    )


if __name__ == "__main__":
    main()
