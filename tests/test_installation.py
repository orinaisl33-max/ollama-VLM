"""Installation failures must preserve existing environments and complete source bundles."""

import importlib.util
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.setup = module("setup_mac")
        tool = patch.object(self.setup.shutil, "which", return_value="/test/ollama")
        tool.start()
        self.addCleanup(tool.stop)
        self.temp = tempfile.TemporaryDirectory(prefix="labchat setup space ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "main.py").touch()
        (self.root / "requirements-macos-hashed.lock.txt").write_text("example==1\n")

    def test_incomplete_existing_environment_is_not_overwritten(self):
        env = self.root / ".venv"
        env.mkdir()
        sentinel = env / "keep.txt"
        sentinel.write_text("keep")
        with (
            patch.object(self.setup.sys, "platform", "darwin"),
            patch.object(self.setup.sys, "version_info", (3, 11)),
            patch.object(self.setup.platform, "mac_ver", return_value=("14.0", "", "")),
            patch.object(self.setup.venv.EnvBuilder, "create") as create,
        ):
            with self.assertRaisesRegex(RuntimeError, "未覆蓋"):
                self.setup.install(self.root)
            create.assert_not_called()
        self.assertEqual(sentinel.read_text(), "keep")

    def test_wrong_interpreter_prefix_stops_before_installing_packages(self):
        env = self.root / ".venv"
        (env / "bin").mkdir(parents=True)
        (env / "bin/python").touch()
        (env / "pyvenv.cfg").touch()
        with (
            patch.object(self.setup.sys, "platform", "darwin"),
            patch.object(self.setup.sys, "version_info", (3, 11)),
            patch.object(self.setup.platform, "mac_ver", return_value=("14.0", "", "")),
            patch.object(
                self.setup.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, "/another/environment\n3.11\n"),
            ) as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "版本不符"):
                self.setup.install(self.root)
            self.assertEqual(run.call_count, 1)

    def test_missing_ollama_is_reported_before_creating_environment(self):
        with (
            patch.object(self.setup.sys, "platform", "darwin"),
            patch.object(self.setup.sys, "version_info", (3, 11)),
            patch.object(self.setup.platform, "mac_ver", return_value=("14.0", "", "")),
            patch.object(self.setup.shutil, "which", return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "找不到 Ollama"):
                self.setup.install(self.root)
        self.assertFalse((self.root / ".venv").exists())

    def test_old_macos_stops_before_environment_creation(self):
        with (
            patch.object(self.setup.sys, "platform", "darwin"),
            patch.object(self.setup.sys, "version_info", (3, 11)),
            patch.object(self.setup.platform, "mac_ver", return_value=("13.0", "", "")),
        ):
            with self.assertRaisesRegex(RuntimeError, "macOS 14"):
                self.setup.install(self.root)
        self.assertFalse((self.root / ".venv").exists())


class DoctorTests(unittest.TestCase):
    def test_missing_model_fails_only_when_required(self):
        doctor = module("check_install")
        with patch.object(doctor, "local_models", return_value=set()):
            optional = doctor.inspect()
            required = doctor.inspect(require_model=True)
        self.assertEqual(next(r["status"] for r in optional if r["check"] == "可用模型"), "WARN")
        self.assertEqual(next(r["status"] for r in required if r["check"] == "可用模型"), "FAIL")

    def test_offline_mode_never_opens_http_connection(self):
        doctor = module("check_install")
        with patch.object(doctor, "local_models") as network:
            doctor.inspect(offline=True)
            network.assert_not_called()


class PublicationBundleTests(unittest.TestCase):
    def test_source_bundle_has_installation_docs_images_and_valid_manifest(self):
        package = module("package_handoff")
        verify = module("verify_handoff")
        with tempfile.TemporaryDirectory(prefix="labchat archive space ") as directory:
            target = Path(directory)
            with patch(
                "sys.argv", ["package_handoff.py", "--target", "mac", "--output-dir", str(target)]
            ):
                package.main()
            with zipfile.ZipFile(target / "labchat-mac-handoff.zip") as archive:
                names = archive.namelist()
                self.assertIn("labchat/docs/images/app-home.png", names)
                self.assertIn("labchat/install.command", names)
                self.assertIn("labchat/docs/INSTALL_WITH_CODEX.md", names)
                self.assertIn("labchat/測試圖/README.md", names)
                self.assertEqual(
                    sum(n.startswith("labchat/測試圖/") and n.endswith(".jpg") for n in names), 6
                )
                self.assertNotIn("labchat/測試圖/機器人視角：病房跌倒偵測.jpg", names)
                self.assertFalse(
                    any("/.venv/" in n or "/models/" in n or "/.logs/" in n for n in names)
                )
                self.assertTrue(
                    (archive.getinfo("labchat/install.command").external_attr >> 16) & 0o100
                )
                archive.extractall(target / "extracted")
            self.assertGreater(verify.verify(target / "extracted/labchat"), 50)
