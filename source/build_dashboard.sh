#!/bin/bash
# Build "Cyberleek Watcher.app" for macOS. Run from anywhere; uses the local .venv.
set -euo pipefail
cd "$(dirname "$0")"
.venv/bin/python tools/update_upstream.py || { echo 'Upstream compatibility check failed; review the adapter before building' >&2; exit 1; }
.venv/bin/python -m PyInstaller --noconfirm --clean --windowed --name 'Cyberleek Watcher' \
    --osx-bundle-identifier com.cyberleek.watcher \
    --add-data "upstream/cyberleek_watcher.py:upstream" \
    --add-data "upstream/compatibility.json:upstream" \
    cyberleek_dashboard.py
echo 'Built dist/Cyberleek Watcher.app'
