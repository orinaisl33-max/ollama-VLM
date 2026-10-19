"""Regression checks for local-only endpoints and untrusted model text."""

import json
import unittest

from labchat.client import ChatClient
from labchat.grounding import parse_boxes
from labchat.protocol import ProtocolError, StreamDecoder
from labchat.security import clean_label, local_base_url


class SecurityTests(unittest.TestCase):
    def test_loopback_endpoints_only(self):
        for value in ("http://127.0.0.1:11434", "http://localhost:1234/", "http://[::1]:11434"):
            self.assertEqual(local_base_url(value), value.rstrip("/"))
        for value in (
            "https://127.0.0.1",
            "http://0.0.0.0:11434",
            "http://example.com",
            "http://127.0.0.1.evil",
            "http://user@127.0.0.1",
            "http://127.0.0.1/api",
            "http://127.0.0.1?redirect=evil",
            "http://127.0.0.1#fragment",
            "file:///tmp/file",
            "http://127.0.0.1:99999",
            None,
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                local_base_url(value)

    def test_endpoint_change_cannot_redirect_outside_machine(self):
        client = ChatClient()
        try:
            with self.assertRaises(ValueError):
                client.base_url = "http://example.com"
            self.assertEqual(client.base_url, "http://127.0.0.1:11434")
        finally:
            client.shutdown()
            client.deleteLater()

    def test_shutdown_prevents_new_network_requests(self):
        client = ChatClient()
        client.shutdown()
        with self.assertRaises(RuntimeError):
            client.start("model", [])
        client.deleteLater()

    def test_invalid_unicode_model_text_is_recoverable(self):
        for payload in ({"message": {"content": "\ud800"}}, {"error": "\udfff"}):
            with self.assertRaises(ProtocolError):
                StreamDecoder().feed(json.dumps(payload).encode() + b"\n")

    def test_bidi_control_and_surrogate_characters_removed_from_labels(self):
        self.assertEqual(clean_label("蘋\u202e果\x00\ud800"), "蘋果")
        self.assertEqual(len(clean_label("字" * 100)), 60)
        self.assertEqual(
            parse_boxes('{"objects":[{"label":"蘋\\u202e果","bbox":[0,0,10,10]}]}')[0].label, "蘋果"
        )
        with self.assertRaises(ValueError):
            parse_boxes('{"objects":[{"label":"\\u202e","bbox":[0,0,10,10]}]}')
