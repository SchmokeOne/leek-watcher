"""Load the untouched console monitor and install reviewed dashboard extensions."""
from pathlib import Path
import compatibility
import dashboard_extensions

base = Path(__file__).resolve().parent
issues = compatibility.check(base / 'upstream' / 'cyberleek_watcher.py')
if issues:
    raise RuntimeError('Upstream compatibility check failed:\n' + '\n'.join(issues))

from upstream import cyberleek_watcher as engine

dashboard_extensions.install(engine)
