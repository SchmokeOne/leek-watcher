# Cyberleek Watcher

**Original console script created by Penistone (GitHub: [wpenistone](https://github.com/wpenistone)).**
This desktop dashboard builds on his original Python monitoring and asset retrieval work.
[View the original console script](https://gist.github.com/wpenistone/22d418d7160e2ca6eb0c5f95283aae71).

Cyberleek Watcher is a Windows dashboard for following Cyberleek market data,
community polls, milestones, on-chain activity, website changes, and media downloads.

## Download and run

1. Open this repository's **Releases** page and download the attached **Cyberleek Watcher.exe**.
2. Put it in a writable folder and double-click it. No Python installation is required.
3. Keep an internet connection available for live monitoring and downloads.

The prebuilt application targets **64-bit Windows**. It creates a `data` folder
beside the executable for settings, downloaded files, and website history.
If you download the repository's source archive, extract it before running anything.

## Features

- Market capitalization, token price, liquidity, volume, and trading activity.
- A session market-cap chart and milestone progress.
- Community poll results sorted from highest share to lowest.
- Reserve balances, connection diagnostics, and website change tracking.
- Background media downloads and historical backfill for missing files.
- Adjustable refresh interval, fullscreen on the current monitor, and custom accent colors.
- A Credits panel linking to the original creator's script.

## Defaults and controls

The refresh interval defaults to **15 seconds** and can be set from **5 to 3600 seconds**.
Settings and colors are saved between sessions. **Hide spoilers** and **Automatically
open media** default to off, so actual poll and milestone names are visible and
saved media does not open automatically.

With **Download payloads** enabled, the app attempts missing historical downloads
at startup and downloads newly discovered media in the background. **Backfill assets**
retries missing files. Automated retrieval never opens browsers or torrent clients;
the **Open CyberLeek site** button opens the browser only when clicked.

## Data and download limitations

Estimated market cap uses the latest DexScreener pool price multiplied by the
last successfully fetched CoinGecko circulating supply. Price follows the selected
refresh interval; supply refreshes independently with a 61-second delay between requests, including
retries after failures. Supply age and stale status are displayed.
CoinGecko outages do not freeze price updates. Until supply is available, market
cap is unavailable rather than replaced by FDV or a hardcoded supply estimate.
The value may differ from CoinGecko's reported cap because its aggregated price
can differ from the selected pool's price. Providers may cache or rate-limit data.

Historical backfill scans currently available on-chain links, not deleted entries
or every asset ever posted on a website. Some hosts require unsupported browser
workflows, authentication, or client-side decryption. Those attempts are reported
as failures while supported mirrors are tried.

Downloaded media comes from external sources. The app may automatically extract
archives; inspect downloaded content before opening or executing it. Public RPC
and storage services can be unavailable or rate-limited.

## Run from source

Install **Python 3.12 for Windows**, including Tcl/Tk and the Python launcher.
Open the `source` folder and double-click **Start Cyberleek.cmd**. On first launch,
it creates a local `.venv` and installs the pinned runtime dependencies from PyPI.
No administrator access is required.

Alternatively, open PowerShell in the `source` folder and run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe cyberleek_dashboard.py
```

Source runs store settings and downloads in the source folder. The original
command-line interface remains available through `cyberleek_watcher.py`.

## Compile your own executable

Open PowerShell in the `source` folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File .\build_dashboard.ps1
```

The compiled executable appears at **`source/dist/Cyberleek Watcher.exe`**.
You can edit the Python files before building your own version.

To run the included tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Troubleshooting

Startup discovery may take time while public services respond. Check the
connection diagnostics and activity feed for failures. Use a writable folder
if settings or downloads cannot be saved. For source setup errors, run
`py -3.12 launch.py` and inspect `startup.log`.

If security software flags a release, review the source and the detection details;
do not disable antivirus merely to run the application. Source availability and
successful tests do not constitute an independent security audit.

## Credits and license

Thanks to **Penistone / wpenistone** for the original console monitor.
Additional attribution is included in `source/CREDITS.md`.
See `source/LICENSE` for the license supplied with the dashboard additions.
Upstream code, third-party dependencies, and external media remain subject to
their respective authors' rights and applicable licenses.

## Original script and update compatibility

The source is separated into:

```text
source/
  cyberleek_dashboard.py      Desktop UI
  dashboard_adapter.py       Loads and checks the original monitor
  dashboard_extensions.py    Dashboard features and reviewed engine overrides
  compatibility.py           Static upstream compatibility checks
  cyberleek_watcher.py        Legacy CLI/import entry point
  upstream/                  Untouched original script and compatibility baseline
  tools/                     Upstream update utility and detailed instructions
  tests/                     Regression tests
```

Penistone's original script is kept unchanged in `upstream/cyberleek_watcher.py`.
Updates are staged for review instead of executed automatically. From the source folder:

```powershell
.\.venv\Scripts\python.exe tools/update_upstream.py --fetch
```

Read `tools/README.md` for checking, reviewing, installing, and testing a candidate.
Compatible updates can be installed without changing the UI. Changes to functions
that the dashboard overrides require reviewing and possibly merging the extension.
Static checks help identify conflicts; they do not replace runtime tests.
The build script checks compatibility before compiling. To update a prebuilt app,
replace its executable while keeping its `data` folder.
