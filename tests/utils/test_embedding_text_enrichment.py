# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
from openviking.utils.embedding_utils import build_embedding_text


def test_prefixes_repo_relative_path():
    text = build_embedding_text(
        "viking://resources/posmodule-v2/apps/backend/src/lib/aws/sqs.ts",
        "export const sendMessage = ...",
    )
    assert text.startswith(
        "resources/posmodule-v2/apps/backend/src/lib/aws/sqs.ts\n"
    )
    assert text.endswith("export const sendMessage = ...")


def test_empty_body_returns_path_only():
    assert build_embedding_text("viking://resources/r/a.ts", "") == "resources/r/a.ts"


def test_plain_path_without_scheme():
    assert build_embedding_text("/resources/r/a.ts", "body") == "resources/r/a.ts\nbody"
