# Therein on Windows

## Portable executable edition

A successful native Windows build produces `Therein-Windows-x64.zip` and its SHA-256 checksum. Extract the ZIP into a permanent local folder, keep `Therein.exe` and `_internal` together, and double-click `Therein.exe`. No separate Python install is required. Python, the Playwright driver, and Chromium are bundled. Initial venue access still requires internet.

The program opens a console and the local dashboard in your default browser. **Leave the console running.** Select **Exit recorder** in the dashboard for a clean shutdown. `Start_Demo.bat` opens an isolated synthetic demonstration instead of real capture.

The executable is unsigned. It does not request administrator access or tell you to disable Defender or SmartScreen. Verify its source and checksum; an organization may need to review it under its own security rules. Extract before running rather than launching inside an archive viewer. Windows 11 x64 is the intended desktop target; other Windows versions/architectures are not certified.

## Python source edition

1. Install a Windows Python runtime 3.10 or later from python.org. Python 3.12 x64 is the workflow's Windows test/build runtime.
2. Extract the full source into a writable local folder. Do not use a copy of a Mac `.venv`.
3. Run `01_Setup_Windows.bat`. The script finds `py -3` or `python`, creates `.venv`, installs the pinned Playwright package, downloads Chromium, and runs tests. It does not activate PowerShell scripts or change execution policy.
4. Run `02_Start_Windows.bat` whenever you want to record. No administrative privileges are needed.

Useful scripts: `03_Synthetic_Demo_Windows.bat`, `04_Test_Windows.bat`, `05_Build_Portable_Windows.bat`, and `06_Open_Data_Folder_Windows.bat`. For unattended source setup/test runs, set `THEREIN_NO_PAUSE=1` first; this only suppresses the console's final pause.

## Obsidian and persistence

Paste your existing vault's full path into the dashboard, for example `C:\Users\you\Documents\MyVault` or its actual OneDrive location. Spaces and Unicode characters are supported. Do not paste an `obsidian://` URL or a path to a single note.

Save the destination explicitly. Only `Crash Round Research` inside that vault is generated/refreshed. The SQLite database and dedicated browser profile stay in `%LOCALAPPDATA%\CrashRoundRecorder`. Updating or replacing the extracted software folder does not reset these records. Do not run two recorder copies against the same data folder or two writers against the same synced vault export folder.

To move history to another computer, stop the recorder, back up the data, and transfer a complete all-round CSV into the other machine's recorder. CSV transfer preserves IDs/results but is recorded as an import, not as original capture timestamps. Do not transfer login profiles or live SQLite WAL files casually. The program does not automatically synchronize two machines.

## Capture calibration and limits

Open the separate capture browser, display completed history, compare IDs/multipliers, then approve the preview. The current live-site layout remains unverified. If no compatible history links exist, a site adapter is needed; CSV import still works. The recorder does not bypass site blocks or place wagers.

The newest result remains buffered until a newer ID is visible and repeated scans agree. Missing IDs interrupt streak continuity. The machine must stay awake and connected, with the recorder and capture browser open.

## Troubleshooting

**Python not found:** install Python, close the script, reopen it. **Missing browser:** rerun setup. **Empty preview:** show completed round history and review the source selector; do not approve player cashout values. **Already running:** use the existing recorder's dashboard and exit it normally. **Vault does not exist:** choose the real folder already on this machine. **Port occupied:** the app automatically tries another local port. **Blocked unsigned executable:** use the reviewed source edition or your organization's approval process; do not disable protections.
