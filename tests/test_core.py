import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtGui import QColor, QImage

from labchat.config import MAX_HISTORY_CHARS, build_messages, retain_turn
from labchat.images import prepare_image
from labchat.protocol import ProtocolError, StreamDecoder


class ProtocolTests(unittest.TestCase):
    def test_split_utf8_crlf_and_final_line(self):
        wire = (
            json.dumps({"message": {"content": "繁體中文"}}, ensure_ascii=False).encode() + b"\r\n"
        )
        wire += b'{"done":true}'
        decoder, events = StreamDecoder(), []
        for value in wire:
            events += decoder.feed(bytes([value]))
        events += decoder.feed(b"", final=True)
        self.assertEqual(events[0]["message"]["content"], "繁體中文")
        self.assertTrue(events[1]["done"])

    def test_reject_invalid_json_and_shapes(self):
        for line in (
            b"bad\n",
            b"[]\n",
            b'{"message":null}\n',
            b'{"message":{"content":4}}\n',
            b'{"done":"true"}\n',
            b"{}\n",
            b'{"error":null}\n',
            b"\xff\n",
        ):
            with self.subTest(line=line), self.assertRaises(ProtocolError):
                StreamDecoder().feed(line)

    def test_bound_unterminated_and_complete_lines(self):
        with patch("labchat.protocol.MAX_LINE_BYTES", 8):
            for data in (b"x" * 9, b"x" * 9 + b"\n"):
                with self.assertRaises(ProtocolError):
                    StreamDecoder().feed(data)

    def test_bound_total_stream(self):
        with patch("labchat.protocol.MAX_STREAM_BYTES", 3):
            with self.assertRaises(ProtocolError):
                StreamDecoder().feed(b"    ")

    def test_deeply_nested_json_reports_protocol_error(self):
        with self.assertRaises(ProtocolError):
            StreamDecoder().feed(b'{"message":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}\n")


class HistoryTests(unittest.TestCase):
    def test_no_images_in_followup_history_and_no_mutation(self):
        history = retain_turn([], "問題", "答案")
        messages = build_messages(history, "看圖", "encoded")
        self.assertEqual(messages[-1]["images"], ["encoded"])
        self.assertEqual(
            history, [{"role": "user", "content": "問題"}, {"role": "assistant", "content": "答案"}]
        )
        self.assertNotIn("images", build_messages(history, "後續", None)[-1])
        self.assertIn("本次沒有附加圖片", build_messages(history, "後續", None)[0]["content"])

    def test_bounded_complete_pairs(self):
        history = []
        for i in range(10):
            history = retain_turn(history, str(i) * 1000, "答" * 1000)
        self.assertEqual(len(history), 6)
        self.assertLessEqual(sum(len(m["content"]) for m in history), MAX_HISTORY_CHARS)
        messages = build_messages(history, "問" * 4000, None)
        self.assertEqual(
            [m["role"] for m in messages[1:]], ["user", "assistant", "user", "assistant", "user"]
        )

    def test_oversize_pair_dropped_without_orphan(self):
        self.assertEqual(retain_turn([], "問", "答" * (MAX_HISTORY_CHARS + 1)), [])

    def test_new_image_does_not_reuse_old_visual_claims(self):
        history = [
            {"role": "user", "content": "先前圖片"},
            {"role": "assistant", "content": "先前不可靠的數量結論"},
        ]
        messages = build_messages(history, "分析新的圖片", "encoded-image")
        self.assertEqual(len(messages), 2)
        self.assertNotIn("先前不可靠的數量結論", str(messages))
        self.assertEqual(messages[-1]["images"], ["encoded-image"])


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "image.png"

    def test_resize_and_do_not_upscale(self):
        for width, expected in ((2048, 1024), (32, 32)):
            image = QImage(width, 128, QImage.Format.Format_RGB32)
            image.fill(QColor("red"))
            self.assertTrue(image.save(str(self.path)))
            result = QImage.fromData(base64.b64decode(prepare_image(str(self.path))))
            self.assertEqual(result.width(), expected)

    def test_missing_corrupt_and_wrong_format(self):
        with self.assertRaises(ValueError):
            prepare_image(str(self.path))
        self.path.write_text("not an image")
        with self.assertRaises(ValueError):
            prepare_image(str(self.path))
        image = QImage(4, 4, QImage.Format.Format_RGB32)
        image.fill(QColor("blue"))
        image.save(str(self.path), "BMP")
        with self.assertRaises(ValueError):
            prepare_image(str(self.path))

    def test_pixel_and_file_limits(self):
        image = QImage(4, 4, QImage.Format.Format_RGB32)
        image.save(str(self.path))
        with patch("labchat.images.MAX_PIXELS", 4), self.assertRaises(ValueError):
            prepare_image(str(self.path))
        with patch("labchat.images.MAX_FILE_BYTES", 1), self.assertRaises(ValueError):
            prepare_image(str(self.path))
