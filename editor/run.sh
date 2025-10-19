#!/bin/bash

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment and install dependencies
echo "Activating virtual environment..."
source venv/bin/activate

# Install requirements if needed
echo "Installing dependencies..."
pip install -q -r requirements.txt

# Run the application
echo "Starting application..."
python main.py
