#!/bin/bash

# Activate the virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "Starting CSV Analyzer in watch mode. Press Ctrl+C to stop."
watchmedo auto-restart --pattern="*.py;*.qss" --directory="src" --recursive --no-restart-on-command-exit -- python src/main.py
