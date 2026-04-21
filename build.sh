#!/bin/bash

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
# --add-data    : Bundle the stylesheet (use : separator on Linux/Mac, ; on Windows)
pyinstaller --noconsole --onefile --add-data "style.qss:." --add-data "grip_horizontal.png:." --add-data "grip_vertical.png:." --name "CSV_Analyzer" main.py

echo ""
echo "========================================="
echo "Build complete! Your executable is located at:"
echo "$(pwd)/dist/CSV_Analyzer"
echo "========================================="
