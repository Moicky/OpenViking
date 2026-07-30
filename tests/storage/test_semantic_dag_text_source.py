# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
from openviking.storage.queuefs.semantic_dag import resolve_vectorize_summary


def test_code_repo_no_longer_forces_summary_only():
    summary_dict, use_summary = resolve_vectorize_summary(
        {"name": "a.ts", "summary": "Handles receipts."}, is_code_repo=True
    )
    assert use_summary is False
    assert summary_dict["summary"] == "Handles receipts."


def test_failed_summary_is_scrubbed():
    summary_dict, use_summary = resolve_vectorize_summary(
        {"name": "a.ts", "summary": "Video summary generation not yet implemented"},
        is_code_repo=True,
    )
    assert summary_dict["summary"] == ""
    assert use_summary is False


def test_non_code_repo_unchanged():
    summary_dict, use_summary = resolve_vectorize_summary(
        {"name": "notes.md", "summary": "Meeting notes."}, is_code_repo=False
    )
    assert use_summary is False
    assert summary_dict["summary"] == "Meeting notes."
