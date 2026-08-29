#!/bin/sh
set -e
cd "$(dirname "$0")"
python3 -m src.test_core
python3 -m src.main --once
