"""
process.py — Core aggregation: top-20 DPS average, unique pricing, character filtering.

Reads raw build data, economy prices, and exclusion list.
Writes data/processed.json — single source of truth for API and frontend.
"""

import json
import os
import sys
from collections import defaultdict

# Add src dir to path for t0_t1_uniques import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from t0_t1_uniques import ALL_EXCLUDED_UNIQUES

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
ECONOMY_PATH = os.path.join(DATA_DIR, "economy.json")
LABELS_PATH = os.path.join(DATA_DIR, "time_machine_labels.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "processed.json")

# Normalize T0/T1 sets separately for configurable filtering
from t0_t1_uniques import T0_UNIQUES, T1_UNIQUES
T0_LOWER: set[str] = {n.lower() for n in T0_UNIQUES}
T1_LOWER: set[str] = {n.lower() for n in T1_UNIQUES}
EXCLUDED_LOWER: set[str] = T0_LOWER | T1_LOWER

MIN_BUILDS_PER_SKILL = 5
TOP_N = 20

def divine_cap_for_label(label: str) -> float:
    """Maximum allowed divine orb total for a character in this window.

    Formula: 3 divines × league_day.
    hour-3 through hour-18 = day 1.
    day-N = 3 × N, week-N = 3 × 7 × N.
    """
    if label.startswith("hour-"):
        return 3.0
    if label.startswith("day-"):
        return float(label.split("-")[1]) * 3.0
    if label.startswith("week-"):
        return float(label.split("-")[1]) * 21.0
    return float("inf")

def load_economy() -> tuple[dict, list[float], dict[str, int]]:
    """Load economy.json (Keepers dump format).

    Returns:
        (items, divine_rates, label_day_map)
        items: {name_lower: [price_day0, price_day1, ...]}  (index = day offset)
        divine_rates: [rate_day0, rate_day1, ...]
        label_day_map: {label: day_offset}
    """
    if not os.path.exists(ECONOMY_PATH):
        print(f"WARNING: {ECONOMY_PATH} not found — prices will be 0", file=sys.stderr)
        return {}, [0.0], {}

    with open(ECONOMY_PATH) as f:
        eco = json.load(f)
    items = eco.get("items", {})
    divine_rates = eco.get("divine_rates", [0.0])
    label_day_map = eco.get("label_day_map", {})
    return items, divine_rates, label_day_map


def load_labels() -> list[str]:
    with open(LABELS_PATH) as f:
        return json.load(f)["labels"]


def load_builds_for_label(label: str) -> list[dict]:
    """Load and parse builds from all per-ascendancy Firecrawl output files.

    Looks for data/builds_raw_{label}_*.json, loads each, and combines results.
    Returns list of normalized build dicts or empty list.
    """
    import glob as glob_mod

    pattern = os.path.join(DATA_DIR, f"builds_raw_{label}_*.json")
    files = sorted(glob_mod.glob(pattern))

    # Fallback: try old single-file format (builds_raw_{label}.json)
    if not files:
        old_path = os.path.join(DATA_DIR, f"builds_raw_{label}.json")
        if os.path.exists(old_path):
            files = [old_path]

    all_builds = []
    for path in files:
        with open(path) as f:
            raw = json.load(f)

        # Detect format: puppeteer has {builds: [...]}, Firecrawl has {data: {extract: ...}}
        extract = None
        if "builds" in raw and isinstance(raw["builds"], list):
            # Puppeteer format
            extract = raw["builds"]
        elif "data" in raw:
            # Firecrawl format
            extract = raw.get("data", {}).get("extract")
        if extract is None:
            extract = raw.get("extract")  # Fallback
        if extract is None:
            print(f"WARNING: No build data found in {path}", file=sys.stderr)
            continue

        if isinstance(extract, str):
            try:
                extract = json.loads(extract)
            except json.JSONDecodeError:
                print(f"WARNING: Could not parse extract JSON in {path}", file=sys.stderr)
                continue

        if not isinstance(extract, list):
            print(f"WARNING: Unexpected extract format in {path}: {type(extract)}", file=sys.stderr)
            continue

        for entry in extract:
            if not isinstance(entry, dict):
                continue
            all_builds.append(normalize_build(entry))

    return all_builds


def normalize_build(entry: dict) -> dict:
    """Normalize a single build entry from Firecrawl extraction."""
    unique_items = entry.get("uniqueItems", [])
    if not isinstance(unique_items, list):
        unique_items = []

    normalized_items = []
    for item in unique_items:
        if isinstance(item, dict):
            normalized_items.append({
                "name": str(item.get("name", "")),
                "links": int(item.get("links", 0)),
            })

    return {
        "characterName": str(entry.get("characterName", "")),
        "level": int(entry.get("level", 0)),
        "class": str(entry.get("class", "")),
        "ascendancy": str(entry.get("ascendancy", "")),
        "skill": str(entry.get("skill", "")),
        "dps": float(entry.get("dps", 0)),
        "life": float(entry.get("life", 0)) if entry.get("life") is not None else None,
        "energyShield": float(entry.get("energyShield", 0)) if entry.get("energyShield") is not None else None,
        "uniqueItems": normalized_items,
    }


def normalize_skill_name(name: str) -> str:
    """Normalize skill name for grouping: lowercase, strip, collapse spaces."""
    return " ".join(name.strip().lower().split())


def compute_view(items: dict, divine_rates: list[float], label_day_map: dict,
                 labels: list[str], window_order: dict[str, int],
                 exclude_t0: bool, exclude_t1: bool, enforce_cap: bool) -> dict:
    """Compute skills_output for one filter configuration."""

    # Phase 1: per-window character filtering and skill grouping
    window_data: dict[str, dict[str, list[dict]]] = {}

    for label in labels:
        builds = load_builds_for_label(label)
        if not builds:
            continue

        cap = divine_cap_for_label(label) if enforce_cap else float("inf")
        day_offset = label_day_map.get(label, 1)

        filtered_builds = []
        for build in builds:
            if not should_exclude(build, items, divine_rates, day_offset, cap,
                                  exclude_t0=exclude_t0, exclude_t1=exclude_t1,
                                  enforce_cap=enforce_cap):
                filtered_builds.append(build)

        # Group by skill
        skill_groups: dict[str, list[dict]] = defaultdict(list)
        for build in filtered_builds:
            skill_norm = normalize_skill_name(build["skill"])
            if skill_norm:
                skill_groups[skill_norm].append(build)

        valid_groups = {s: b for s, b in skill_groups.items() if len(b) >= MIN_BUILDS_PER_SKILL}
        if valid_groups:
            window_data[label] = valid_groups

    # Phase 2: build skills_output
    all_skills: set[str] = set()
    for ld in window_data.values():
        all_skills.update(ld.keys())

    skills_output: dict = {}
    for skill in all_skills:
        dps_over_time: dict = {}
        build_count: dict = {}
        top_ascendancy: dict = {}
        ascendancy_counts: dict = {}
        unique_usage: dict = {}

        original_name = skill
        for label in labels:
            if label in window_data:
                for snorm, blds in window_data[label].items():
                    if snorm == skill and blds:
                        original_name = blds[0]["skill"]
                        break

        for label in labels:
            blds = window_data.get(label, {}).get(skill, [])
            if not blds:
                continue

            sorted_blds = sorted(blds, key=lambda b: b["dps"], reverse=True)
            top_blds = sorted_blds[:TOP_N]
            if len(top_blds) < MIN_BUILDS_PER_SKILL:
                continue

            dps_values = [b["dps"] for b in top_blds]
            dps_over_time[label] = round(sum(dps_values) / len(dps_values), 1)
            build_count[label] = len(top_blds)

            asc_counts: dict[str, int] = defaultdict(int)
            for b in top_blds:
                asc = b.get("ascendancy", "Unknown")
                if asc:
                    asc_counts[asc] += 1
            if asc_counts:
                top_ascendancy[label] = max(asc_counts, key=lambda k: asc_counts[k])
                ascendancy_counts[label] = dict(asc_counts)

            # Unique item usage
            day = label_day_map.get(label, 1)
            divine_rate = divine_rates[day] if day < len(divine_rates) else divine_rates[-1]
            if divine_rate <= 0:
                divine_rate = 1.0

            item_usage: dict[str, dict] = {}
            for b in top_blds:
                for item in b.get("uniqueItems", []):
                    item_name = item["name"]
                    if not item_name:
                        continue
                    prices = items.get(item_name.lower())
                    chaos_val = 0.0
                    if prices and day < len(prices) and prices[day] is not None:
                        chaos_val = prices[day]
                    divine_val = chaos_val / divine_rate if chaos_val > 0 else 0.0
                    if item_name not in item_usage:
                        item_usage[item_name] = {"count": 0, "total_price_chaos": 0, "divine_value": divine_val}
                    item_usage[item_name]["count"] += 1
                    item_usage[item_name]["total_price_chaos"] += chaos_val
            for name, data in item_usage.items():
                data["avg_price_chaos"] = round(data["total_price_chaos"] / data["count"], 1)
                del data["total_price_chaos"]
            unique_usage[label] = item_usage

        skills_output[original_name] = {
            "dps_over_time": dps_over_time,
            "build_count": build_count,
            "top_ascendancy": top_ascendancy,
            "ascendancy_counts": ascendancy_counts,
            "unique_usage": unique_usage,
        }
        if not dps_over_time:
            del skills_output[original_name]

    return skills_output


def process():
    """Main pipeline — computes 3 filter views and saves processed.json."""
    print("Loading economy data...")
    items, divine_rates, label_day_map = load_economy()
    labels = load_labels()
    window_order = {label: i for i, label in enumerate(labels)}

    views = {
        "t0_t1_cap": {
            "label": "T0 + T1 + Divine Cap",
            "desc": "Excludes T0 & T1 uniques, enforces divine budget",
            "exclude_t0": True, "exclude_t1": True, "enforce_cap": True,
        },
        "t0_t1_nocap": {
            "label": "T0 + T1, No Cap",
            "desc": "Excludes T0 & T1 uniques, no divine budget limit",
            "exclude_t0": True, "exclude_t1": True, "enforce_cap": False,
        },
        "t0_only": {
            "label": "T0 Only + Divine Cap",
            "desc": "Excludes T0 uniques only, enforces divine budget",
            "exclude_t0": True, "exclude_t1": False, "enforce_cap": True,
        },
        "unfiltered": {
            "label": "Unfiltered (All Builds)",
            "desc": "No T0/T1 exclusion, no divine cap",
            "exclude_t0": False, "exclude_t1": False, "enforce_cap": False,
        },
    }
    all_skills_output = {}
    for view_id, cfg in views.items():
        label = cfg["label"]
        print(f"\nComputing view: {label}")
        skills = compute_view(items, divine_rates, label_day_map, labels, window_order,
                              exclude_t0=cfg["exclude_t0"],
                              exclude_t1=cfg["exclude_t1"],
                              enforce_cap=cfg["enforce_cap"])
        all_skills_output[view_id] = skills
        print(f"  → {len(skills)} skills")

    # Build ascendancy index from the strictest view (t0_t1_cap)
    primary_skills = all_skills_output["t0_t1_cap"]

    output = {
        "league": "Mirage",
        "windows": labels,
        "window_order": window_order,
        "filters_applied": {
            "excluded_uniques": sorted(ALL_EXCLUDED_UNIQUES),
            "excluded_count": len(ALL_EXCLUDED_UNIQUES),
            "divine_cap_formula": "3 divines × league_day",
        },
        "default_view": "t0_t1_cap",
        "views": {
            vid: {"label": cfg["label"], "desc": cfg["desc"], "skills": all_skills_output[vid]}
            for vid, cfg in views.items()
        },
        # Backwards compatibility: expose default view at top level
        "skills": primary_skills,
        "ascendancy_skills": build_ascendancy_index(primary_skills),
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    total = sum(len(v) for v in all_skills_output.values())
    print(f"\nProcessed {total} skill-views across {len(labels)} windows")
    print(f"Output written to {OUTPUT_PATH}")
    return output


def build_ascendancy_index(skills_output: dict) -> dict[str, list[str]]:
    """Build ascendancy → sorted skill names from skills_output."""
    KNOWN = {
        "Juggernaut", "Berserker", "Chieftain",
        "Slayer", "Gladiator", "Champion",
        "Deadeye", "Warden", "Pathfinder",
        "Assassin", "Saboteur", "Trickster",
        "Necromancer", "Elementalist", "Occultist",
        "Inquisitor", "Hierophant", "Guardian",
        "Ascendant", "Reliquarian",
    }
    idx: dict[str, set[str]] = defaultdict(set)
    for skill_name, data in skills_output.items():
        for label_counts in data.get("ascendancy_counts", {}).values():
            for asc in label_counts:
                if asc in KNOWN:
                    idx[asc].add(skill_name)
    return {asc: sorted(skills) for asc, skills in idx.items()}


def should_exclude(build: dict, items: dict, divine_rates: list[float],
                   day_offset: int, cap: float,
                   exclude_t0: bool = True, exclude_t1: bool = True,
                   enforce_cap: bool = True) -> bool:
    """Check if a character should be excluded based on unique items.

    Args:
        exclude_t0: if True, exclude characters wearing T0 uniques
        exclude_t1: if True, exclude characters wearing T1 uniques
        enforce_cap: if True, exclude characters exceeding divine budget
    """
    total_divine = 0.0
    divine_rate = divine_rates[day_offset] if day_offset < len(divine_rates) else divine_rates[-1]
    if divine_rate <= 0:
        divine_rate = 1.0

    for item in build.get("uniqueItems", []):
        item_name = item.get("name", "").lower()

        # Check T0 exclusion
        if exclude_t0 and item_name in T0_LOWER:
            return True
        # Check T1 exclusion
        if exclude_t1 and item_name in T1_LOWER:
            return True

        # Price lookup by name + day
        prices = items.get(item_name)
        if prices and day_offset < len(prices):
            chaos_val = prices[day_offset]
            if chaos_val is not None:
                total_divine += chaos_val / divine_rate

    if enforce_cap and total_divine > cap > 0:
        return True

    return False


if __name__ == "__main__":
    process()