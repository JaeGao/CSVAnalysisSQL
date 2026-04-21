#!/bin/bash

cd "$(dirname "$0")"

echo "Starting CSV Analyzer Setup..."

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment 'venv'..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install requirements
echo "Installing dependencies from requirements.pip..."
pip install -r requirements.pip

# Run the app
echo "Launching CSV Analyzer..."
python src/main.py
