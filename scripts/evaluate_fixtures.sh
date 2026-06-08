#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 1

echo "CVBrain fixture evaluation"
echo "[1/3] Python compile"
python3 -m py_compile app/main.py

echo "[2/3] Pytest"
pytest

echo "[3/3] Fixture suite complete"
