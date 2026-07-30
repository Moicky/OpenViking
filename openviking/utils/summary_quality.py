# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Detect placeholder/failed summaries that must never be embedded."""

from typing import Optional

FAILED_SUMMARY_MARKERS = (
    "video summary generation not yet implemented",
    "audio summary generation not yet implemented",
)


def is_failed_summary(summary: Optional[str]) -> bool:
    """Return True when a summary is empty or a known failure placeholder."""
    if summary is None or not str(summary).strip():
        return True
    normalized = str(summary).strip().lower()
    return any(marker in normalized for marker in FAILED_SUMMARY_MARKERS)
