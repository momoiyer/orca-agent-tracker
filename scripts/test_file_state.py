"""Private tracker-backup isolation and restoration tests."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import file_state

class FileStateTests(unittest.TestCase):
    def test_independent_backup_restore_protects_later_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory).resolve()
            with patch.object(file_state,'CODEx',base/'codex'),patch.object(file_state,'CLAUDE',base/'claude'),patch.object(file_state,'STATE',base/'private-state'):
                path=file_state.CLAUDE/'settings.json';path.parent.mkdir();path.write_bytes(b'original')
                file_state.apply({path:b'installed'},{path:b'original'})
                backup=next((file_state.STATE/'setup-backups').iterdir())
                self.assertFalse((file_state.CODEx/'setup-backups').exists())
                path.write_bytes(b'user edit')
                with self.assertRaises(ValueError):file_state.restore(backup)
                self.assertEqual(path.read_bytes(),b'user edit')
                path.write_bytes(b'installed');file_state.restore(backup)
                self.assertEqual(path.read_bytes(),b'original')

    def test_unrelated_restore_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory).resolve();path=base/'unrelated'
            with patch.object(file_state,'STATE',base/'state'):
                with self.assertRaises(ValueError):file_state.apply({path:b'new'},{path:None})
                self.assertFalse(path.exists())

if __name__=='__main__':unittest.main()
