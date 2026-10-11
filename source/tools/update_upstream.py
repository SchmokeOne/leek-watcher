"""Stage, statically check, and install original-script updates after maintainer review."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import urllib.request

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from compatibility import check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true', help='Download latest script as a candidate; do not install it')
    parser.add_argument('--apply', type=Path, help='Install a reviewed candidate only if static checks pass')
    parser.add_argument('--check', type=Path, help='Check a candidate; defaults to the installed original')
    args = parser.parse_args()
    original = BASE / 'upstream' / 'cyberleek_watcher.py'
    candidate = args.apply or args.check or original
    if args.fetch:
        if args.apply:
            parser.error('Fetch and apply are separate review steps')
        candidate = BASE / 'upstream' / 'candidate.py'
        url = 'https://gist.githubusercontent.com/wpenistone/22d418d7160e2ca6eb0c5f95283aae71/raw/cyberleek_watcher.py'
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Cyberleek-Watcher'}), timeout=30) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError('Candidate is unexpectedly large')
        candidate.write_bytes(body)
        print('Downloaded candidate for review:', candidate.name)
    conflicts = check(candidate)
    if conflicts:
        print('Update needs adapter review; installed original was not changed:')
        for conflict in conflicts:
            print(' -', conflict)
        return 1
    print('Static compatibility checks passed. Run the test suite and manual UI checks too.')
    if args.apply:
        if candidate.resolve() == original.resolve():
            return 0
        backups = BASE / 'tools' / 'backups'
        backups.mkdir(exist_ok=True)
        old_hash = hashlib.sha256(original.read_bytes()).hexdigest()
        shutil.copy2(original, backups / (old_hash + '.py'))
        shutil.copy2(candidate, original)
        (BASE / 'upstream' / 'revision.json').write_text(json.dumps({'sha256': hashlib.sha256(original.read_bytes()).hexdigest(), 'source_url': 'https://gist.github.com/wpenistone/22d418d7160e2ca6eb0c5f95283aae71'}, indent=2), encoding='utf-8')
        print('Reviewed candidate installed. Previous script was backed up. Test before building.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print('Update failed:', exc)
        raise SystemExit(1)
