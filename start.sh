#!/bin/bash

# Change to the directory of the script
cd "$(dirname "$0")"

echo "Starting CSV Analyzer Setup..."

# Check if Python is installed
if ! command -v python3 &> /dev/null
then
    echo "Python3 could not be found. Please install Python3 and try again."
    exit
fi

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
python main.py
