import json
import urllib.request
import urllib.parse
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

API = "https://hue.pp.ua/cherkasyoblenergo/api/blackout-schedule"
TZ = ZoneInfo("Europe/Kyiv")
QUEUE = "6_1"
OUTPUT = "docs/calendar.ics"


def fetch_schedule(day):
    params = urllib.parse.urlencode({
        "option": "by_schedule_date",
        "date": day,
        "queue": QUEUE
    })
    url = f"{API}?{params}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "CherkasyCalendar/1.0"}
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    if not isinstance(data, list):
        raise ValueError("Невідомий формат відповіді API")

    return data


def escape(text):
    return str(text).replace("\\", "\\\\").replace(
        ";", "\\;"
    ).replace(",", "\\,").replace("\n", "\\n")


def main():
    today = datetime.now(TZ).date()
    records = []

    for offset in range(2):
        day = today + timedelta(days=offset)
        records.extend(fetch_schedule(day.isoformat()))

    events = []

    for record in records:
        schedule_day = date.fromisoformat(record["schedule_date"])
        intervals = record.get(QUEUE, "")

        if not intervals:
            continue

        for interval in intervals.split(","):
            parts = interval.strip().replace(" ", "").split("-")
            if len(parts) != 2:
                continue

            start_time = time.fromisoformat(parts[0])
start = datetime.combine(schedule_day, start_time, TZ)

if parts[1] in ("24:00", "24:00:00"):
    end = datetime.combine(
        schedule_day + timedelta(days=1), time.min, TZ
    )
else:
    end_time = time.fromisoformat(parts[1])
    end = datetime.combine(schedule_day, end_time, TZ)

            if end <= start:
                end += timedelta(days=1)

            uid = f"{QUEUE}-{schedule_day}-{start_time}-{end_time}@cherkasy-calendar"

            events.append((uid, start, end))

    if not events:
        raise ValueError("Графік не знайдено. Старий календар не перезаписано.")

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
            f"DTSTAMP:{datetime.now(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART;TZID=Europe/Kyiv:{start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID=Europe/Kyiv:{end.strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{escape('6.1 черга — відключення')}",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")

    import os
    os.makedirs("docs", exist_ok=True)

    with open(OUTPUT, "w", encoding="utf-8", newline="\r\n") as file:
        file.write("\r\n".join(lines) + "\r\n")


if __name__ == "__main__":
    main()
