# Sound Player Service

UDP-based audio playback service for Pi_Eyes. Plays MP3/WAV/OGG/FLAC files through the Raspberry Pi audio jack via UDP commands.

## Features

- **UDP Control**: Listen on port 5008 for playback commands
- **Multiple Formats**: Supports MP3, WAV, OGG, and FLAC
- **Named Playback**: Trigger specific sound files by name
- **Random Playback**: Play random sounds from a directory
- **Volume Control**: Adjust volume via UDP commands
- **Non-blocking**: Runs alongside other Pi_Eyes services
- **Systemd Service**: Auto-start on boot with automatic restart

## Directory Structure

```
sound_player/
├── sound_player.py           # Main service daemon
├── test_sound_player.py      # Test/control client
├── sound_player.service      # Systemd service file
├── deploy.sh                 # Deployment script (gitignored)
├── deploy.sh.example         # Deployment template
├── README.md                 # This file
└── sounds/                   # Sound files directory
    ├── README.md             # Sound files documentation
    ├── .gitkeep              # Keeps directory in git
    └── random/               # Random sound selection
        └── .gitkeep
```

## Installation

### 1. Install Dependencies on Raspberry Pi

Before deploying, ensure pygame is installed and audio is configured on your Pi:

```bash
# SSH into your Pi
ssh sshpi@<pi_ip>

# Install pygame for Python 3
sudo apt-get update
sudo apt-get install -y python3-pygame

# Verify installation
python3 -c "import pygame; print('pygame installed successfully')"

# Set audio output to 3.5mm jack (option 1: headphones)
# This ensures sound plays through the audio jack, not HDMI
sudo raspi-config nonint do_audio 1

# Alternative: Set to HDMI (option 0)
# sudo raspi-config nonint do_audio 0

# Or use interactive menu
# sudo raspi-config
# > System Options > Audio > Choose output device
```

### 2. Deploy to Raspberry Pi

```bash
# Copy deploy.sh.example to deploy.sh and update credentials
cp deploy.sh.example deploy.sh
nano deploy.sh  # Edit PI_HOST and PI_PASSWORD

# Deploy the service
./deploy.sh
```

The deployment script will:
- Copy service files to the Pi
- Install systemd service
- Create sound directories
- Copy any local sound files
- Enable and start the service

### 3. Add Sound Files

Copy your audio files to the Pi:

```bash
# Copy specific sound files
scp mysound.mp3 sshpi@192.168.1.100:/boot/Pi_Eyes/sounds/

# Copy random sounds
scp *.mp3 sshpi@192.168.1.100:/boot/Pi_Eyes/sounds/random/
```

Or add them locally to the `sounds/` directory for testing.

## Usage

### Testing from Development Machine

The `test_sound_player.py` utility provides both interactive and command-line modes:

#### Interactive Mode
```bash
python test_sound_player.py -i <pi_ip>
```

Commands in interactive mode:
- `play <filename>` - Play specific sound
- `random` - Play random sound
- `stop` - Stop playback
- `volume <0-100>` - Set volume
- `quit` - Exit

#### Command-Line Mode
```bash
# Play specific sound
python test_sound_player.py -i <pi_ip> --play mysound.mp3

# Play random sound
python test_sound_player.py -i <pi_ip> --random

# Stop current playback
python test_sound_player.py -i <pi_ip> --stop

# Set volume
python test_sound_player.py -i <pi_ip> --volume 75
```

### Service Management

```bash
# Check status
ssh <pi_ip> 'sudo systemctl status sound_player.service'

# Start service
ssh <pi_ip> 'sudo systemctl start sound_player.service'

# Stop service
ssh <pi_ip> 'sudo systemctl stop sound_player.service'

# Restart service
ssh <pi_ip> 'sudo systemctl restart sound_player.service'

# View logs
ssh <pi_ip> 'sudo journalctl -u sound_player.service -f'

# Enable on boot
ssh <pi_ip> 'sudo systemctl enable sound_player.service'

# Disable on boot
ssh <pi_ip> 'sudo systemctl disable sound_player.service'
```

### Running Manually (Development)

