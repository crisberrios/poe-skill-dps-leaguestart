"""
fetch_builds.py — Scrapes poe.ninja builds table.

Primary: local headless Chromium via Puppeteer (fast, free, no credit cost).
Fallback: Firecrawl API (--firecrawl flag).

For each time-machine label × ascendancy, scrapes the top builds table.
URL pattern: https://poe.ninja/poe1/builds/mirage?timemachine={label}&class={ascendancy}

Extracts per row: characterName, level, ascendancy, life, energyShield, ehp,
dps, skill, keystones. Note: equipped items are NOT shown on the builds table;
use Firecrawl extract mode or visit individual character pages for item data.

Usage:
    python src/fetch_builds.py --all                      # all labels × all ascendancies (local)
    python src/fetch_builds.py --label day-1               # all ascendancies for one label
    python src/fetch_builds.py --label day-1 --class Juggernaut  # single scrape
    python src/fetch_builds.py --all --firecrawl           # use Firecrawl instead of local
"""

import json
import math
import os
import re
import subprocess
import sys
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
LABELS_PATH = os.path.join(DATA_DIR, "time_machine_labels.json")

# All 19 official PoE 3.28 ascendancies (sourced from pathofexile.com/ascendancy/classes)
# Raider replaced by Warden in 3.25; Reliquarian added in 3.28 for Scion
ASCENDANCIES = [
    "Juggernaut", "Berserker", "Chieftain",       # Marauder
    "Slayer", "Gladiator", "Champion",             # Duelist
    "Deadeye", "Warden", "Pathfinder",             # Ranger (Raider removed in 3.25)
    "Assassin", "Saboteur", "Trickster",           # Shadow
    "Necromancer", "Elementalist", "Occultist",    # Witch
    "Inquisitor", "Hierophant", "Guardian",        # Templar
    "Ascendant", "Reliquarian",                    # Scion
]

