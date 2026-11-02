"""Tracking-hook merge and snapshot regression checks; uses temporary files only."""
import json
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

import file_state
import tracking


class TrackingTests(unittest.TestCase):
    def test_preserves_all_unmanaged_settings_and_hooks(self):
        data = {'permissions': {'allow': ['Read']}, 'env': {'EXAMPLE': 'value'},
                'hooks': {'SessionStart': [{'matcher': 'startup', 'hooks': [
                    {'type': 'command', 'command': 'orca-existing-hook', 'timeout': 10}]}],
                    'Notification': [{'hooks': [{'type': 'command', 'command': 'notify'}]}]}}
        for provider in ('codex', 'claude'):
            result = json.loads(tracking.merge(json.dumps(data).encode(), provider))
            self.assertEqual(result['permissions'], data['permissions'])
            self.assertEqual(result['env'], data['env'])
            self.assertEqual(result['hooks']['SessionStart'][0], data['hooks']['SessionStart'][0])
            self.assertEqual(result['hooks']['Notification'], data['hooks']['Notification'])
            for event in tracking.EVENTS:
                self.assertEqual(sum(tracking.managed(h) for g in result['hooks'][event] for h in g['hooks']), 1)

    def test_reinstall_is_idempotent_and_replaces_old_commands(self):
        result = tracking.merge(None, 'codex')
        self.assertEqual(tracking.merge(result, 'codex'), result)
        with patch.object(tracking, 'command', return_value='new-path --provider codex '+tracking.MARKER):
            updated = tracking.merge(result, 'codex')
            self.assertEqual(tracking.merge(updated, 'codex'), updated)
            self.assertNotIn('telemetry.py', updated.decode())

    def test_mixed_groups_preserve_other_handlers(self):
        data = {'hooks': {'Stop': [{'matcher': 'x', 'hooks': [
            {'type': 'command', 'command': 'old '+tracking.MARKER},
            {'type': 'command', 'command': 'keep'}]}]}}
        result = json.loads(tracking.merge(json.dumps(data).encode(), 'claude'))
        self.assertEqual(result['hooks']['Stop'][0], {'matcher': 'x', 'hooks': [{'type': 'command', 'command': 'keep'}]})

    def test_invalid_existing_data_is_refused(self):
        for original in (b'[]', b'{"hooks": []}', b'{"hooks":{"Stop":{}}}', b'{"hooks":{"Stop":[{}]}}'):
            with self.subTest(original=original), self.assertRaises(ValueError):
                tracking.merge(original, 'codex')

    def test_commands_quote_interpreter_and_checkout(self):
        with patch.object(file_state, 'ROOT', Path('/tmp/a folder/quote\'s')), patch.object(tracking.sys, 'executable', '/tmp/python interpreter'):
            generated = tracking.command('claude')
            args = shlex.split(generated.split(' >/dev/null')[0])
            self.assertEqual(args, [str(Path('/tmp/python interpreter').resolve()), str(Path("/tmp/a folder/quote's/dashboard/telemetry.py").resolve()), '--provider', 'claude'])
            self.assertTrue(generated.endswith(' '+tracking.MARKER))

    def test_snapshot_race_and_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            with patch.object(file_state, 'CODEx', base/'codex'), patch.object(file_state, 'CLAUDE', base/'claude'), patch.object(file_state, 'STATE', base/'state'):
                claude = file_state.CLAUDE/'settings.json'
                claude.parent.mkdir()
                original = b'{"example":true}\n'
                claude.write_bytes(original)
                changes, originals = tracking.plan()
                claude.write_bytes(b'{"example":"concurrent edit"}\n')
                with self.assertRaises(ValueError):
                    file_state.apply(changes, originals)
                self.assertEqual(claude.read_bytes(), b'{"example":"concurrent edit"}\n')
                self.assertFalse((file_state.CODEx/'hooks.json').exists())
                claude.write_bytes(original)
                changes, originals = tracking.plan()
                file_state.apply(changes, originals)
                self.assertEqual(tracking.plan()[0], {})
                backup = sorted((file_state.STATE/'setup-backups').iterdir())[-1]
                file_state.restore(backup)
                self.assertEqual(claude.read_bytes(), original)
                self.assertFalse((file_state.CODEx/'hooks.json').exists())


if __name__ == '__main__':
    unittest.main()
