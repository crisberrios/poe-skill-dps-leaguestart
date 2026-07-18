# PoE Skill DPS Leaguestart

Chart.js dashboard tracking skill DPS trends across PoE 3.28 Mirage league, powered by [poe.ninja](https://poe.ninja) time-machine data.

**Live:** [https://crisberrios.github.io/poe-skill-dps-leaguestart](https://crisberrios.github.io/poe-skill-dps-leaguestart)

## Pipeline

```
fetch_index_state.py → fetch_builds.py → fetch_economy.py → process.py → processed.json → static site
```

| Step | What | Source |
|------|------|--------|
| `fetch_index_state.py` | Discover available time-machine labels | poe.ninja |
| `fetch_builds.py` | Scrape top builds per label × ascendancy | poe.ninja builds table (Puppeteer or Firecrawl) |
| `fetch_economy.py` | Download unique item & Divine Orb price history | Keepers league dump |
| `process.py` | Aggregate top-20 DPS avgs, filter by T0/T1/divine cap, build ascendancy index | — |

### Views

Four filter presets in `processed.json`:

| View | T0 uniques | T1 uniques | Divine cap |
|------|-----------|-----------|------------|
| T0 + T1 + Divine Cap | excluded | excluded | enforced |
| T0 + T1 No Cap | excluded | excluded | disabled |
| T0 Only + Cap | excluded | included | enforced |
| Unfiltered | included | included | disabled |

## Dashboard Features

- **Time range** — slide through hour-3 to week-19
- **Ascendancy filter** — narrow to one class
- **View presets** — toggle T0/T1 filtering and divine budget cap
- **Skill chips** — sorted by DPS at the latest window in range; click to toggle chart lines
- **Chart** — DPS over time for selected skills (Chart.js)
- **Sortable table** — latest DPS, peak DPS, build count per window

## Develop Locally

```bash
# Install dependencies
pip install -r requirements.txt      # Python (Flask, httpx, etc.)
npm install                           # Puppeteer for fetch_builds.py

# Run the full pipeline (takes ~30 min — scrapes all labels × ascendancies)
python src/fetch_index_state.py
python src/fetch_economy.py
python src/fetch_builds.py --all
python src/process.py

# Start the Flask dev server
python src/server.py --port 5000
```

## Deploy

```bash
python src/process.py
bash deploy.sh
git add docs/
git commit -m 'deploy: update static site'
git push origin main
```

Requires GitHub Pages configured to serve from `/docs` on `main`.
