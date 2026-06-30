#!/usr/bin/env python3
"""Manual CVBrain Intake v2 live-smoke command."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from typing import Any, TextIO

from app.intake_v2.live_smoke import run_intake_v2_live_smoke


def main(*, env: Mapping[str, str] | None = None, stdout: TextIO | None = None) -> int:
    output = stdout or sys.stdout
    result = run_intake_v2_live_smoke(env=dict(env) if env is not None else dict(os.environ))
    safe_result = _safe_script_result(result)
    print(json.dumps(safe_result, sort_keys=True), file=output)
    return 0 if safe_result.get("status") == "passed" else 1


def _safe_script_result(result: Mapping[str, Any]) -> dict[str, Any]:
    status = result.get("status")
    if status not in {"skipped", "unavailable", "ready_to_run", "passed", "failed"}:
        status = "failed"
    return {
        "ok": bool(result.get("ok") is True),
        "status": status,
        "code": _safe_code(result.get("code")),
        "category": "live_smoke",
    }


def _safe_code(value: Any) -> str:
    text = str(value or "").strip()
    if text in {
        "live_smoke_not_enabled",
        "live_smoke_provider_config_missing",
        "live_smoke_failed",
        "live_smoke_passed",
    }:
        return text
    return "live_smoke_failed"


if __name__ == "__main__":
    raise SystemExit(main())
