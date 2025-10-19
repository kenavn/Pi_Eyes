# Pi_Eyes Animatronics Studio

The Animatronics Studio is a GUI application for creating and editing animations for the Pi_Eyes project.

## Features

- Record eye movements using game controller
- Record mouth movements separately
- Synchronize animations with audio
- Export animation bundles for playback on Raspberry Pi
- Timeline editing and playback

## Quick Start

### Using Launcher Scripts (Recommended)

The easiest way to run the editor:

**Linux/Mac:**
```bash
./run_editor.sh
```

**Windows:**
```
run_editor.bat
```

The launcher will automatically:
- Create a Python virtual environment (first run only)
- Install all required dependencies
- Check for connected game controller
- Launch the application

### Manual Setup

If you prefer to manage the environment yourself:

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate.bat  # Windows

# Install dependencies
pip install -r requirements.txt

# Run the editor
python main.py
```

## Requirements

- Python 3.7 or higher
- PS4 or Xbox controller
- Audio files for animation synchronization (optional)

## Dependencies

All dependencies are listed in `requirements.txt`:
- pygame - Game controller input and audio playback
- pydub - Audio file manipulation
- numpy - Data processing
- inputs - Controller input handling

## Usage

1. **Connect Controller**: Plug in your PS4 or Xbox controller before starting
2. **Launch**: Run the launcher script or `python main.py`
3. **Configure Settings**: Set robot IP address and ports
4. **Record**: Use controller to record eye and mouth movements
5. **Export**: Save as animation bundle for deployment

## Troubleshooting

### "No game controller detected"
- Ensure controller is connected before launching
- Check USB connection
- On Linux, you may need to add your user to the `input` group

### "Module not found" errors
- Delete the `venv` folder and run the launcher again
- Or reinstall dependencies: `pip install -r requirements.txt`

### Controller not responding
- Try a different USB port
- Reconnect the controller
- Restart the application

## File Formats

### Animation Bundle (.anim)
Binary format containing:
- Eye movement data
- Mouth movement data
- Audio file (MP3/WAV)
- Timing information

### Animation CSV
Text format for eye/mouth movements (legacy)

## Controls

See the application UI for current controller mapping.

## Contributing

When adding new features, update `requirements.txt` if you add dependencies:
```bash
pip freeze > requirements.txt
```
