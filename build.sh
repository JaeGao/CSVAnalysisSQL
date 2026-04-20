#!/bin/bash

echo "Building CSV Analyzer Executable..."

# Activate virtual environment if available
if [ -d "../venv" ]; then
    source ../venv/bin/activate
fi

# Install PyInstaller
pip install pyinstaller

# Build the executable
pyinstaller --noconsole --onefile --add-data "style.qss:." --name "CSV_Analyzer" main.py

echo ""
echo "========================================="
echo "Build complete! Your executable is located at:"
echo "$(pwd)/dist/CSV_Analyzer"
echo "========================================="
