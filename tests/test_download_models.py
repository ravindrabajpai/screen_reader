import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import download_models


class DownloadTests(unittest.TestCase):
    def test_verified_download_replaces_destination(self):
        data = b"verified model"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "model.onnx"
            target.write_bytes(b"previous model")
            with patch.object(download_models.urllib.request, "urlopen", return_value=io.BytesIO(data)):
                download_models.download("https://example.invalid/model", target, hashlib.sha256(data).hexdigest())
            self.assertEqual(target.read_bytes(), data)
            self.assertEqual(list(target.parent.glob("*.part")), [])

    def test_bad_checksum_preserves_previous_model_and_cleans_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "model.onnx"
            target.write_bytes(b"previous model")
            with patch.object(download_models.urllib.request, "urlopen", return_value=io.BytesIO(b"bad")):
                with self.assertRaisesRegex(RuntimeError, "Checksum mismatch"):
                    download_models.download("https://example.invalid/model", target, "0" * 64)
            self.assertEqual(target.read_bytes(), b"previous model")
            self.assertEqual(list(target.parent.glob("*.part")), [])

    def test_network_failure_cleans_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "model.onnx"
            with patch.object(download_models.urllib.request, "urlopen", side_effect=TimeoutError):
                with self.assertRaises(TimeoutError):
                    download_models.download("https://example.invalid/model", target, "0" * 64)
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.iterdir()), [])
