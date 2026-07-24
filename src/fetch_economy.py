"""
fetch_economy.py — Builds economy price lookup from poe.ninja data dump.

Downloads Mirage league dump (~53MB ZIP), extracts daily price history for
unique items and Divine Orb. Builds a compact JSON lookup consumable by process.py.

Source: GET /poe1/api/data/dumps/dump?name=Mirage
Output: data/economy.json
"""

import csv
import io
import json
import os
import sys
import zipfile
import httpx

DUMP_URL = "https://poe.ninja/poe1/api/data/dumps/dump?name=Mirage"
ZIP_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "Mirage.zip")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "economy.json")

UNIQUE_TYPES = {"UniqueWeapon", "UniqueArmour", "UniqueAccessory", "UniqueFlask", "UniqueJewel", "UniqueMap", "UniqueTincture"}

# Map time-machine label to league day (day 1 = league start)
def label_to_day(label: str) -> int:
    """Convert time-machine label to equivalent league day (1-indexed)."""
    parts = label.split("-")
    unit = parts[0]
    num = int(parts[1])
    if unit == "hour":
        return 1
    if unit == "day":
        return num  # day-1 = day 1, day-2 = day 2
    if unit == "week":
        return num * 7  # week-1 = day 7, week-2 = day 14
    return 1


def download_dump() -> str:
    """Download Keepers dump if not cached. Returns path to ZIP."""
    if os.path.exists(ZIP_PATH):
        print(f"Using cached dump: {ZIP_PATH} ({os.path.getsize(ZIP_PATH):,} bytes)")
        return ZIP_PATH

    print(f"Downloading Keepers dump (~43MB)...")
    with httpx.stream("GET", DUMP_URL, timeout=300) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(ZIP_PATH, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=1_048_576):
                f.write(chunk)
                downloaded += len(chunk)
                pct = downloaded / total * 100 if total else 0
                print(f"\r  {downloaded:,} / {total:,} bytes ({pct:.0f}%)", end="", flush=True)
        print()
    print(f"Saved to {ZIP_PATH}")
    return ZIP_PATH


def parse_items_csv(zf: zipfile.ZipFile) -> dict:
    """Parse Mirage.items.csv into {item_name_lower: {day_offset: chaos_value}}.

    For items with multiple variants/links, keeps the cheapest per day.
    """
    print("Parsing items CSV...")
    items: dict[str, dict[int, float]] = {}

    with zf.open("Mirage.items.csv") as f:
        reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter=";")
        count = 0
        for row in reader:
            item_type = row.get("Type", "")
            if item_type not in UNIQUE_TYPES:
                continue

            name = row.get("Name", "").strip()
            if not name:
                continue

            date_str = row.get("Date", "")
            try:
                value = float(row.get("Value", "0"))
            except ValueError:
                continue

            # Compute day offset from Mirage league start (2026-03-06)
            try:
                parts = date_str.split("-")
                if len(parts) != 3:
                    continue
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                from datetime import date
                d = date(year, month, day)
                league_start = date(2026, 3, 6)
                day_offset = (d - league_start).days + 1  # day 1 = league start
                if day_offset < 1:
                    continue
            except (ValueError, ImportError):
                continue

            key = name.lower()
            if key not in items:
                items[key] = {}

            # Keep the cheapest price per day (items with multiple variants/links)
            current = items[key].get(day_offset)
            if current is None or value < current:
                items[key][day_offset] = value

            count += 1
            if count % 1_000_000 == 0:
                print(f"  Parsed {count:,} rows, {len(items):,} unique items...")

    print(f"  Parsed {count:,} rows, {len(items):,} unique items")
    return items


def parse_currency_csv(zf: zipfile.ZipFile) -> dict[int, float]:
    """Parse Mirage.currency.csv to get Divine Orb chaos price per day.

    Returns {day_offset: divine_chaos_value}
    """
    print("Parsing currency CSV for Divine Orb...")
    divine: dict[int, float] = {}

    with zf.open("Mirage.currency.csv") as f:
        reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter=";")
        for row in reader:
            get = row.get("Get", "")
            pay = row.get("Pay", "")
            if get != "Divine Orb" or pay != "Chaos Orb":
                continue

            date_str = row.get("Date", "")
            try:
                value = float(row.get("Value", "0"))
            except ValueError:
                continue

            try:
                parts = date_str.split("-")
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                from datetime import date
                d = date(year, month, day)
                league_start = date(2026, 3, 6)
                day_offset = (d - league_start).days + 1  # day 1 = league start
                if day_offset >= 1:
                    divine[day_offset] = value
            except (ValueError, ImportError):
                continue

    print(f"  Divine Orb prices for {len(divine)} days (range: day {min(divine.keys())}-{max(divine.keys())})")
    return divine


def build_economy():
    """Main entry point — builds economy.json from Mirage dump."""
    zip_path = download_dump()

    with zipfile.ZipFile(zip_path, "r") as zf:
        items = parse_items_csv(zf)
        divine = parse_currency_csv(zf)

    # Build output: per-item price arrays + divine rate array
    # Compact format: arrays indexed by day_offset
    # lookup: {item_name_lower: [price_day0, price_day1, ...]}
    # divine_rates: [rate_day0, rate_day1, ...]

    max_day = max(divine.keys()) if divine else 120

    # Build item price arrays (sparse → dense)
    item_arrays: dict[str, list[float | None]] = {}
    for name, day_prices in items.items():
        arr = [None] * (max_day + 1)
        for day, price in day_prices.items():
            if day <= max_day:
                arr[day] = price
        # Only include items that have at least some prices
        if any(p is not None for p in arr):
            item_arrays[name] = arr

    # Build divine rate array
    divine_array = [0.0] * (max_day + 1)
    for day, rate in divine.items():
        if day <= max_day:
            divine_array[day] = rate

    # Fill gaps in divine rates (forward-fill)
    last_rate = divine_array[0] or 1.0
    for i in range(max_day + 1):
        if divine_array[i] == 0:
            divine_array[i] = last_rate
        else:
            last_rate = divine_array[i]

    output = {
        "source": "Mirage dump (actual)",
        "league_start": "2026-03-06",
        "days": max_day + 1,
        "unique_item_count": len(item_arrays),
        "divine_rates": divine_array,
        "items": item_arrays,
        "label_day_map": {
            label: label_to_day(label)
            for label in [
                "hour-3", "hour-6", "hour-12", "hour-18",
                *[f"day-{i}" for i in range(1, 7)],
                *[f"week-{i}" for i in range(1, 20)],
            ]
        },
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f)
    print(f"\nSaved economy data to {OUTPUT_PATH}")
    print(f"  {len(item_arrays)} unique items, {max_day + 1} days of price history")
    return output


if __name__ == "__main__":
    build_economy()