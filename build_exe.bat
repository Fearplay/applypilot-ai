@echo off
setlocal EnableDelayedExpansion

REM ============================================================================
REM  ApplyPilot AI - Windows EXE builder
REM ----------------------------------------------------------------------------
REM  Goal: produce a single, self-contained ``dist\ApplyPilotAI.exe`` the user
REM  can double-click without having Python installed. Steps:
REM    1. Create / reuse a disposable virtualenv (.venv-build) so PyInstaller
REM       packages a deterministic, isolated dependency tree.
REM    2. Install everything from requirements.txt into that venv.
REM    3. Install PyInstaller if missing.
REM    4. Run PyInstaller with ``--onefile --windowed`` plus the hidden imports
REM       and data folders the runtime needs.
REM
REM  When you add a new top-level Python dependency, ALSO update this script:
REM    - Make sure it is in requirements.txt (Cursor rule: requirements-sync.mdc)
REM    - If the import is dynamic (PyInstaller can't see it from app.py),
REM      add a ``--hidden-import`` or ``--collect-all`` line below
REM      (Cursor rule: build-exe-sync.mdc).
REM ============================================================================

set REPO_ROOT=%~dp0
pushd "%REPO_ROOT%"

set VENV=.venv-build

REM -- 1. Find a Python interpreter & create the disposable venv ---------------
if not exist "%VENV%\Scripts\python.exe" (
    echo [build_exe] Creating fresh venv at %VENV% ...
    py -3.13 -m venv "%VENV%" 2>nul
    if errorlevel 1 (
        py -3.12 -m venv "%VENV%" 2>nul
    )
    if errorlevel 1 (
        py -3.11 -m venv "%VENV%" 2>nul
    )
    if errorlevel 1 (
        echo [build_exe] ERROR: could not find Python 3.11/3.12/3.13 to create venv. && goto :fail
    )
)

call "%VENV%\Scripts\activate.bat"
if errorlevel 1 goto :fail

REM -- 2. Install / upgrade runtime + build dependencies ----------------------
python -m pip install --upgrade pip
if errorlevel 1 goto :fail

python -m pip install --upgrade -r requirements.txt
if errorlevel 1 goto :fail

REM PyInstaller is in the dev section of requirements.txt but install it
REM explicitly too so a stripped-down requirements file still works.
python -m pip install --upgrade "pyinstaller>=6.10,<7"
if errorlevel 1 goto :fail

REM -- 3. Make sure Playwright has a browser to drive (used by job-fetcher) ----
REM    Skip the heavy Chromium download when the user already has Chrome /
REM    Edge installed system-wide (the JD parser uses ``channel="chrome"``).
where chrome >nul 2>nul
if errorlevel 1 (
    where msedge >nul 2>nul
    if errorlevel 1 (
        echo [build_exe] No system Chrome/Edge detected; downloading Playwright Chromium ...
        python -m playwright install chromium
    )
)

REM -- 4. Run PyInstaller -----------------------------------------------------
REM    --onefile      : single executable
REM    --windowed     : no console window (it's a Qt GUI app)
REM    --collect-all  : grab every submodule + data file the package ships
REM    --hidden-import: pull in dynamic imports PyInstaller's static
REM                     analyser cannot see (e.g. keyring backends loaded
REM                     by entry points).
echo [build_exe] Running PyInstaller ...
pyinstaller ^
    --noconfirm --clean --onefile --windowed ^
    --name=ApplyPilotAI ^
    --icon=assets\applypilot.ico ^
    --add-data "src\i18n;src\i18n" ^
    --add-data "sample_data;sample_data" ^
    --add-data "assets;assets" ^
    --collect-all PySide6 ^
    --collect-all playwright ^
    --collect-all keyring ^
    --collect-all truststore ^
    --hidden-import keyring.backends.Windows ^
    --hidden-import keyring.backends.macOS ^
    --hidden-import keyring.backends.SecretService ^
    --hidden-import keyring.backends.fail ^
    app.py
if errorlevel 1 goto :fail

if not exist "dist\ApplyPilotAI.exe" (
    echo [build_exe] ERROR: PyInstaller reported success but dist\ApplyPilotAI.exe is missing. && goto :fail
)

echo.
echo ========================================================================
echo   BUILD OK
echo   Output: %REPO_ROOT%dist\ApplyPilotAI.exe
echo ========================================================================
popd
endlocal
exit /b 0

:fail
echo.
echo ========================================================================
echo   BUILD FAILED
echo ========================================================================
popd
endlocal
exit /b 1
