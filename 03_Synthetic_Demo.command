#!/bin/bash
cd "$(dirname "$0")" || exit 1
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
"$PY" recorder.py --demo
