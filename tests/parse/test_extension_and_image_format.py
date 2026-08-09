# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Extension coverage for ESM/CJS sources, and VLM image-format gating."""

from openviking.parse.parsers.code.ast.extractor import _EXT_MAP
from openviking.parse.parsers.constants import CODE_EXTENSIONS
from openviking.parse.parsers.media.utils import _vlm_image_format


def test_esm_cjs_extensions_are_code():
    # .mjs/.cjs configs and scripts are ordinary JavaScript; before this they
    # were reported as "unsupported file(s)" and skipped entirely.
    for ext in (".mjs", ".cjs", ".mts", ".cts"):
        assert ext in CODE_EXTENSIONS, f"{ext} missing from CODE_EXTENSIONS"

    for ext in (".mjs", ".cjs"):
        assert _EXT_MAP[ext] == "javascript"
    for ext in (".mts", ".cts"):
        assert _EXT_MAP[ext] == "typescript"


def test_vlm_image_format_accepts_only_what_the_api_takes():
    assert _vlm_image_format(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8) == "image/png"
    assert _vlm_image_format(b"\xff\xd8\xff\xe0" + b"\x00" * 8) == "image/jpeg"
    assert _vlm_image_format(b"GIF89a" + b"\x00" * 8) == "image/gif"
    assert _vlm_image_format(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 4) == "image/webp"


def test_vlm_image_format_rejects_ico_and_svg():
    # app/favicon.ico from a Next.js app: ICO container, 3 images, 48x48.
    # Sending this returned a 400 from OpenAI on every ingest.
    ico = bytes.fromhex("0000010003003030") + b"\x00" * 8
    assert _vlm_image_format(ico) is None
    assert _vlm_image_format(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None
    assert _vlm_image_format(b"BM" + b"\x00" * 12) is None  # .bmp
    assert _vlm_image_format(b"\x00\x00") is None  # too short to classify
