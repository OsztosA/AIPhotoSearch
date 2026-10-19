@echo off
setlocal

cd /d "%~dp0"
if errorlevel 1 (
    echo Failed to change to the project directory.
    exit /b 1
)

python -m pip install -r requirements-build.txt
if errorlevel 1 (
    echo Failed to install build requirements.
    exit /b 1
)

python -m PyInstaller --noconfirm --clean PhotoSearch.spec
if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

echo Build complete: dist\PhotoSearch\PhotoSearch.exe