PUPPETEER_SCRIPT = r"""
const puppeteer = require('puppeteer');
const zlib = require('zlib');

const [label, ascendancy, outPath, itemsFlag] = process.argv.slice(2);
const scrapeItems = itemsFlag === '--items';

(async () => {
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
  });
  const page = await browser.newPage();
  await page.setViewport({width: 1920, height: 1080});

  const url = `https://poe.ninja/poe1/builds/mirage?timemachine=${label}&class=${ascendancy}&sort=dps`;
  await page.goto(url, {waitUntil: 'networkidle2', timeout: 30000});
  await page.waitForSelector('._build-table_167ik_1', {timeout: 15000});
  await new Promise(r => setTimeout(r, 2000));

  const builds = await page.evaluate(() => {
    function parseDps(text) {
      if (!text) return 0;
      text = text.replace(/,/g, '').trim();
      const num = parseFloat(text);
      if (!isNaN(num)) {
        const lower = text.toLowerCase();
        if (lower.includes('k')) return Math.round(num * 1000);
        if (lower.includes('m')) return Math.round(num * 1000000);
        if (lower.includes('b')) return Math.round(num * 1000000000);
        return num;
      }
      return 0;
    }

    const rows = document.querySelectorAll('._build-table_167ik_1 tbody tr');
    const results = [];
    for (const row of rows) {
      const cells = row.querySelectorAll('td');
      if (cells.length < 7) continue;

      const nameLink = cells[0].querySelector('a');
      const characterName = nameLink ? nameLink.textContent.trim() : '';
      const href = nameLink ? nameLink.getAttribute('href') : '';

      // Extract account from href: /poe1/builds/mirage/character/{account}-{id}/{charName}
      let account = '';
      let id = '';
      const match = href && href.match(/\/character\/([^-]+)-(\d+)\//);
      if (match) {
        account = match[1];
        id = match[2];
      }

      const levelText = (cells[1].textContent || '').trim();
      const level = parseInt(levelText) || 0;
      const ascImg = cells[1].querySelector('img');
      const ascendancy = ascImg ? (ascImg.getAttribute('alt') || ascImg.getAttribute('title') || '') : '';
      const life = parseInt(cells[2].textContent) || 0;
      const energyShield = parseInt(cells[3].textContent) || 0;
      const ehpText = (cells[4].textContent || '').trim();

      const dpsContainer = cells[5].querySelector('.grow, [class*="grow"]');
      const dpsText = dpsContainer ? dpsContainer.textContent.trim() : '';
      const dps = parseDps(dpsText);
      const skillImg = cells[5].querySelector('img');
      const skill = skillImg ? (skillImg.getAttribute('alt') || '') : '';

      const keystoneImgs = cells[6].querySelectorAll('img');
      const keystones = Array.from(keystoneImgs)
        .map(img => img.getAttribute('alt') || '')
        .filter(Boolean);

      results.push({
        characterName, account, id,
        level, ascendancy, life, energyShield, ehp: ehpText,
        dps, skill, keystones,
        uniqueItems: [],
        _itemsAvailable: false,
      });
    }
    return results;
  });

  // Phase 2: Scrape character pages for PoB codes (if --items flag)
  if (scrapeItems && builds.length > 0) {
    const CONCURRENCY = 5;
    process.stderr.write(JSON.stringify({status: 'scraping_items', total: builds.length}) + '\n');

    async function scrapeCharacterPage(build) {
      if (!build.account || !build.characterName) return;
      const charUrl = `https://poe.ninja/poe1/builds/mirage/character/${build.account}-${build.id}/${encodeURIComponent(build.characterName)}?timemachine=${label}`;
      try {
        const charPage = await browser.newPage();
        await charPage.setViewport({width: 1280, height: 800});
        await charPage.goto(charUrl, {waitUntil: 'networkidle2', timeout: 20000});
        await new Promise(r => setTimeout(r, 1000));

        const pob = await charPage.evaluate(() => {
          const inp = document.querySelector('input[aria-label="Import code for Path of Building"]');
          return inp ? inp.value : null;
        });

        if (pob) {
          try {
            const standard = pob.replace(/_/g, '/').replace(/-/g, '+');
            const buf = Buffer.from(standard, 'base64');
            const decompressed = zlib.inflateSync(buf).toString('utf-8');

            // Extract Items section
            const itemsStart = decompressed.indexOf('<Items');
            const itemsEnd = decompressed.indexOf('</Items>', itemsStart);
            if (itemsStart !== -1 && itemsEnd !== -1) {
              const itemsSection = decompressed.substring(itemsStart, itemsEnd + 8);
              const itemBlocks = itemsSection.split('<Item id=');
              const uniques = [];
              for (const block of itemBlocks.slice(1)) {
                const rarityMatch = block.match(/Rarity:\s*(\w+)/);
                if (rarityMatch && rarityMatch[1] === 'UNIQUE') {
                  const lines = block.split('\n');
                  const rawName = lines[2] ? lines[2].trim() : '';
                  // Decode XML entities
                  const itemName = rawName.replace(/&apos;/g, "'").replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
                  if (itemName) {
                    uniques.push({name: itemName, links: 0});
                  }
                }
              }
              if (uniques.length > 0) {
                build.uniqueItems = uniques;
                build._itemsAvailable = true;
              }
            }
          } catch(e) {
            // PoB parse failed — skip
          }
        }
        await charPage.close();
      } catch(e) {
        // Character page load failed — skip
      }
    }

    // Process in batches with concurrency limit
    for (let i = 0; i < builds.length; i += CONCURRENCY) {
      const batch = builds.slice(i, i + CONCURRENCY);
      await Promise.all(batch.map(b => scrapeCharacterPage(b)));
      process.stderr.write(JSON.stringify({status: 'items_progress', done: Math.min(i + CONCURRENCY, builds.length), total: builds.length}) + '\n');
    }
    process.stderr.write(JSON.stringify({status: 'items_done', withItems: builds.filter(b => b._itemsAvailable).length}) + '\n');
  }

  await browser.close();

  const fs = require('fs');
  fs.writeFileSync(outPath, JSON.stringify({success: true, builds, source: 'puppeteer', url, count: builds.length}, null, 2));
  process.stdout.write(JSON.stringify({status: 'ok', count: builds.length}) + '\n');
})().catch(e => {
  process.stderr.write(JSON.stringify({status: 'error', message: e.message}) + '\n');
  process.exit(1);
});
"""


