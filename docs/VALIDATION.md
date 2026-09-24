# Validation scope / v1.1.0

## Checks executed in the build workspace

On Linux x64 with Python 3.13.5 and Playwright 1.57.0:

- 68 unittest cases passed with no skips. This includes the original rule/browser/storage/server tests, Windows-path selection, Unicode persistence, junction detection, cross-process locking, launcher structure, and authenticated shutdown checks.
- The rule test includes 300 randomized comparisons with a separately implemented eligibility-mask calculation. It is a correctness check against synthetic data, not a performance backtest.
- Offline `--self-test` passed bundled-resource lookup in source mode, a real headless Chromium parse of synthetic HTML, SQLite persistence, the finality guard, and Obsidian export.
- The subprocess smoke test passed startup, authenticated HTTP status, dashboard resource serving, safe shutdown, restart, and cumulative-data persistence.

## Native-platform checks

The repository workflow is configured to run the suite and smoke tests on Linux/Python 3.10, Windows/Python 3.12, and macOS/Python 3.12. Its native Windows build installs a local bundled Chromium, builds a PyInstaller one-folder executable, runs the executable's offline browser/storage self-test, and restarts the executable against isolated synthetic data before packaging it.

**Consult the GitHub Actions result for the specific commit.** A workflow definition is not evidence that its runs or executable build succeeded. This document records the local Linux results; it does not predeclare native workflow results.

## Not certified

Live EtherCrash capture, current site DOM/terms/account requirements, cryptographic outcome verification, uninterrupted site availability, real cashout settlement, profitability, Windows ARM, and all possible consumer Windows configurations were not certified. The site reader is still explicitly user-calibrated. A Windows hosted-runner pass is not a live venue test or an exhaustive desktop compatibility certification.

No actual account, private vault, wallet, or wager was involved in these tests. All input history in the repository is synthetic. Maximum observed streaks are not future limits.
