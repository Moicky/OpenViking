# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""One-hop import expansion for find results.

Parses relative imports out of top-ranked seed files on demand (no extra
persistence) and adds the imported files as lower-scored candidates.
"""

import posixpath
import re
from typing import List

_JS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_JS_IMPORT_RE = re.compile(
    r"(?:import|export)\s+[^'\"\n]*?from\s+['\"]([^'\"]+)['\"]|require\(\s*['\"]([^'\"]+)['\"]\s*\)"
)
_PY_IMPORT_RE = re.compile(r"^\s*from\s+(\.[\w.]*)\s+import\s", re.MULTILINE)
_RESOLVE_SUFFIXES = ("", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js")
SCORE_DECAY = 0.6


def extract_imports(file_name: str, content: str) -> List[str]:
    """Return relative import specifiers (order-preserving, deduped)."""
    specs: List[str] = []
    if file_name.endswith(_JS_EXTENSIONS):
        for a, b in _JS_IMPORT_RE.findall(content):
            spec = a or b
            if spec.startswith("."):
                specs.append(spec)
    elif file_name.endswith(".py"):
        specs.extend(_PY_IMPORT_RE.findall(content))
    seen = set()
    return [s for s in specs if not (s in seen or seen.add(s))]


def resolve_import_candidates(seed_uri: str, spec: str) -> List[str]:
    """Resolve a relative import spec into possible sibling URIs."""
    scheme, _, path = seed_uri.partition("://")
    base_dir = posixpath.dirname(path)
    if not spec.startswith("."):
        return []

    if seed_uri.endswith(".py"):
        dots = len(spec) - len(spec.lstrip("."))
        rel = spec.lstrip(".").replace(".", "/")
        target_dir = base_dir
        for _ in range(dots - 1):
            target_dir = posixpath.dirname(target_dir)
        resolved = posixpath.normpath(posixpath.join(target_dir, rel))
        return [f"{scheme}://{resolved}.py", f"{scheme}://{resolved}/__init__.py"]

    resolved = posixpath.normpath(posixpath.join(base_dir, spec))
    basename = posixpath.basename(resolved)
    return [
        f"{scheme}://{resolved}{suffix}"
        for suffix in _RESOLVE_SUFFIXES
        if suffix or "." in basename
    ]
