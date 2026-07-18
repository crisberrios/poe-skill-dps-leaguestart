"""
server.py — Flask app serving processed data API + static dashboard.

GET /api/processed    → data/processed.json
GET /api/skills       → {skills: [...], windows: [...]}
All other routes      → static/index.html
"""

import json
import os
import sys
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), "..", "static"))

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
PROCESSED_PATH = os.path.join(DATA_DIR, "processed.json")


def load_processed() -> dict:
    """Load processed.json or return empty skeleton."""
    if not os.path.exists(PROCESSED_PATH):
        return {"league": "Mirage", "windows": [], "skills": {}}
    with open(PROCESSED_PATH) as f:
        return json.load(f)


@app.route("/api/processed")
def api_processed():
    data = load_processed()
    return jsonify(data)


@app.route("/api/skills")
def api_skills():
    data = load_processed()
    skills_data = data.get("skills", {})

    # Sort skills by latest-window DPS descending
    windows = data.get("windows", [])

    def sort_key(item):
        name, skill = item
        dps = 0
        for w in reversed(windows):
            dps = skill.get("dps_over_time", {}).get(w, 0)
            if dps:
                break
        return -dps

    sorted_skills = sorted(skills_data.items(), key=sort_key)
    skill_names = [name for name, _ in sorted_skills]

    return jsonify({
        "skills": skill_names,
        "windows": windows,
        "filters_applied": data.get("filters_applied", {}),
    })


@app.route("/")
@app.route("/<path:path>")
def serve_static(path="index.html"):
    static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
    if path == "" or not os.path.exists(os.path.join(static_dir, path)):
        path = "index.html"
    return send_from_directory(static_dir, path)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Start the dashboard server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
