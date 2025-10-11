# Thermal Eye Tracking Installation Guide

## Quick Start

The thermal tracking system uses an Adafruit AMG8833 thermal camera to automatically direct the robot's gaze toward heat sources (people, faces, etc.).

## Prerequisites

1. **Base Pi_Eyes Installation**: Follow the installation steps in the main [README.md](README.md) first
2. **Hardware**: Adafruit AMG8833 IR Thermal Camera Breakout
3. **I2C**: Enable I2C on Raspberry Pi (`sudo raspi-config` > Interface Options > I2C)
4. **Python Dependencies**: Install smbus for I2C communication
   ```bash
   sudo apt install python3-smbus
   ```

**Note**: Always use `python3` (not `python`) for thermal tracking commands on the Pi.

## Installation on Raspberry Pi

1. **Copy files to Pi**:
   ```bash
   scp thermal_tracker.py pi@your-pi:/boot/Pi_Eyes/
   scp thermal_debug.py pi@your-pi:/boot/Pi_Eyes/
   scp amg8833_simple.py pi@your-pi:/boot/Pi_Eyes/
   scp thermal_tracker.service pi@your-pi:~/
   ```

2. **Install service**:
   ```bash
   sudo mv ~/thermal_tracker.service /etc/systemd/system/
   sudo systemctl daemon-reload
   ```

3. **Enable automatic startup on boot**:
   ```bash
   sudo systemctl enable thermal_tracker.service
   sudo systemctl start thermal_tracker.service
   ```

4. **Check status**:
   ```bash
   sudo systemctl status thermal_tracker.service
   ```

5. **View service logs** (for troubleshooting):
   ```bash
   journalctl -u thermal_tracker.service -f
   ```

## Usage

### Manual Operation
```bash
# Run with debug output (use python3)
python3 thermal_tracker.py --debug --sensitivity 7.5

# Test and calibrate (use python3)
python3 thermal_debug.py --test-service
python3 thermal_debug.py --calibrate
python3 thermal_debug.py --live-display
```

### Service Management
```bash
# Start/stop service
sudo systemctl start thermal_tracker.service
sudo systemctl stop thermal_tracker.service

# View logs
journalctl -u thermal_tracker.service -f
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