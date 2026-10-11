# Updating the original monitor

The file `upstream/cyberleek_watcher.py` is the untouched original by Penistone.
The dashboard imports it through `dashboard_adapter.py`; reviewed overrides and
extra dashboard features are in `dashboard_extensions.py`.

From the source folder, after installing dependencies:

```powershell
.\.venv\Scripts\python.exe tools/update_upstream.py --fetch
```

This downloads `upstream/candidate.py` for inspection. It does not execute or
install the candidate. Alternatively, place a downloaded script anywhere and run:

```powershell
.\.venv\Scripts\python.exe tools/update_upstream.py --check path/to/candidate.py
```

If static checks pass, review the diff, stop the app, then install the candidate:

```powershell
.\.venv\Scripts\python.exe tools/update_upstream.py --apply upstream/candidate.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe cyberleek_dashboard.py --preview
```

Verify live data, downloads, settings, audio, and shutdown before building a release.
Old upstream source is backed up under `tools/backups/` during installation.
If checks report conflicts, the original stays unchanged. Review the affected
extension and upstream function, port the required behavior, update that node's
reviewed AST hash in `upstream/compatibility.json`, and test again. Do not change
hashes simply to silence conflicts. Interface checks cannot prove runtime behavior.

The adapter preserves all current dashboard features by overriding selected
engine functions in the original module's namespace. This means updates to an
overridden function need review and may need merging. Compatible unchanged
functions can receive upstream body changes without rewriting the dashboard.
This is a reviewed extension layer, not an unrestricted drop-in guarantee.

Builds run the static compatibility check automatically. Prebuilt EXEs include
the reviewed original; they never download or execute upstream updates themselves.
Users update by replacing the EXE while retaining the adjacent `data` folder.
