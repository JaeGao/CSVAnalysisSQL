#!/bin/bash

cd "$(dirname "$0")"

echo "========================================="
echo " CSV Analyzer - Build Script"
echo "========================================="
echo ""

# Activate virtual environment if available
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Install PyInstaller
pip install pyinstaller

echo ""
echo "Building executable..."
echo ""

# Build the executable
# --noconsole   : No terminal window behind the GUI
# --onefile     : Single executable output
# --add-data    : Bundle assets (use : separator on Linux/Mac, ; on Windows)
pyinstaller --noconsole --onefile \
    --add-data "src/style.qss:." \
    --add-data "src/grip_horizontal.png:." \
    --add-data "src/grip_vertical.png:." \
    --add-data "src/icon.png:." \
    --name "CSV_Analyzer" \
    src/main.py

echo ""
echo "========================================="
echo "Build complete! Your executable is located at:"
echo "$(pwd)/dist/CSV_Analyzer"
echo "========================================="
