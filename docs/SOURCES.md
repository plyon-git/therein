# Primary-source implementation references

Reviewed for the cross-platform build on 2026-09-24. These are documentation references, not proof that a live site's DOM is compatible.

- Playwright Python installation and supported environments: https://playwright.dev/python/docs/intro
- Playwright PyInstaller browser bundling, thread ownership and Windows event loop: https://playwright.dev/python/docs/library
- Browser installations and Chromium-only/no-shell options: https://playwright.dev/python/docs/browsers
- Python Windows installation, `py`, and virtual environments: https://docs.python.org/3/using/windows.html
- PyInstaller platform-specific builds and one-folder distribution: https://pyinstaller.org/en/stable/operating-mode.html
- PyInstaller runtime resource paths: https://pyinstaller.org/en/stable/runtime-information.html
- Obsidian local Markdown storage: https://help.obsidian.md/Files+and+folders/How+Obsidian+stores+data
- SQLite WAL and backup considerations: https://sqlite.org/wal.html
- GitHub Actions artifact download: https://docs.github.com/en/actions/managing-workflow-runs/downloading-workflow-artifacts

Python standard-library APIs implement SQLite, local HTTP, CSV, UTF-8 files and OS-specific process locking. The live reader only inspects user-approved visible page text and numeric history IDs.
