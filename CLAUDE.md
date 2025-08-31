# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pi_Eyes is a modified fork of Adafruit's animated snake eyes project for Raspberry Pi. The system controls robotic eye animations with remote UDP control, PS4 controller recording/playback, mouth servo control, and MQTT-based animation management. It consists of three main components:

1. **Eye Control System** (`eyes.py`) - Main eye animation engine using pi3d graphics
2. **Mouth Control System** (`mouth.py`) - Servo-based mouth movement via UDP
3. **MQTT Animation Daemon** (`editor/animationDaemon.py`) - Orchestrates synchronized audio/animation playback

## Architecture

### Core Components
- `eyes.py`: Main eye rendering engine with UDP control interface (port 5005)
- `mouth.py`: Servo motor controller listening on UDP (port 5006) 
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
```

### Deployment
```bash
# Deploy to Raspberry Pi (modify IPs in script)
./deploy.sh
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

### Animation Package Format
- `.skelanim` files contain synchronized audio and animation data
- Packages include eye movements, mouth positions, and audio tracks
- MQTT interface allows remote triggering of animation playback

### Dependencies
- Python packages: `pi3d`, `pygame`, `paho-mqtt`, `pigpio`, `svg.path`, `pydub`
- System: `pigpiod` daemon for servo control
- Hardware: Adafruit Snake Eyes Bonnet or compatible Pi display setup

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