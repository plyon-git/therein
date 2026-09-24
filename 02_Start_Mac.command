#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "Run 01_Setup_Mac.command first. Press Return to close."
  read -r _
  exit 1
fi
.venv/bin/python recorder.py
status=$?
if [ "$status" -ne 0 ]; then
  echo "Recorder exited with an error. Press Return to close."
  read -r _
fi
