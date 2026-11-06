#!/bin/bash
# Rebuild and publish Award Radar to gh-pages
set -e
cd /workspace/award-radar
python3 build.py
cd site
touch .nojekyll
git add -A
git commit -qm "site $(date +%F)" || true
git push -q origin gh-pages
