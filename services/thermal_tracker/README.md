# Thermal Eye Tracker Service

Automatic eye tracking service for Pi_Eyes using the Adafruit AMG8833 IR thermal camera. Tracks heat sources (people, faces, etc.) and automatically directs the robot's gaze toward them.

## Features

- **Thermal Tracking**: Automatically directs eyes toward heat sources
- **UDP Control**: Communicates with eyes service on port 5005
- **Status Interface**: UDP port 5007 for configuration and monitoring
- **Smooth Motion**: Configurable smoothing and position thresholds
- **Auto-Fallback**: Seamlessly hands control back to autonomous eye movement
- **Systemd Service**: Auto-start on boot with automatic restart
- **Debug Tools**: Testing and calibration utilities included

## Directory Structure

```
thermal_tracker/
├── thermal_tracker.py           # Main service daemon
├── test_thermal_tracker.py      # Test/debug/calibration client
├── amg8833_simple.py           # AMG8833 sensor interface
├── thermal_tracker.service      # Systemd service file
├── deploy.sh                    # Deployment script (gitignored)
├── deploy.sh.example            # Deployment template
└── README.md                    # This file
```

## Prerequisites

1. **Base Pi_Eyes Installation**: Follow the installation steps in the main [README.md](README.md) first
2. **Hardware**: Adafruit AMG8833 IR Thermal Camera Breakout
3. **I2C**: Enable I2C on Raspberry Pi (`sudo raspi-config` > Interface Options > I2C)
4. **Python Dependencies**: Install smbus for I2C communication
   ```bash
   sudo apt install python3-smbus
   ```

**Note**: Always use `python3` (not `python`) for thermal tracking commands on the Pi.

## Installation

### 1. Install Dependencies on Raspberry Pi

Before deploying, ensure I2C and smbus are configured on your Pi:

```bash
# SSH into your Pi
ssh sshpi@<pi_ip>

# Enable I2C interface
sudo raspi-config
# > Interface Options > I2C > Enable

# Install smbus for Python 3
sudo apt-get update
sudo apt-get install -y python3-smbus

# Verify installation
python3 -c "import smbus; print('smbus installed successfully')"

# Add user to i2c and gpio groups
sudo usermod -a -G i2c,gpio sshpi
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
- Enable I2C if not already enabled
- Add user to i2c and gpio groups
- Enable and start the service

## Usage

### Testing from Development Machine

The `test_thermal_tracker.py` utility provides debugging and calibration tools:

#### Test Service Connection
```bash
python3 test_thermal_tracker.py --test-service
```

#### Live Thermal Display
```bash
python3 test_thermal_tracker.py --live-display
```

#### Interactive Calibration
```bash
python3 test_thermal_tracker.py --calibrate
```

#### Set Sensitivity
```bash
python3 test_thermal_tracker.py --sensitivity 7.5
```

#### Test Eye Commands
```bash
python3 test_thermal_tracker.py --test-eyes
```

### Service Management

```bash
# Check status
ssh <pi_ip> 'sudo systemctl status thermal_tracker.service'

# Start service
ssh <pi_ip> 'sudo systemctl start thermal_tracker.service'

# Stop service
ssh <pi_ip> 'sudo systemctl stop thermal_tracker.service'

# Restart service
ssh <pi_ip> 'sudo systemctl restart thermal_tracker.service'

# View logs
ssh <pi_ip> 'sudo journalctl -u thermal_tracker.service -f'

# Enable on boot
ssh <pi_ip> 'sudo systemctl enable thermal_tracker.service'

# Disable on boot
ssh <pi_ip> 'sudo systemctl disable thermal_tracker.service'
```

### Running Manually (Development)

```bash
# Run on Pi with debug output
python3 thermal_tracker.py --debug --sensitivity 7.5

# Custom parameters
python3 thermal_tracker.py \
    --eye-host 127.0.0.1 \
    --eye-port 5005 \
    --thermal-port 5007 \
    --rate 5.0 \
    --sensitivity 5.0 \
    --position-threshold 0.05 \
    --smoothing 0.7
