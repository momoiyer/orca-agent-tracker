"""Portable setup edge cases; no installed files or live services are changed."""
import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
import desk_service

class PortabilityTests(unittest.TestCase):
    def test_remove_refuses_unrelated_service(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"service.plist"
            original=plistlib.dumps({"Label":desk_service.LABEL,"ProgramArguments":["/some/other/program"]})
            path.write_bytes(original)
            with patch.object(desk_service,"PLIST",path), patch.object(desk_service.sys,"platform","darwin"), patch.object(desk_service.sys,"argv",["desk_service.py","--remove"]), patch.object(desk_service.subprocess,"run") as run:
                with self.assertRaises(SystemExit):desk_service.main()
                run.assert_not_called()
            self.assertEqual(path.read_bytes(),original)


if __name__=="__main__":unittest.main()
