# Third-party components

The MIT license in this repository applies to this project's original source. It does not replace the terms for dependencies, model weights, voice data, or macOS utilities. Dependencies and models are fetched separately by the installer and are not included in the source repository.

Key upstream references:

| Component | Upstream terms / source |
| --- | --- |
| Kokoro ONNX wrapper | [MIT license](https://github.com/thewh1teagle/kokoro-onnx/blob/main/LICENSE) |
| Kokoro model | [Model card, Apache-2.0 and attribution information](https://huggingface.co/hexgrad/Kokoro-82M) |
| ONNX model and voice release artifacts | [Kokoro ONNX model release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1) |
| Phonemizer | [Project and GPL license information](https://github.com/bootphon/phonemizer) |
| eSpeak NG, loaded by espeakng-loader | [GPL license](https://github.com/espeak-ng/espeak-ng/blob/master/COPYING) |
| Remaining Python packages | Installed package metadata and upstream license files; exact versions in `requirements.lock` |
| Tesseract and its dependencies | [Upstream project](https://github.com/tesseract-ocr/tesseract), installed separately through Homebrew |

This is a source/dependency reference list, not an exhaustive notice bundle for a binary distribution. If producing a packaged app, container, or downloadable environment, review all included artifacts and their redistribution obligations, particularly GPL components and model/voice notices. Do not describe the complete installed dependency stack as MIT-only.
