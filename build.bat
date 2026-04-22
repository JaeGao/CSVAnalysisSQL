@echo off
setlocal

cd /d "%~dp0"

echo =========================================
echo  CSV Analyzer - Windows Build Script
echo =========================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python could not be found. Please install Python and add it to PATH.
    pause
    exit /b 1
)

:: Create virtual environment if it doesn't exist
if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
)

:: Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

:: Install requirements
echo Installing project dependencies...
pip install -r requirements.pip

:: Install PyInstaller
echo Installing PyInstaller...
pip install pyinstaller

echo.
echo Pre-installing DuckDB Excel extension...
python src\bundle_ext.py

echo.
echo Building executable...
echo.

:: Build the executable
:: --noconsole   : No terminal window behind the GUI
:: --onefile     : Single .exe output
:: --add-data    : Bundle assets with the executable
:: --icon        : Set the executable icon
pyinstaller ^
    --noconsole ^
    --onefile ^
    --add-data "src\style.qss;." ^
    --add-data "src\grip_horizontal.png;." ^
    --add-data "src\grip_vertical.png;." ^
    --add-data "src\icon.png;." ^
    --add-data "src\scripts.json;." ^
    --add-data "src\extensions;extensions" ^
    --icon "src\icon.ico" ^
    --name "CSV_Analyzer" ^
    src\main.py

echo.
if exist "dist\CSV_Analyzer.exe" (
    echo =========================================
    echo  Build successful!
    echo  Output: %cd%\dist\CSV_Analyzer.exe
    echo =========================================
) else (
    echo =========================================
    echo  Build FAILED. Check the output above.
    echo =========================================
)

pause
