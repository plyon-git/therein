#!/bin/bash
set -e
cd "$(dirname "$0")"
trap 'echo; echo "Setup stopped. Read the error above. Press Return to close."; read -r _' ERR
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.10 or later is required. Install Python from https://www.python.org/downloads/macos/ and run this again."
  read -r _
  exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10 or later is required"'
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
chmod +x 02_Start_Mac.command 03_Synthetic_Demo.command
.venv/bin/python -m unittest discover -s tests -p 'test_core.py' -v
echo
echo "Setup complete. Run 02_Start_Mac.command. No vault or website account has been changed."
echo "Press Return to close."
read -r _