```bash
# Run on Pi
python3 sound_player.py --port 5008 --volume 1.0

# Custom directories
python3 sound_player.py \
    --sounds-dir /path/to/sounds \
    --random-dir /path/to/random \
    --port 5008 \
    --volume 0.8
```

## UDP Protocol

The service listens on UDP port 5008 (default) for binary commands:

### Command Format

| Command | Byte | Payload | Description |
|---------|------|---------|-------------|
| Play Specific | `0x60` | null-terminated string | Play named sound file |
| Play Random | `0x61` | none | Play random sound |
| Stop | `0x62` | none | Stop current playback |
| Set Volume | `0x63` | 1 byte (0-100) | Set volume percentage |

### Examples

```python
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Play specific file
message = b'\x60' + b'mysound.mp3\x00'
sock.sendto(message, ('192.168.1.100', 5008))

# Play random
sock.sendto(b'\x61', ('192.168.1.100', 5008))

# Stop
sock.sendto(b'\x62', ('192.168.1.100', 5008))

# Set volume to 75%
import struct
message = struct.pack('BB', 0x63, 75)
sock.sendto(message, ('192.168.1.100', 5008))
```

## Configuration

### Service Configuration

Edit `/etc/systemd/system/sound_player.service` on the Pi:

```ini
[Service]
ExecStart=/usr/bin/python3 /boot/Pi_Eyes/sound_player.py \
    --sounds-dir /boot/Pi_Eyes/sounds \
    --random-dir /boot/Pi_Eyes/sounds/random \
    --port 5008 \
    --volume 1.0
```

After editing, reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart sound_player.service
```

### Audio Output

By default, audio plays through the Pi's 3.5mm jack. To use HDMI audio:

```bash
# Check available audio devices
aplay -l

# Set default output (add to /etc/asound.conf)
sudo nano /etc/asound.conf
```

## Troubleshooting

### Service Won't Start

```bash
# Check service status
sudo systemctl status sound_player.service

# View full logs
sudo journalctl -u sound_player.service -n 50

# Check if pygame is installed
python3 -c "import pygame; print('OK')"

# If pygame is not installed:
sudo apt-get update
sudo apt-get install -y python3-pygame

# Verify audio permissions (replace 'sshpi' with your username)
groups sshpi  # Should include 'audio'
```

### No Audio Output

If the service is running but you don't hear any sound:

```bash
# Check which audio devices are available
aplay -l

# Set audio output to 3.5mm headphone jack
sudo raspi-config nonint do_audio 1

# Set audio output to HDMI
sudo raspi-config nonint do_audio 0

# Restart the service after changing audio output
sudo systemctl restart sound_player.service

# Test audio directly with speaker-test
speaker-test -t wav -c 2

# Check volume levels
alsamixer

# Verify sound is not muted and volume is up
```

**Common causes:**
- Audio is routed to HDMI instead of headphone jack (or vice versa)
- Volume is muted or too low
- No speakers/headphones connected to the 3.5mm jack
- Wrong audio output selected in raspi-config

### UDP Commands Not Working

```bash
# Check if service is listening
sudo netstat -ulnp | grep 5008

# Test with netcat
echo -ne '\x61' | nc -u <pi_ip> 5008

# Check firewall (unlikely on local network)
sudo ufw status
```

## Integration with Other Services

The sound player runs independently and can be triggered by:

- **MQTT Animation Daemon**: Add sound triggers to animation bundles
- **Thermal Tracker**: Trigger sounds based on thermal events
- **Eye Controller**: Coordinate sounds with eye movements
- **Custom Scripts**: Any service that can send UDP packets

## Development

### File Locations on Pi

- Service Script: `/boot/Pi_Eyes/sound_player.py`
- Systemd Unit: `/etc/systemd/system/sound_player.service`
- Sound Files: `/boot/Pi_Eyes/sounds/`
- Random Sounds: `/boot/Pi_Eyes/sounds/random/`

### Dependencies

- Python 3.7+
- pygame (audio playback)
- Standard library: socket, struct, threading, pathlib

### Version History

- **v1.0.0** - Initial release with UDP control, multi-format support, and systemd integration

## License

Follows Pi_Eyes project license (see root LICENSE file).
