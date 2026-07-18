"""
fetch_index_state.py — Fetches time-machine labels from poe.ninja index-state.

GET /poe1/api/data/index-state → snapshotVersions[].timeMachineLabels for Mirage.
Saves sorted labels to data/time_machine_labels.json.
"""

import json
import os
import sys
import httpx

INDEX_STATE_URL = "https://poe.ninja/poe1/api/data/index-state"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "time_machine_labels.json")


def label_sort_key(label: str) -> tuple[int, int]:
    """Sort labels chronologically: hour-3 < hour-6 < ... < day-1 < ... < week-18."""
    parts = label.split("-")
    unit = parts[0]    # "hour", "day", or "week"
    num = int(parts[1])

    if unit == "hour":
        return (0, num)
    elif unit == "day":
        return (1, num)
    elif unit == "week":
        return (2, num)
    return (3, num)


def fetch_labels() -> dict:
    """Fetch index-state and return dict with labels, version, and league.

    Returns:
        {"labels": [...], "version": "1732-...", "league": "Mirage"}
    """
    print(f"Fetching {INDEX_STATE_URL}")
    resp = httpx.get(INDEX_STATE_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # Find the Mirage snapshot entry
    mirage_entry = None
    for entry in data.get("snapshotVersions", []):
        if entry.get("url") == "mirage":
            mirage_entry = entry
            break

    if not mirage_entry:
        print("ERROR: No 'mirage' entry found in snapshotVersions", file=sys.stderr)
        sys.exit(1)

    labels = mirage_entry.get("timeMachineLabels", [])
    if not labels:
        print("WARNING: timeMachineLabels empty or missing", file=sys.stderr)

    labels.sort(key=label_sort_key)
    version = data.get("version", "unknown")

    result = {
        "league": "Mirage",
        "version": version,
        "labels": labels,
    }
    print(f"Found {len(labels)} time-machine labels (version {version}): {labels}")
    return result


def main():
    result = fetch_labels()
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()