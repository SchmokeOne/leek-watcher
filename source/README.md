# Cyberleek Watcher

An open-source Windows dashboard for Cyberleek market data, community polls,
milestone progress, on-chain changes, website changes, and background media downloads.

## Start in three steps

1. Install **Python 3.12 for Windows** from https://www.python.org/downloads/windows/.
   Keep the Tcl/Tk and Python launcher components enabled. No other downloads are required.
2. Extract the entire source ZIP into a writable folder, such as Documents.
3. Double-click **Start Cyberleek.cmd**.

The first launch creates `.venv` in the app folder and installs the two pinned
runtime packages from PyPI: `websockets` and `certifi`. Internet is required for
setup and live monitoring. Later launches reuse the environment and open the UI
without a persistent console. No administrator access or EXE build is needed.
All application and setup code is included for inspection.

## Settings and downloads

Settings are stored beside the application in `watcher_config.json`; colors are
stored in `dashboard_preferences.json`. New installations refresh every 15 seconds,
show poll and milestone names, and save media without automatically opening it.
Automated downloads never launch browsers or torrent clients. Historical backfill
retrieves missing media referenced by currently available on-chain links. Some
hosts require unsupported authentication or decryption; those attempts are reported
as failures and other mirrors are tried. Downloaded content comes from external
sources and is separate from this application's source license.

See README-dashboard.md for all dashboard controls and data limitations.

## Troubleshooting

Run `py -3.12 launch.py` in this folder to see setup errors. Startup errors are
written to `startup.log`. If Python isn't detected, verify that Python 3.12 and
the Python launcher are installed. Re-extract the package if either Python source
file is missing. Package installation uses PyPI and may be blocked by your network.

## Development

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe cyberleek_dashboard.py
.\.venv\Scripts\python.exe -m unittest discover -v
```

The original command-line monitor is `cyberleek_watcher.py`.
Executable builds additionally require `requirements-build.txt` and `build_dashboard.ps1`.

## License

Application source is provided under the MIT License. Third-party dependencies
retain their own licenses. The license does not grant rights to external media.

## Packaged release

Run the executable in the parent folder; Python is not required.
Settings and downloads are stored in a data folder created on first launch.
Original console script by Penistone (wpenistone); see CREDITS.md.
