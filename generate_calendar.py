import json
import urllib.request
import urllib.parse
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
import os

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

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "CherkasyCalendar/2.0"}
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    if not isinstance(data, list):
        raise ValueError("API повернув невідомий формат даних")

    return data


def parse_schedule_time(value, schedule_day):
    value = value.strip()

    parts = value.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Невідомий формат часу: {value}")

    hour = int(parts[0])
    minute = int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0

    if hour == 24 and minute == 0 and second == 0:
        return datetime.combine(
            schedule_day + timedelta(days=1),
            time.min,
            TZ
        )

    if not (0 <= hour <= 23):
        raise ValueError(f"Некоректна година: {value}")

    if not (0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError(f"Некоректний час: {value}")

    return datetime.combine(
        schedule_day,
        time(hour, minute, second),
        TZ
    )


def escape(text):
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


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
            interval = interval.strip()

            if not interval:
                continue

            parts = interval.replace(" ", "").split("-")

            if len(parts) != 2:
                continue

            start = parse_schedule_time(parts[0], schedule_day)
            end = parse_schedule_time(parts[1], schedule_day)

            if end <= start:
                end += timedelta(days=1)

            uid = (
                f"{QUEUE}-{schedule_day}-"
                f"{start.strftime('%H%M')}-"
                f"{end.strftime('%H%M')}@cherkasy-calendar"
            )

            events.append((uid, start, end))

    if not events:
        raise ValueError(
            "Графік не знайдено. Старий календар не перезаписано."
        )

    now_utc = datetime.now(timezone.utc)
    stamp = now_utc.strftime("%Y%m%dT%H%M%SZ")

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
        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc)

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{start_utc.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{end_utc.strftime('%Y%m%dT%H%M%SZ')}",
            f"SUMMARY:{escape('6.1 черга — відключення')}",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")

    os.makedirs("docs", exist_ok=True)

    with open(OUTPUT, "w", encoding="utf-8", newline="\r\n") as file:
        file.write("\r\n".join(lines) + "\r\n")

    print(f"Календар створено. Подій: {len(events)}")


if __name__ == "__main__":
    main()
