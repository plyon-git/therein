@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0.." || exit /b 1
set "ACTION=%~1"
set "RESULT=0"
if /i "%ACTION%"=="setup" goto setup
if /i "%ACTION%"=="start" goto start
if /i "%ACTION%"=="demo" goto demo
if /i "%ACTION%"=="test" goto test
if /i "%ACTION%"=="build" goto build
if /i "%ACTION%"=="folder" goto folder
echo Unknown action: %ACTION%
set "RESULT=1"
goto end

:findpython
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) and sys.platform == 'win32' else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY exit /b 0
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) and sys.platform == 'win32' else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY exit /b 0
echo Python 3.10 or later for Windows is required for the source edition.
echo Install it from https://www.python.org/downloads/windows/ and reopen this script.
echo The portable executable edition does not need Python installed.
exit /b 1

:checkenv
if not exist ".venv\Scripts\python.exe" (
  echo Run 01_Setup_Windows.bat first. Do not copy a Mac .venv onto Windows.
  exit /b 1
)
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
exit /b %errorlevel%

:setup
call :findpython
if errorlevel 1 goto fail
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv
  if errorlevel 1 goto fail
)
call :checkenv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m playwright install chromium --no-shell
if errorlevel 1 goto fail
".venv\Scripts\python.exe" scripts\run_tests.py --require-browser
if errorlevel 1 goto fail
echo.
echo Setup passed. Run 02_Start_Windows.bat. No vault or venue account was changed.
goto end

:start
call :checkenv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -u recorder.py
if errorlevel 1 goto fail
goto end

:demo
call :checkenv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -u recorder.py --demo
if errorlevel 1 goto fail
goto end

:test
call :checkenv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" scripts\run_tests.py --require-browser
if errorlevel 1 goto fail
".venv\Scripts\python.exe" recorder.py --self-test
if errorlevel 1 goto fail
goto end

:build
call :checkenv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" scripts\build_windows.py
if errorlevel 1 goto fail
echo Portable output is in dist\Therein-Windows-x64.zip.
goto end

:folder
if not defined LOCALAPPDATA (
  echo LOCALAPPDATA is unavailable. Start the app to display its exact data path.
  goto end
)
if not exist "%LOCALAPPDATA%\CrashRoundRecorder" (
  echo Start the recorder once to create its local data folder.
  goto end
)
start "" "%LOCALAPPDATA%\CrashRoundRecorder"
goto end

:fail
set "RESULT=1"
echo.
echo The operation failed. Read the error above. Existing records were not deleted.
:end
popd
if not defined THEREIN_NO_PAUSE pause
exit /b %RESULT%