```

## Configuration

### Command-Line Parameters

The thermal tracker supports several parameters to tune performance and smoothness:

```bash
# Basic usage with all parameters
python3 thermal_tracker.py \
    --eye-host 127.0.0.1 \
    --eye-port 5005 \
    --thermal-port 5007 \
    --rate 5.0 \
    --sensitivity 5.0 \
    --position-threshold 0.05 \
    --smoothing 0.7 \
    --debug
```

#### Performance & Smoothness Parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `--rate` | 5.0 | 1.0-20.0 | Update rate in Hz. Lower values reduce CPU load and eye jitter. Start with 5.0, reduce to 3.0 or 2.0 if eyes are jittery. |
| `--position-threshold` | 0.05 | 0.01-0.2 | Minimum position change (0-1 scale) to trigger an eye update. Higher values reduce micro-jitters but may feel less responsive. |
| `--smoothing` | 0.7 | 0.0-0.9 | Exponential smoothing factor. Higher values create smoother motion but slower response. 0.0=no smoothing (jittery), 0.9=very smooth (sluggish). |
| `--sensitivity` | 5.0 | 0.1-20.0 | Thermal sensitivity multiplier. Higher values make eyes more responsive to temperature differences. |

#### Common Tuning Scenarios

**Eyes are jittery/jumpy:**
```bash
# Increase smoothing and threshold, reduce rate
--smoothing 0.8 --position-threshold 0.1 --rate 3.0
```

**Tracking feels sluggish:**
```bash
# Decrease smoothing, reduce threshold
--smoothing 0.5 --position-threshold 0.03
```

**High CPU usage / frame drops:**
```bash
# Reduce update rate
--rate 2.0 --position-threshold 0.1
```

**Not sensitive enough to heat sources:**
```bash
# Increase sensitivity
--sensitivity 8.0
```

### Runtime Configuration

The thermal tracker can also be configured via UDP commands on port 5007:

```bash
# Test connection and get current settings
echo "status" | nc -u 127.0.0.1 5007

# Set sensitivity (0.1-20.0) - takes effect immediately
echo "sensitivity=8.0" | nc -u 127.0.0.1 5007
```

### Systemd Service Configuration

To permanently change settings, edit the service file at `/etc/systemd/system/thermal_tracker.service`:

```bash
sudo nano /etc/systemd/system/thermal_tracker.service
```

Modify the `ExecStart` line with your desired parameters:

```ini
ExecStart=/usr/bin/python3 /boot/Pi_Eyes/thermal_tracker.py \
    --eye-host 127.0.0.1 \
    --eye-port 5005 \
    --thermal-port 5007 \
    --rate 5.0 \
    --sensitivity 5.0 \
    --position-threshold 0.05 \
    --smoothing 0.7
```

Then reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart thermal_tracker.service
```

## Wiring AMG8833 to Raspberry Pi

