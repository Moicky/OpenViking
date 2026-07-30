# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
from openviking.retrieve.graph_expansion import (
    extract_imports,
    resolve_import_candidates,
)


def test_extracts_ts_imports():
    content = (
        "import { sendMessage } from '../aws/sqs';\n"
        'import fiskaly from "./fiscal-providers/fiskaly";\n'
        "const x = require('../../lib/receipts/utils');\n"
    )
    assert extract_imports("lambda.ts", content) == [
        "../aws/sqs",
        "./fiscal-providers/fiskaly",
        "../../lib/receipts/utils",
    ]


def test_ignores_bare_package_imports():
    content = "import fs from 'node:fs';\nimport x from 'lodash';\n"
    assert extract_imports("a.ts", content) == []


def test_resolves_relative_candidates():
    cands = resolve_import_candidates(
        "viking://r/apps/backend/src/lambdas/order-signing-function/lambda.ts",
        "../aws/sqs",
    )
    assert "viking://r/apps/backend/src/lambdas/aws/sqs.ts" in cands
    assert "viking://r/apps/backend/src/lambdas/aws/sqs/index.ts" in cands


def test_extracts_python_relative_imports():
    content = "from .utils import helper\nimport os\n"
    assert extract_imports("mod.py", content) == [".utils"]


def test_python_resolution():
    cands = resolve_import_candidates("viking://r/pkg/mod.py", ".utils")
    assert "viking://r/pkg/utils.py" in cands
