import json
import socket
import struct
import threading
import unittest

from reader_protocol import MAX_MESSAGE, VERSION, receive_message, send_message, validate_request


class ProtocolTests(unittest.TestCase):
    def test_partial_reads_and_unicode_newlines(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        expected = {"text": "Hello\n世界" * 2000}
        data = json.dumps(expected).encode()
        frame = struct.pack("!I", len(data)) + data

        def writer():
            for index in range(0, len(frame), 7):
                left.sendall(frame[index:index + 7])

        thread = threading.Thread(target=writer)
        thread.start()
        self.assertEqual(receive_message(right), expected)
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_rejects_oversize_truncated_and_non_object(self):
        for frame in (struct.pack("!I", MAX_MESSAGE + 1), struct.pack("!I", 10) + b"{}", struct.pack("!I", 2) + b"[]"):
            left, right = socket.socketpair()
            with left, right:
                left.sendall(frame)
                left.shutdown(socket.SHUT_WR)
                with self.assertRaises(ValueError):
                    receive_message(right)

    def test_validation_and_outgoing_limit(self):
        request = {"version": VERSION, "type": "speak", "request_id": "id", "text": "hello",
                   "voice": "af_heart", "speed": 0.95, "speech_language": "en-us", "model_dir": "/tmp/models"}
        self.assertEqual(validate_request(request), request)
        for changes in ({"speed": float("nan")}, {"speed": True}, {"speed": 3}, {"text": " "}, {"voice": []}, {"version": 0}, {"type": "nope"}):
            with self.assertRaises(ValueError):
                validate_request({**request, **changes})
        with self.assertRaises(ValueError):
            send_message(None, {"text": "x" * MAX_MESSAGE})