| AMG8833 Pin | Snake Eyes Bonnet | Description |
|-------------|-------------------|-------------|
| VIN         | 3.3V (labelled)   | Power       |
| GND         | GND (labelled)    | Ground      |
| SDA         | SDA (labelled     | I2C Data    |
| SCL         | SCL (labelled)    | I2C Clock   |

## Troubleshooting

1. **"Warning: AMG8833 simple interface not available"**: The `amg8833_simple.py` file is missing. Make sure you copied it to `/boot/Pi_Eyes/` along with `thermal_tracker.py`. Also install smbus: `sudo apt install python3-smbus`
2. **"Error initializing AMG8833"**: Check I2C wiring and enable I2C with `sudo raspi-config`
3. **"Service not responding"**: Check if service is running with `systemctl status thermal_tracker.service`
4. **Poor tracking**: Adjust sensitivity with `python3 thermal_debug.py --sensitivity X`
5. **Import errors**: Make sure you're using `python3` not `python` on the Pi
6. **I2C permission errors**: Add user to i2c group: `sudo usermod -a -G i2c sshpi`

## Algorithm Details

The tracking uses a temperature-weighted centroid calculation:
- Each thermal pixel's position is weighted by its temperature
- The centroid is calculated and scaled to eye movement range (-1.0 to 1.0)
- Higher sensitivity values make the eyes more responsive to smaller temperature differences
- The system sends standard eye position commands (0x20 + x_byte + y_byte) to port 5005

**Inspiration**: This implementation is based on Adafruit's [Monster M4sk "Watch the Watcher"](https://learn.adafruit.com/monster-m4sk-is-watching-you/watch-the-watcher) project, which uses thermal camera pixel averaging for eye tracking. The concept has been adapted from CircuitPython for the Monster M4sk to Python 3 for the Snake Eyes Bonnet. Original code: [Monster_M4sk_Watching_You](https://github.com/adafruit/Adafruit_Learning_System_Guides/tree/main/Monster_M4sk_Watching_You)

## Expected Behavior

The thermal tracking system integrates with Pi_Eyes' built-in autonomous movement:

1. **Heat Source Detected** (magnitude > 2.0): 
   - Thermal tracker takes control (`joystick_connected` command)
   - Eyes track the heat source (person's face, hand, etc.) smoothly
   - Pi_Eyes autonomous movement is disabled during tracking
   - Debug output: `Tracking: x=0.123, y=0.456, heat=7.8`

2. **No Heat Source** (magnitude ≤ 2.0):
   - Thermal tracker releases control (`joystick_disconnected` command)
   - **Pi_Eyes resumes its built-in autonomous movement** (random, natural patterns)
   - This maintains the robot's lifelike behavior when no one is present
   - Debug output: `No heat detected (magnitude=1.2), using auto movement`

3. **Sensor Error**:
   - Thermal tracker releases control to Pi_Eyes autonomous movement
   - Debug output: `Sensor data unavailable, using auto movement`

**This design properly hands control between thermal tracking and the original Pi_Eyes autonomous behavior**, ensuring smooth transitions and natural movement when not tracking.

## UDP Protocol

The thermal tracker communicates using two UDP interfaces:

### Eye Control (Port 5005)

Sends commands to the eye controller:

| Command | Byte | Payload | Description |
|---------|------|---------|-------------|
| Controller Connected | `0x01` | none | Disable autonomous movement |
| Controller Disconnected | `0x00` | none | Enable autonomous movement |
| Eye Position | `0x20` | 2 bytes (x, y) | Set eye position (0-255 range) |

### Status Interface (Port 5007)

Receives status requests and configuration commands:

```python
import socket
import json

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Get status
sock.sendto(b'status', ('127.0.0.1', 5007))
data, addr = sock.recvfrom(1024)
status = json.loads(data.decode('utf-8'))
print(status)

# Set sensitivity
command = b'sensitivity=7.5'
sock.sendto(command, ('127.0.0.1', 5007))
```

## Integration with Other Services

The thermal tracker runs independently and integrates with:

- **Eye Controller** (`eyes.py`): Sends position commands and controller status
- **MQTT Animation Daemon**: Can be disabled during thermal tracking
- **Sound Player**: Can trigger sounds based on tracking events (future enhancement)
- **Custom Scripts**: Any service that can send UDP packets to port 5007

## Development

### File Locations on Pi

- Service Script: `/boot/Pi_Eyes/thermal_tracker.py`
- Sensor Interface: `/boot/Pi_Eyes/amg8833_simple.py`
- Systemd Unit: `/etc/systemd/system/thermal_tracker.service`

### Dependencies

- Python 3.7+
- smbus (I2C communication)
- Standard library: socket, struct, threading, json, argparse

### Version History

- **v1.0.0** - Initial release with UDP control, smoothing, and systemd integration

## License

Follows Pi_Eyes project license (see root LICENSE file).