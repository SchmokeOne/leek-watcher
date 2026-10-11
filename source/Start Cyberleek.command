#!/bin/bash
# Double-click in Finder to set up and launch Cyberleek Watcher on macOS.
cd "$(dirname "$0")" || exit 1
for candidate in python3.12 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import tkinter' >/dev/null 2>&1; then
        "$candidate" launch.py "$@" && exit 0
        break
    fi
done
if command -v uv >/dev/null 2>&1; then
    uv run --no-project --python 3.12 launch.py "$@" && exit 0
fi
echo
echo "Install Python 3.12 for macOS from https://www.python.org/downloads/macos/"
echo "(or install uv from https://docs.astral.sh/uv/), then double-click this launcher again."
echo "See README.md for details."
read -r -p "Press Return to close..."
exit 1
