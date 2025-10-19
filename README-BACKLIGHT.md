# Backlight Control for Snake Eyes Bonnet

Control the brightness of the TFT/IPS LED panels via GPIO 18 (LITE pin).

## Quick Test (Manual)

Before installing as a service, test it manually:

```bash
# On your Raspberry Pi
sudo python3 /boot/Pi_Eyes/backlight.py --brightness 128
```

This sets brightness to 50% (128/255). You should see the displays dim immediately.

Press `Ctrl+C` to stop. The backlight will return to full brightness on exit.

## Installation (As a Service)

Follow these steps to install backlight control as a system service:

### 1. Copy files to Raspberry Pi

```bash
# Copy the backlight script
sudo cp backlight.py /boot/Pi_Eyes/

# Make it executable
sudo chmod +x /boot/Pi_Eyes/backlight.py

# Copy the service file
sudo cp backlight.service /etc/systemd/system/
```

### 2. Enable and start the service

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable backlight.service

# Start the service now
sudo systemctl start backlight.service
```

### 3. Check status

```bash
sudo systemctl status backlight.service
```

## Configuration Options

Edit `/etc/systemd/system/backlight.service` to change settings:

```
ExecStart=/usr/bin/python3 /boot/Pi_Eyes/backlight.py --brightness 200 --port 5007 --freq 1000
```

### Available options:

| Option       | Description                          | Default |
| ------------ | ------------------------------------ | ------- |
| --pin        | GPIO pin for backlight               | 18      |
| --brightness | Initial brightness (0-255)           | 255     |
| --port       | UDP port to listen on                | 5007    |
| --freq       | PWM frequency in Hz                  | 1000    |

After changing, restart the service:
```bash
sudo systemctl restart backlight.service
```

## Remote Control via UDP

### Protocol

Send UDP packets to port 5007 (default):

**Set Brightness Command (0x60)**
- Byte 0: `0x60` (command type)
- Byte 1: Brightness value (0-255)

### Python Example

```python
import socket
import struct

# Connect to Raspberry Pi
UDP_IP = "192.168.1.2"  # Your Pi's IP
UDP_PORT = 5007

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Set brightness to 50% (128/255)
brightness = 128
message = struct.pack('BB', 0x60, brightness)
sock.sendto(message, (UDP_IP, UDP_PORT))
```

## Troubleshooting

### Service won't start
- Check pigpiod is running: `sudo systemctl status pigpiod`
- If not: `sudo systemctl start pigpiod && sudo systemctl enable pigpiod`

### No brightness change
- Verify GPIO 18 is the LITE pin on your bonnet
- Check for conflicts: `gpio readall` (look for GPIO 18)
- Try different PWM frequencies: `--freq 100` to `--freq 10000`

### Brightness changes but flickers
- Increase PWM frequency: `--freq 5000` or `--freq 10000`
- Lower frequencies (100-500 Hz) may show visible flicker

## Uninstall

```bash
sudo systemctl stop backlight.service
sudo systemctl disable backlight.service
sudo rm /etc/systemd/system/backlight.service
sudo systemctl daemon-reload
```
