#!/bin/bash
# Pi_Eyes Animatronics Studio Launcher
# Automatically sets up virtual environment and runs the editor

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
MAIN_SCRIPT="$SCRIPT_DIR/main.py"

echo "Pi_Eyes Animatronics Studio Launcher"
echo "===================================="
echo

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed"
    echo "Please install Python 3 first"
    exit 1
fi

# Check if requirements.txt exists
if [ ! -f "$REQUIREMENTS" ]; then
    echo "Error: requirements.txt not found at $REQUIREMENTS"
    exit 1
fi

# Check if main.py exists
if [ ! -f "$MAIN_SCRIPT" ]; then
    echo "Error: main.py not found at $MAIN_SCRIPT"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "✓ Virtual environment created"
    echo
fi

# Activate virtual environment
echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Check if requirements are installed or have changed
REQUIREMENTS_HASH_FILE="$VENV_DIR/.requirements_hash"
CURRENT_HASH=$(md5sum "$REQUIREMENTS" | cut -d' ' -f1)

if [ ! -f "$REQUIREMENTS_HASH_FILE" ] || [ "$(cat "$REQUIREMENTS_HASH_FILE")" != "$CURRENT_HASH" ]; then
    echo "Installing/updating dependencies..."
    pip install -q --upgrade pip
    pip install -q -r "$REQUIREMENTS"
    echo "$CURRENT_HASH" > "$REQUIREMENTS_HASH_FILE"
    echo "✓ Dependencies installed"
    echo
else
    echo "✓ Dependencies up to date"
    echo
fi

# Check for game controller
echo "Checking for game controller..."
if python3 -c "import inputs; inputs.devices.gamepads" 2>/dev/null; then
    echo "✓ Game controller detected"
else
    echo "⚠ Warning: No game controller detected"
    echo "  Make sure your PS4 or Xbox controller is connected"
fi
echo

# Run the editor
echo "Starting Animatronics Studio..."
echo "===================================="
echo
python3 "$MAIN_SCRIPT" "$@"

# Deactivate is automatic when script exits, but we'll be explicit
deactivate
