# Cyberleek Watcher

The dashboard includes three operational views:

- **Downloads / mirror attempts:** active transfers, bytes received, percentage when a source sends a total size, and session counts for completed, failed, canceled, and externally handed-off attempts. Multiple mirrors may race for one asset, so attempt counts are not unique-file counts. Active and recent attempts appear in the table; select a row for its title/status. Spoiler masking hides titles and detailed errors. Unknown total sizes show transferred MB rather than a guessed percentage.
- **Connection diagnostics:** per-endpoint request latency, status/cooldown, success/failure totals, and the age of the last successful RPC request. Double-click a row for its latest method and error. These are measurements from real requests, not extra ping requests; displayed endpoint names omit URL credentials and query parameters.
- **Website changes:** current deployment IDs and check status for each watched ArNS name, the last check and observed change times, and a content-change summary. Select a site to inspect it. **Open website history** opens saved snapshots and diffs. Status is saved per site in `website_history/website_status.json`; failed snapshot fetches are retried rather than recorded as a completed archive. The change time is when this app observed the deployment, not its publication time.

Double-click `dist/Cyberleek Watcher.exe` to open the dashboard. Python and administrator privileges are not needed to run it.

Use **Fullscreen** or **F11** to enter or leave fullscreen; **Esc** returns to the window. Fullscreen stays on the monitor containing most of the window and restores its previous position, size, and maximized state when you exit. The normal Windows maximize button also works.

Click **Appearance** to choose a preset accent, use the custom color picker, or enter a six-digit hex color. Changes apply immediately to headings, bars, the graph, activity highlights, and positive price changes. **Reset to mint** restores the original accent. Your choice is saved in `dashboard_preferences.json` beside the executable, separately from monitoring settings. Keep that file with the executable when moving it.

The layout is sized for 1920×1080. Fonts and spacing adapt to the client area in windowed, maximized, and fullscreen modes, independently of Windows DPI scaling. The default window is 1760×980 when screen space allows; the minimum window is 1280×900. All panels, the footer, and action buttons remain visible, and the activity feed scrolls within its panel.

Selected-pool market activity includes liquidity, 24-hour volume, FDV (shown separately from market cap), 24-hour buys/sells, and 5-minute, 1-hour, 6-hour, and 24-hour price changes. These are pool statistics, not sums across all markets. Missing values show a dash. The footer displays session uptime and discovered proposal, notice, Arweave ID, IPFS ID, and reserve-account counts; discovered IDs are not counts of successful downloads.

Market capitalization, price, developer reserve, links, community votes, milestones, service health, and activity appear together. Controls retain the settings in `watcher_config.json`. Startup may take a little time while public RPC services respond; the window stays responsive. A dash means data has not been observed yet. Market data shows its observation age.

The executable uses the configuration beside it. The build copies your existing configuration, including the current download location. If you move the app to another computer, update `download_dir` in that configuration. New configurations use a `leaks` folder beside the app. Keep the app in a writable folder.

Buttons export a JSON snapshot, retrieve historical assets, extract local archives, test audio, or open the downloads folder. Activity history is bounded in memory. Closing the window signals the monitoring workers to stop.

**Test sound** is available before monitoring connects and plays even if **Audio alerts** is muted. Automatic alerts honor that checkbox. Windows audio uses generated WAV chimes through the default playback device, with errors shown in the activity feed and a system-sound fallback. If the feed says playback completed but you hear nothing, check the selected Windows output device and the app's volume in Volume Mixer.

Set **Update every** to 5–3600 seconds and click **Apply** (or press Enter). The default is 15 seconds. The setting is saved in the app's `watcher_config.json` and restored on reopening. All scheduled market, on-chain state/balance/vote, Arweave, website, and revision checks start from a shared countdown. Changing the setting restarts that countdown. Requests run concurrently and may finish at different times; a worker still busy at a tick never starts an overlapping request and catches up to the latest tick when available. Startup performs initial discovery separately. WebSocket events remain immediate; UI drawing and configuration-file checks do not make data requests. Rebuilding the app preserves its saved settings.

Market price comes from the highest-liquidity Solana pool with the monitored mint as its base token. Market cap uses that pool's DexScreener `marketCap` field; if missing, the UI labels the fixed-supply estimate (price × 729,894,829.458). FDV is never substituted for market cap. The source, fetch age, and stale status are visible. Fetch age is the time since this app received the response, not a guarantee of the provider's upstream freshness. Failed refreshes preserve the last observation without adding graph points. The last-hour chart collects successful observations during this session (up to 3600 points); it does not load prior historical prices.

To run from source: `.venv\Scripts\python.exe cyberleek_dashboard.py`.
For an offline UI preview: add `--preview`.

To rebuild, create a Python 3.12 virtual environment in `.venv`, install `requirements-build.txt`, and run `build_dashboard.ps1`. The original `cyberleek_watcher.py` command-line interface remains available.

Accuracy safeguards: failed vote refreshes preserve the last complete poll and show STALE; reserve totals include small changes; partial program queries cannot trigger false disappearance alerts. RPC server errors fail over to another endpoint. Existing notices are baselined at startup. Settings write failures are reported in the activity feed.


Auto-open media defaults to OFF. With Download payloads enabled, the dashboard backfills historical on-chain links at startup, skipping manifest entries whose saved files still exist. Backfill assets retries missing files. Historical backfill suppresses browser fallback; browser-only hosts and torrents may require manual retrieval. This scans currently available on-chain links, not deleted entries or every previously published website asset.


Automated media retrieval never opens browsers or torrent clients. Download payloads controls background downloads, including startup backfill. Unsupported browser-only or encrypted sources appear as failed attempts while supported mirrors are tried. The Open CyberLeek site button opens the browser only when clicked.

Hide spoilers defaults to OFF, so poll choices and milestone names are visible. Enable it in Controls if desired.
