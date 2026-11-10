import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

spec = importlib.util.spec_from_file_location("trial", Path(__file__).resolve().parents[2]/"tools/ws30_multi_wifi_trial.py")
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class TrialTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.args = SimpleNamespace(phase="install", state=self.directory)
        self.session = SimpleNamespace(
            identity={"firmwareVersion": 102},
            export=Mock(return_value={"session_secret": "synthetic-secret"}),
            read_server=AsyncMock(return_value={"host": "scales.example.com"}),
            install=AsyncMock(side_effect=TimeoutError),
        )

    async def test_uncertain_ota_is_journaled_and_never_replayed(self):
        output = io.StringIO()
        with patch.object(trial, "raw_wifi", AsyncMock(return_value=b"synthetic-private-key")), \
             patch.object(trial, "inspect", return_value={"sha256": trial.SHA256}), redirect_stdout(output):
            with self.assertRaises(TimeoutError):
                await trial.act(self.session, self.args, {"model": "WBS03"}, b"image")
            journal = json.loads((self.directory/"install.json").read_text())
            self.assertEqual(journal["state"], "uncertain")
            with self.assertRaisesRegex(ValueError, "journal exists"):
                await trial.act(self.session, self.args, {"model": "WBS03"}, b"image")
        self.session.install.assert_awaited_once()
        self.assertNotIn("synthetic", output.getvalue())

    async def test_wrong_source_version_never_starts_ota(self):
        self.session.identity["firmwareVersion"] = 921
        with self.assertRaisesRegex(ValueError, "Expected source"):
            await trial.act(self.session, self.args, {}, b"image")
        self.session.install.assert_not_called()
        self.assertFalse((self.directory/"install.json").exists())

    def test_journal_create_is_exclusive(self):
        path = self.directory/"install.json"
        trial.save(path, {"state": "starting"})
        with self.assertRaises(FileExistsError):
            trial.save(path, {"state": "second-process"})
        self.assertEqual(json.loads(path.read_text())["state"], "starting")

    def test_bad_candidate_digest_rejected_before_connection(self):
        path = self.directory/"candidate.bin"
        path.write_bytes(b"synthetic image")
        with patch.object(trial, "inspect", return_value={"version": 1103, "sha256": "0"*64}):
            with self.assertRaisesRegex(ValueError, "exact trial"):
                trial.checked_image(path)


if __name__ == "__main__":
    unittest.main()
