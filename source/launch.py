"""Set up a local environment and launch the dashboard. No administrator access needed."""
from pathlib import Path
import hashlib
import os
import subprocess
import sys
import venv


def main():
    base = Path(__file__).resolve().parent
    os.chdir(base)
    if sys.version_info[:2] != (3, 12):
        print('Python 3.12 is required for this tested release.')
        return 1
    try:
        import tkinter
        environment = base / '.venv'
        if sys.platform == 'win32':
            interpreter = environment / 'Scripts' / 'python.exe'
            windowed = environment / 'Scripts' / 'pythonw.exe'
        else:
            interpreter = windowed = environment / 'bin' / 'python'
        requirements = base / 'requirements.txt'
        stamp = environment / '.cyberleek-requirements'
        digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
        if not interpreter.exists():
            print('Creating a private Python environment in this folder...')
            venv.EnvBuilder(with_pip=True, symlinks=sys.platform != 'win32').create(environment)
        probe = subprocess.run([str(interpreter), '-c', 'import tkinter, websockets, certifi'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if probe.returncode or not stamp.exists() or stamp.read_text() != digest:
            print('Installing runtime packages from PyPI (first launch or changed requirements)...')
            subprocess.run([str(interpreter), '-m', 'pip', 'install', '--disable-pip-version-check',
                            '-r', str(requirements)], check=True)
            stamp.write_text(digest)
        environ = dict(os.environ)
        if sys.platform != 'win32' and 'TCL_LIBRARY' not in environ:
            # Some standalone Python builds cannot locate Tcl from inside a venv.
            try:
                environ['TCL_LIBRARY'] = tkinter.Tcl().eval('info library')
            except tkinter.TclError:
                pass
        log = base / 'startup.log'
        print('Opening Cyberleek Watcher...')
        with log.open('a', encoding='utf-8') as output:
            subprocess.Popen([str(windowed), str(base / 'cyberleek_dashboard.py'), *sys.argv[1:]],
                             cwd=str(base), stdout=output, stderr=output, env=environ,
                             start_new_session=sys.platform != 'win32')
        return 0
    except (OSError, ImportError, subprocess.CalledProcessError) as exc:
        print(f'Setup failed: {exc}')
        print('Use a writable folder and check your internet connection. See README.md.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
