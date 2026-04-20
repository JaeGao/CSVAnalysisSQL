@echo off
setlocal

cd /d "%~dp0"

echo Starting CSV Analyzer Setup...

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Python could not be found. Please install Python and make sure it is added to PATH.
    pause
    exit /b
)

:: Create virtual environment if it doesn't exist
if not exist "venv\" (
    echo Creating virtual environment 'venv'...
    python -m venv venv
)

:: Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

:: Install requirements
echo Installing dependencies from requirements.pip...
pip install -r requirements.pip

:: Run the app
echo Launching CSV Analyzer...
python main.py

pause