def load_labels() -> list[str]:
    with open(LABELS_PATH) as f:
        return json.load(f)["labels"]


def scrape_puppeteer(label: str, ascendancy: str, scrape_items: bool = False) -> dict | None:
    """Scrape builds table using local puppeteer (headless Chromium).

    If scrape_items=True, also visits each character's detail page to
    extract PoB import code and parse unique items.
    """
    safe_asc = ascendancy.replace(" ", "_")
    out_path = os.path.join(DATA_DIR, f"builds_raw_{label}_{safe_asc}.json")

    # Resume: skip if output file already exists
    if os.path.exists(out_path):
        print(f"SKIP (exists): {out_path}")
        return None

    url = f"https://poe.ninja/poe1/builds/mirage?timemachine={label}&class={ascendancy}&sort=dps"
    print(f"Scraping (puppeteer): {url}" + (" + items" if scrape_items else ""))

    script_path = os.path.join(DATA_DIR, "_scrape_temp.js")
    with open(script_path, "w") as f:
        f.write(PUPPETEER_SCRIPT)

    # Build args: label, ascendancy, outPath, [--items]
    node_args = ["node", script_path, label, ascendancy, out_path]
    if scrape_items:
        node_args.append("--items")

    # Timeout: 90s for table only, 300s for table + items
    cmd_timeout = 300 if scrape_items else 90

    try:
        result = subprocess.run(
            node_args,
            capture_output=True, text=True, timeout=cmd_timeout,
            cwd=os.path.dirname(script_path),
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            print(f"  Puppeteer failed: {stderr[:200]}", file=sys.stderr)
            return None

        stdout = result.stdout.strip()
        try:
            parsed = json.loads(stdout)
            if parsed.get("status") == "ok":
                with_items = scrape_items and result.stderr and '"withItems"' in result.stderr
                print(f"  Extracted {parsed['count']} builds → {out_path}")
            else:
                print(f"  Unexpected output: {stdout[:200]}", file=sys.stderr)
                return None
        except json.JSONDecodeError:
            print(f"  Could not parse output: {stdout[:200]}", file=sys.stderr)
            return None

        return parsed

    except subprocess.TimeoutExpired:
        print(f"  Puppeteer timed out after {cmd_timeout}s", file=sys.stderr)
        return None
    finally:
        try:
            os.remove(script_path)
        except OSError:
            pass

# ─── Firecrawl fallback ──────────────────────────────────────────────────

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"

EXTRACT_PROMPT = """\
Extract all build entries from the builds table on this Path of Exile builds page.
For each build row, return a JSON object with these fields:
- characterName: the character name (string)
- level: character level (number)
- ascendancy: the ascendancy class (string)
- skill: the primary skill gem name displayed for this build (string)
- dps: the DPS number shown in the DPS column (number)
- life: life value (number or null)
- energyShield: energy shield value (number or null)
- uniqueItems: array of {name: string, links: number} for each unique item equipped

Return the result as a JSON array of these objects. Include ALL visible rows.\
"""


def scrape_firecrawl(label: str, ascendancy: str) -> dict | None:
    """Scrape builds using Firecrawl (paid fallback)."""
    if not FIRECRAWL_API_KEY:
        print("  FIRECRAWL_API_KEY not set — skipping Firecrawl", file=sys.stderr)
        return None

    safe_asc = ascendancy.replace(" ", "_")
    out_path = os.path.join(DATA_DIR, f"builds_raw_{label}_{safe_asc}.json")

    if os.path.exists(out_path):
        print(f"SKIP (exists): {out_path}")
        return None

    url = f"https://poe.ninja/poe1/builds/mirage?timemachine={label}&class={ascendancy}&sort=dps"
    print(f"Scraping (Firecrawl): {url}")

    payload = {
        "url": url,
        "formats": ["extract"],
        "extract": {"prompt": EXTRACT_PROMPT},
    }
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(2):
        try:
            resp = httpx.post(FIRECRAWL_SCRAPE_URL, json=payload, headers=headers, timeout=90)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("success", True):
                print(f"  Firecrawl error: {data.get('error', 'unknown')}", file=sys.stderr)
                if attempt == 0:
                    time.sleep(10)
                    continue
                return None

            with open(out_path, "w") as f:
                json.dump(data, f, indent=2)
            print(f"  Saved to {out_path}")
            return data

        except httpx.HTTPStatusError as e:
            print(f"  HTTP {e.response.status_code}", file=sys.stderr)
            if e.response.status_code == 429:
                time.sleep(60)
                continue
            if attempt == 0:
                time.sleep(10)
                continue
            return None
        except httpx.RequestError as e:
            print(f"  Request failed: {e}", file=sys.stderr)
            if attempt == 0:
                time.sleep(10)
                continue
            return None

    return None


# ─── Main ─────────────────────────────────────────────────────────────────

def scrape_with_fallback(label: str, ascendancy: str, firecrawl_only: bool = False, scrape_items: bool = False) -> dict | None:
    """Try puppeteer first, fall back to Firecrawl on failure.

    If firecrawl_only=True, skip puppeteer entirely.
    If scrape_items=True, also scrape character pages for PoB items.
    """
    if not firecrawl_only:
        result = scrape_puppeteer(label, ascendancy, scrape_items=scrape_items)
        if result is not None:
            return result
        # Check if file was written despite error signal
        safe_asc = ascendancy.replace(" ", "_")
        out_path = os.path.join(DATA_DIR, f"builds_raw_{label}_{safe_asc}.json")
        if os.path.exists(out_path):
            return {"source": "puppeteer", "count": "?"}
        print("  → Falling back to Firecrawl...", file=sys.stderr)

    return scrape_firecrawl(label, ascendancy)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Scrape poe.ninja builds")
    parser.add_argument("--label", type=str, help="Single time-machine label (e.g. day-1)")
    parser.add_argument("--class", dest="ascendancy", type=str, help="Single ascendancy")
    parser.add_argument("--all", action="store_true", help="All labels × all ascendancies")
    parser.add_argument("--firecrawl-only", action="store_true", help="Skip puppeteer, use Firecrawl directly")
    parser.add_argument("--items", action="store_true", help="Also scrape character pages for PoB item data")
    args = parser.parse_args()

    if not args.all and not args.label:
        parser.error("Must specify --label or --all")

    os.makedirs(DATA_DIR, exist_ok=True)

    labels = [args.label] if args.label else load_labels()
    ascendancies = [args.ascendancy] if args.ascendancy else ASCENDANCIES

    total = len(labels) * len(ascendancies)
    parts = ["puppeteer → Firecrawl"]
    if args.items:
        parts.append("+ items")
    method = " ".join(parts)
    print(f"Scraping {len(labels)} labels × {len(ascendancies)} ascendancies = {total} total")
    print(f"Method: {method}\n")

    done = 0
    ok = 0
    skipped = 0
    failed = 0

    for label in labels:
        for asc in ascendancies:
            # Check skip before calling
            safe_asc = asc.replace(" ", "_")
            out_path = os.path.join(DATA_DIR, f"builds_raw_{label}_{safe_asc}.json")
            if os.path.exists(out_path):
                print(f"SKIP (exists): {out_path}")
                skipped += 1
                done += 1
                continue
            result = scrape_with_fallback(label, asc, firecrawl_only=args.firecrawl_only, scrape_items=args.items)
            done += 1

            if result is not None:
                ok += 1
            else:
                # Check if file was actually created (puppeteer writes it internally)
                if os.path.exists(out_path):
                    ok += 1
                else:
                    failed += 1

            if total > 1:
                remaining = total - done
                eta = remaining * 3  # ~3s per scrape including delay
                print(f"  [{done}/{total}] ok={ok} skip={skipped} fail={failed} ~{eta}s remaining\n")
                time.sleep(1.5)  # Gentle rate limit

    print(f"\nDone. ok={ok} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    main()