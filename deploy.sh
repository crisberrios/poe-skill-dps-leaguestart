#!/usr/bin/env bash
set -euo pipefail

# Deploy to GitHub Pages from /docs
# 1. Run: python src/process.py            (generate data/processed.json)
# 2. Run: bash deploy.sh                   (copy files to docs/)
# 3. git add docs && git commit -m "deploy" && git push
# 4. GitHub: Settings > Pages > Branch: main, folder: /docs

DATA="data/processed.json"
if [ ! -f "$DATA" ]; then
  echo "ERROR: $DATA not found. Run 'python src/process.py' first."
  exit 1
fi

echo "==> Copying static files to docs/"
mkdir -p docs
cp static/index.html docs/
cp static/dashboard.js docs/
cp "$DATA" docs/processed.json

echo "==> Done. Commit and push:"
echo "   git add docs/"
echo "   git commit -m 'deploy: update static site'"
echo "   git push origin main"
echo ""
echo "   Then enable Pages: Settings > Pages > Branch: main, folder: /docs"