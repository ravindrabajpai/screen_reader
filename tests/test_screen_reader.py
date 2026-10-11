from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import screen_reader


class ScreenReaderTests(unittest.TestCase):
    def test_normalize_text_preserves_paragraphs(self) -> None:
        self.assertEqual(
            screen_reader.normalize_text("Hello\n\n local\treader. "),
            "Hello\n\nlocal reader.",
        )

    def test_resolve_model_dir_prefers_argument(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            expected = Path(temp).resolve()
            self.assertEqual(screen_reader.resolve_model_dir(temp), expected)

    def test_resolve_model_dir_uses_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict("os.environ", {"SCREEN_READER_MODEL_DIR": temp}):
                self.assertEqual(
                    screen_reader.resolve_model_dir(None), Path(temp).resolve()
                )

    def test_clipboard_mode_does_not_require_tesseract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            model_dir = Path(temp)
            (model_dir / "kokoro-v1.0.onnx").touch()
            (model_dir / "voices-v1.0.bin").touch()
            with (
                patch.object(screen_reader.sys, "platform", "darwin"),
                patch.object(screen_reader, "read_clipboard", return_value="hello"),
                patch.object(screen_reader, "submit") as submit,
                patch.object(screen_reader.subprocess, "run"),
                patch.object(screen_reader.shutil, "which", return_value=None),
            ):
                result = screen_reader.main(
                    ["--clipboard", "--model-dir", str(model_dir)]
                )
            self.assertEqual(result, 0)
            self.assertEqual(submit.call_args.args[0]["text"], "hello")

    def test_control_does_not_require_models_or_ocr(self):
        for flag, kind in (("--stop", "stop"), ("--shutdown-reader", "shutdown"), ("--reader-status", "status")):
            with (patch.object(screen_reader.sys, "platform", "darwin"),
                  patch.object(screen_reader, "control", return_value={"state": "not_running"}) as control,
                  patch.object(screen_reader, "resolve_model_dir") as models,
                  patch.object(screen_reader, "read_clipboard") as clipboard):
                self.assertEqual(screen_reader.main([flag]), 0)
                control.assert_called_once_with(kind)
                models.assert_not_called()
                clipboard.assert_not_called()

    def test_direct_preserves_foreground_path(self):
        with tempfile.TemporaryDirectory() as temp:
            for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
                (Path(temp) / name).touch()
            with (patch.object(screen_reader.sys, "platform", "darwin"),
                  patch.object(screen_reader, "read_clipboard", return_value="hello"),
                  patch.object(screen_reader, "synthesize") as synthesize,
                  patch.object(screen_reader.subprocess, "run") as player,
                  patch.object(screen_reader, "submit") as submit):
                self.assertEqual(screen_reader.main(["--clipboard", "--direct", "--model-dir", temp]), 0)
                synthesize.assert_called_once()
                player.assert_called_once()
                submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
