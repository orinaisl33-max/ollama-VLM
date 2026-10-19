"""Download tests use fake QProcess; no models are downloaded."""

import sys
import unittest
from unittest.mock import patch

from PySide6.QtCore import QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from labchat.config import MODELS
from labchat.model_settings import ModelSettings

APP = QApplication.instance() or QApplication([])


class ModelSettingsTests(unittest.TestCase):
    def setUp(self):
        self.dialog = ModelSettings()
        self.addCleanup(self.dialog.deleteLater)
        self.addCleanup(self.dialog.shutdown)

    def test_all_commands_are_whitelisted_and_installed_not_downloaded(self):
        dialog = self.dialog
        for index, model in enumerate(MODELS):
            dialog.models.setCurrentIndex(index)
            self.assertEqual(dialog.command.text(), "ollama pull " + model.identifier)
        dialog.set_installed({dialog.models.currentData()})
        self.assertFalse(dialog.download.isEnabled())
        with patch.object(dialog.process, "start") as start:
            dialog.start_download()
            start.assert_not_called()

    def test_unknown_service_and_missing_binary_do_not_start(self):
        dialog = self.dialog
        with patch.object(dialog.process, "start") as start:
            dialog.start_download()
            start.assert_not_called()
        dialog.set_installed(set())
        with (
            patch("labchat.model_settings.shutil.which", return_value=None),
            patch("labchat.model_settings.Path.is_file", return_value=False),
            patch.object(dialog.process, "start") as start,
        ):
            dialog.start_download()
            start.assert_not_called()
            self.assertIn("找不到 Ollama", dialog.status.text())

    def test_start_is_local_no_shell_and_no_duplicate(self):
        dialog = self.dialog
        dialog.set_installed(set())
        with (
            patch("labchat.model_settings.shutil.which", return_value="/fake/ollama"),
            patch(
                "labchat.model_settings.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch.object(dialog.process, "start") as start,
            patch.object(dialog.process, "kill"),
        ):
            dialog.start_download()
            dialog.start_download()
            start.assert_called_once_with("/fake/ollama", ["pull", MODELS[0].identifier])
            self.assertEqual(
                dialog.process.processEnvironment().value("OLLAMA_HOST"), "127.0.0.1:11434"
            )
            self.assertTrue(dialog.downloading)
            self.assertFalse(dialog.models.isEnabled())
            dialog.cancel()
            dialog._finished(-1, QProcess.ExitStatus.CrashExit)
            self.assertFalse(dialog.downloading)
            self.assertFalse(dialog.timer.isActive())

    def test_failure_and_timeout_recover(self):
        dialog = self.dialog
        dialog.set_installed(set())
        dialog.downloading = True
        dialog.cancel("測試逾時")
        dialog._finished(-1, QProcess.ExitStatus.CrashExit)
        self.assertIn("測試逾時", dialog.status.text())
        self.assertTrue(dialog.download.isEnabled())

    def test_success_requires_status_refresh_before_next_download(self):
        dialog = self.dialog
        dialog.set_installed(set())
        dialog.downloading = True
        refreshed = []
        dialog.refresh_requested.connect(lambda: refreshed.append(True))
        dialog._finished(0, QProcess.ExitStatus.NormalExit)
        self.assertEqual(refreshed, [True])
        self.assertIsNone(dialog.installed)
        self.assertFalse(dialog.download.isEnabled())

    def test_cancel_real_fake_process_does_not_leave_download_active(self):
        dialog = self.dialog
        dialog.set_installed(set())
        real_start = dialog.process.start

        def fake_start(_program, _args):
            real_start(sys.executable, ["-c", "import time; time.sleep(10)"])

        with (
            patch("labchat.model_settings.shutil.which", return_value="/fake/ollama"),
            patch(
                "labchat.model_settings.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch.object(dialog.process, "start", side_effect=fake_start),
        ):
            dialog.start_download()
            QTest.qWait(30)
            dialog.cancel()
            for _ in range(100):
                if not dialog.downloading:
                    break
                QTest.qWait(10)
        self.assertFalse(dialog.downloading)
        self.assertFalse(dialog.timer.isActive())
        self.assertEqual(dialog.process.state(), QProcess.ProcessState.NotRunning)
        self.assertTrue(dialog.models.isEnabled())

    def test_failed_process_start_releases_download_state(self):
        dialog = self.dialog
        dialog.set_installed(set())
        with (
            patch("labchat.model_settings.shutil.which", return_value="/does/not/exist/ollama"),
            patch(
                "labchat.model_settings.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
        ):
            dialog.start_download()
            for _ in range(50):
                if not dialog.downloading:
                    break
                QTest.qWait(10)
        self.assertFalse(dialog.downloading)
        self.assertFalse(dialog.timer.isActive())
        self.assertTrue(dialog.download.isEnabled())

    def test_close_requests_cancel_during_download(self):
        dialog = self.dialog
        dialog.downloading = True
        with patch.object(dialog.process, "kill") as kill:
            dialog.reject()
            kill.assert_called_once()
            self.assertTrue(dialog.cancelled)
        dialog.downloading = False
