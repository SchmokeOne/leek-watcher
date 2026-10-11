import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import launch


class LauncherTests(unittest.TestCase):
    def test_configured_environment_launches_without_installing(self):
        original = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as folder:
                base = Path(folder)
                scripts = base / '.venv' / 'Scripts'
                scripts.mkdir(parents=True)
                (scripts / 'python.exe').touch()
                (scripts / 'pythonw.exe').touch()
                requirements = base / 'requirements.txt'
                requirements.write_text('websockets==17.2')
                (base / '.venv' / '.cyberleek-requirements').write_text(hashlib.sha256(requirements.read_bytes()).hexdigest())
                with patch.object(launch, '__file__', str(base / 'launch.py')), patch.object(launch.sys, 'argv', ['launch.py', '--preview']), patch.object(launch.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run, patch.object(launch.subprocess, 'Popen') as spawn:
                    self.assertEqual(launch.main(), 0)
                    self.assertEqual(run.call_count, 1)
                    self.assertEqual(spawn.call_args.args[0][-1], '--preview')
                os.chdir(original)
        finally:
            os.chdir(original)

    def test_wrong_python_reports_requirement(self):
        original = os.getcwd()
        try:
            with patch.object(launch.sys, 'version_info', (3, 11)):
                self.assertEqual(launch.main(), 1)
        finally:
            os.chdir(original)


if __name__ == '__main__':
    unittest.main()
