# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
from openviking.utils.summary_quality import is_failed_summary


def test_placeholder_video_summary_is_failed():
    assert is_failed_summary("Video summary generation not yet implemented")


def test_placeholder_audio_summary_is_failed():
    assert is_failed_summary("Audio summary generation not yet implemented")


def test_empty_and_whitespace_are_failed():
    assert is_failed_summary("")
    assert is_failed_summary("   \n")
    assert is_failed_summary(None)


def test_real_summary_is_not_failed():
    assert not is_failed_summary("Creates fiscal receipts by queueing SQS messages.")


def test_placeholder_embedded_in_longer_text_is_failed():
    assert is_failed_summary(
        "Note: Video summary generation not yet implemented for this file"
    )
