"""Reconstruction must verify contents and preserve existing models on errors."""

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_installation import module

ROOT = Path(__file__).resolve().parents[1]


class RebuildTests(unittest.TestCase):
    def setUp(self):
        self.restore = module("restore_environment")
        self.baseline = self.restore.manifest()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_existing_matching_models_do_not_download(self):
        name = self.baseline["profiles"]["basic"][0]
        with (
            patch.object(
                self.restore,
                "model_inventory",
                return_value={name: self.baseline["models"][name]["digest"]},
            ),
            patch.object(self.restore.subprocess, "run") as run,
        ):
            self.restore.restore_models([name], self.baseline, {})
            run.assert_not_called()

    def test_mismatch_stops_without_overwriting_existing_model(self):
        name = self.baseline["profiles"]["basic"][0]
        with (
            patch.object(self.restore, "model_inventory", return_value={name: "0" * 64}),
            patch.object(self.restore.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "digest"):
                self.restore.restore_models([name], self.baseline, {})
            run.assert_not_called()

    def test_download_is_checked_again_before_success(self):
        name = self.baseline["profiles"]["basic"][0]
        with (
            patch.object(self.restore, "model_inventory", side_effect=[{}, {name: "0" * 64}]),
            patch.object(self.restore.shutil, "which", return_value="/test/ollama"),
            patch.object(self.restore.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "digest"):
                self.restore.restore_models([name], self.baseline, {})
            self.assertEqual(run.call_args.args[0], ["/test/ollama", "pull", name])

    def test_corrupt_existing_whisper_is_preserved_without_download(self):
        folder = self.root / "models"
        folder.mkdir()
        target = folder / "ggml-small.bin"
        target.write_bytes(b"keep original")
        with patch.object(self.restore.urllib.request, "build_opener") as network:
            with self.assertRaisesRegex(RuntimeError, "校驗失敗"):
                self.restore.restore_whisper(self.root, self.baseline["whisper"])
            network.assert_not_called()
        self.assertEqual(target.read_bytes(), b"keep original")

    def fake_download(self, data, expected):
        specification = {**self.baseline["whisper"], "bytes": len(data), "sha256": expected}
        response = io.BytesIO(data)
        response.geturl = lambda: specification["url"]
        with patch.object(self.restore.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value = response
            self.restore.restore_whisper(self.root, specification)

    def test_bad_checksum_never_activates_whisper_and_cleans_partial_file(self):
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.fake_download(b"bad", "0" * 64)
        self.assertFalse((self.root / "models/ggml-small.bin").exists())
        self.assertFalse(list((self.root / "models").glob("*.part")))

    def test_verified_download_activates_expected_bytes(self):
        data = b"checked test weight"
        self.fake_download(data, hashlib.sha256(data).hexdigest())
        self.assertEqual((self.root / "models/ggml-small.bin").read_bytes(), data)

    def test_verify_only_never_installs_starts_service_or_downloads(self):
        name = self.baseline["profiles"]["basic"][0]
        with (
            patch.object(
                self.restore,
                "model_inventory",
                return_value={name: self.baseline["models"][name]["digest"]},
            ),
            patch.object(self.restore, "install") as install,
            patch.object(self.restore, "ensure_service") as service,
            patch.object(self.restore, "restore_models") as downloads,
            patch.object(self.restore.subprocess, "run"),
        ):
            self.restore.rebuild("basic", verify_only=True)
            install.assert_not_called()
            service.assert_not_called()
            downloads.assert_not_called()

    def test_existing_service_is_never_restarted_or_stopped(self):
        with (
            patch.object(self.restore, "api", return_value={"version": "0.32.1"}),
            patch.object(self.restore.subprocess, "Popen") as spawn,
        ):
            self.restore.ensure_service(self.root, {})
            spawn.assert_not_called()

    def test_failed_owned_service_is_stopped_and_reaped(self):
        with (
            patch.object(self.restore, "api", side_effect=OSError("offline")),
            patch.object(self.restore.shutil, "which", return_value="/test/ollama"),
            patch.object(self.restore.subprocess, "Popen") as spawn,
            patch.object(self.restore.time, "monotonic", side_effect=[0, 61]),
        ):
            spawn.return_value.poll.return_value = None
            with self.assertRaisesRegex(RuntimeError, "無法啟動 Ollama"):
                self.restore.ensure_service(self.root, {})
            spawn.return_value.terminate.assert_called_once()
            spawn.return_value.wait.assert_called_once_with(timeout=5)

    def test_no_confirmation_never_installs(self):
        with (
            patch.object(self.restore.sys.stdin, "isatty", return_value=False),
            patch.object(self.restore, "install") as install,
        ):
            with self.assertRaisesRegex(RuntimeError, "未確認"):
                self.restore.rebuild("basic")
            install.assert_not_called()

    def test_invalid_manifest_is_rejected(self):
        (self.root / "environment.lock.json").write_text(
            json.dumps(
                {"format": 1, "models": {}, "profiles": {"basic": ["--evil"], "full": ["--evil"]}}
            )
        )
        with self.assertRaises(ValueError):
            self.restore.manifest(self.root)

    def test_https_cannot_redirect_to_plain_http(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            self.restore.HTTPSOnlyRedirect().redirect_request(
                None, None, 302, "", {}, "http://example.com/model"
            )
