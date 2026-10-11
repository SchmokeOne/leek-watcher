import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import compatibility
import dashboard_adapter
import cyberleek_watcher


class UpstreamTests(unittest.TestCase):
    def test_installed_original_passes(self):
        self.assertEqual(compatibility.check(Path('upstream/cyberleek_watcher.py')), [])

    def test_legacy_import_shares_exact_engine_state(self):
        self.assertIs(cyberleek_watcher, dashboard_adapter.engine)
        with patch.object(cyberleek_watcher, '_poll_interval', 7):
            self.assertEqual(dashboard_adapter.engine._poll_interval, 7)

    def test_changed_override_requires_review(self):
        original = Path('upstream/cyberleek_watcher.py').read_text(encoding='utf-8')
        tree = ast.parse(original)
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'rpc_call')
        lines = original.splitlines()
        lines.insert(node.body[0].lineno - 1, '    raise RuntimeError("changed implementation")')
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / 'candidate.py'
            candidate.write_text('\n'.join(lines), encoding='utf-8')
            self.assertTrue(any('rpc_call' in issue for issue in compatibility.check(candidate)))

    def test_nonconflicting_addition_does_not_require_review(self):
        original = Path('upstream/cyberleek_watcher.py').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / 'candidate.py'
            candidate.write_text(original + '\ndef upstream_new_feature():\n    return 42\n', encoding='utf-8')
            self.assertEqual(compatibility.check(candidate), [])
