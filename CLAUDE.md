# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pi_Eyes is a multi-generation fork of Adafruit's original animated snake eyes project for Raspberry Pi:

- **Original Project**: [Adafruit Snake Eyes](https://learn.adafruit.com/animated-snake-eyes-bonnet-for-raspberry-pi/) by Adafruit and Paint Your Dragon
- **First Fork**: [kenavn/Pi_Eyes](https://github.com/kenavn/Pi_Eyes) - Added UDP remote control, PS4 controller support, recording/playback, MQTT animation system, and service-based architecture
- **This Fork**: Extends the service architecture with thermal tracking using AMG8833 IR camera and performance optimizations

The system displays animated eyes on small screens with remote UDP control, PS4 controller recording/playback, mouth servo control, thermal eye tracking, and MQTT-based animation management. It consists of four main components:

1. **Eye Control System** (`eyes.py`) - Main eye animation engine using pi3d graphics
2. **Mouth Control System** (`mouth.py`) - Servo-based mouth movement via UDP
3. **Thermal Tracking System** (`thermal_tracker.py`) - AMG8833 thermal camera-based eye tracking
4. **MQTT Animation Daemon** (`editor/animationDaemon.py`) - Orchestrates synchronized audio/animation playback

## Architecture

### Core Components
- `eyes.py`: Main eye rendering engine with UDP control interface (port 5005)
- `mouth.py`: Servo motor controller listening on UDP (port 5006) 
- `thermal_tracker.py`: AMG8833 thermal camera tracker sending to eyes (port 5007 status)
- `thermal_debug.py`: Calibration and debugging utilities for thermal tracking
- `eyeRemote.py`: Remote control client for PS4 controller input and recording
- `fbx2.c`: Low-level framebuffer graphics driver (C binary)
- `gfxutil.py`: Graphics utilities and mathematical functions

### Animation System
- `editor/`: Complete animation studio with GUI editor
  - `main.py`: Main GUI application entry point
  - `animationDaemon.py`: MQTT service daemon for animation orchestration
  - `bundlePlayer.py`: Plays synchronized animation packages
  - `animation_protocol.py`: Communication protocol definitions
  - Controllers for eye/mouth coordination and joystick input

### Graphics Assets
- `graphics/`: SVG eye models, textures (iris.jpg, sclera.png, lid.png)

## Common Commands

### Building
```bash
# Build the framebuffer driver
make

# Clean build artifacts
make clean
```

### Testing
```bash
# Test mouth servo control directly
python test_mouth.py

# Test mouth with mouse input
python test_mouth_mouse.py
```

### Development
```bash
# Run eye controller with remote UDP control
python eyes.py --radius 240

# Run mouth servo controller
python mouth.py --port 5006 --pin 22

# Remote control with PS4 controller
python eyeRemote.py -i <pi_ip> -p 5005

# Record animations with PS4 controller (press SHARE to start/stop)
python eyeRemote.py -i <pi_ip> -p 5005

# Playback recorded animations
python eyeRemote.py -i <pi_ip> -p 5005 -r recording.csv

# Run animation studio GUI
cd editor && python main.py

# Run thermal tracking (requires AMG8833 sensor) - use python3 on Pi
python3 thermal_tracker.py --eye-host <pi_ip> --sensitivity 5.0 --debug

# Debug and calibrate thermal tracking - use python3 on Pi
python3 thermal_debug.py --test-service
python3 thermal_debug.py --calibrate
python3 thermal_debug.py --live-display
```

### Deployment
```bash
# Deploy to Raspberry Pi (uses sshpass with credentials in script)
./deploy.sh

# Deployment script copies eyes.py and thermal_tracker.py to Pi
# Automatically restarts thermal_tracker service if enabled
# Reboots Pi to restart eyes.py
```

### Service Management
```bash
# Install and manage mouth service
sudo systemctl enable mouth.service
sudo systemctl start mouth.service
sudo systemctl status mouth.service

# Install and manage MQTT animation service
sudo systemctl enable mqtt.service  
sudo systemctl start mqtt.service
sudo systemctl status mqtt.service

# Install and manage thermal tracking service
sudo systemctl enable thermal_tracker.service
sudo systemctl start thermal_tracker.service
sudo systemctl status thermal_tracker.service
```

## Development Notes

### Eye Control Protocol
- Eyes listen on UDP port 5005 by default
- Control packet format includes joystick X/Y, blink states, and auto-mode flags
- Graphics rendered using pi3d with OpenGL ES on Raspberry Pi

### Mouth Control Protocol  
- Mouth servo listens on UDP port 5006 by default
- Position values range 0-255, mapped to servo PWM signals
- Requires pigpio daemon (`sudo pigpiod`) for hardware PWM

### Thermal Tracking Protocol
- Thermal tracker sends eye position commands to port 5005 (eyes)
- Status/configuration interface on UDP port 5007
- Uses temperature-weighted centroid algorithm for gaze direction
- Requires Adafruit AMG8833 thermal camera via I2C
- Command format: `0x20` + x_byte + y_byte (same as eye controller)
- Integrates with eye controller by sending `joystick_connected`/`joystick_disconnected` messages
- See [THERMAL_INSTALLATION.md](THERMAL_INSTALLATION.md) for detailed setup, tuning, and troubleshooting

### Animation Package Format
- `.skelanim` files contain synchronized audio and animation data
- Packages include eye movements, mouth positions, and audio tracks
- MQTT interface allows remote triggering of animation playback

### Dependencies
- **Python Version**: Python 3.7+ (Raspberry Pi OS has Python 2.7 as `python` and Python 3.7+ as `python3`)
- **Important**: Use `python3` for all thermal tracking commands on the Pi
- Python packages: `pi3d`, `pygame`, `paho-mqtt`, `pigpio`, `svg.path`, `pydub`
- Thermal tracking: `adafruit-circuitpython-amg88xx`, `board`, `busio`
- System: `pigpiod` daemon for servo control, I2C enabled for thermal sensor
- Hardware: Adafruit Snake Eyes Bonnet or compatible Pi display setup, AMG8833 thermal camera

### Graphics Pipeline
- SVG eye models parsed and rendered in real-time
- Texture mapping for iris/sclera using OpenGL ES
- Eyelid animations using mathematical curves
- Frame buffer output via custom `fbx2` driver

### MQTT Integration
- Topic structure: `robot/{robot-name}/...`
- Supports animation playback, system control (reboot/shutdown)
- Status reporting and real-time state updates
- Animation files must be in configured directory for security