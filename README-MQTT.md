# Robot Animation Service Documentation

This documentation covers both the setup of the systemd service and the MQTT animation daemon that controls robot animations. The system manages eye and mouth animations, handles audio playback, and provides status updates about the robot's current state.

This service is the "layer on top", and acts as the control interface in automation scenarios. It comes in addition to the simple UDP services that exists for the mouth and the eyes.

## System Requirements

- Python 3.7+
- paho-mqtt
- pygame (for audio playback)

```bash
pip install paho-mqtt pygame
```

## Service Setup

### Systemd Service Configuration

Create the service file at `/etc/systemd/system/mqtt.service`:

```ini
[Unit]
Description=Skeleton MQTT Service
After=network-online.target systemd-resolved.service
Wants=network-online.target systemd-resolved.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /boot/Pi_Eyes/animationDaemon.py \
    --mqtt-host mqtt.regins.no \
    --robot-name head1 \
    --animations-dir /etc/anim
Restart=on-failure
User=kenneth
Group=kenneth

# Network retry logic
ExecStartPre=/bin/sh -c 'until host mqtt.regins.no; do sleep 2; done'

# Runtime directory setup
RuntimeDirectory=user/1000/pulse
RuntimeDirectoryMode=0700

# Environment setup
Environment=PYTHONUNBUFFERED=1
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=HOME=/home/kenneth
Environment=DISPLAY=:0
Environment=PULSE_RUNTIME_PATH=/run/user/1000/pulse
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus

SupplementaryGroups=audio pulse-access

StartLimitBurst=5
StartLimitIntervalSec=60
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Installation Steps

1. Enable required services:

```bash
sudo systemctl enable systemd-networkd-wait-online.service
sudo systemctl enable systemd-resolved.service
```

2. Configure user permissions:

```bash
sudo usermod -aG audio,pulse,pulse-access kenneth
```

3. Install the python scripts:

   1. Copy the `editor/animationDaemon.py` file into `/boot/Pi_Eyes/` folder on the Raspberry Pi
      together with: `animation_protocol.py`, `audio_player.py` and `bundlePlayer.py`.
   2. `sudo chmod +x /boot/Pi_Eyes/mqtt_service.py`
   3. `sudo nano /etc/systemd/system/mqtt.service` Edit the client name and check credentials and script folder.

4. Install and start the service:

```bash
sudo cp mqtt.service /etc/systemd/system/mqtt.service
sudo systemctl daemon-reload
sudo systemctl enable mqtt
sudo systemctl restart systemd-resolved
sudo systemctl restart mqtt
```

## MQTT Interface

### Command Line Arguments

| Argument         | Description                          | Default   |
| ---------------- | ------------------------------------ | --------- |
| --mqtt-host      | MQTT broker hostname                 | localhost |
| --mqtt-port      | MQTT broker port                     | 1883      |
| --mqtt-user      | MQTT username                        | None      |
| --mqtt-pass      | MQTT password                        | None      |
| --robot-name     | Robot identifier for MQTT topics     | Required  |
| --robot-host     | Robot's IP address                   | 127.0.0.1 |
| --eye-port       | UDP port for eye control             | 5005      |
| --mouth-port     | UDP port for mouth control           | 5006      |
| --animations-dir | Directory containing animation files | Required  |

### Topic Structure

All topics follow the pattern: `robot/{robot-name}/...`

### Available Topics

#### Status Updates

- Topic: `robot/{robot-name}/status`
- Retained: Yes
- QoS: 1
- Message Format:

```json
{
  "online": true,
  "state": "idle|playing",
  "current_animation": null|"animation1.skelanim"
}
```

#### Play Animation

- Topic: `robot/{robot-name}/animation/play`
- Direction: Input
- Message Format:

```json
{
  "file": "animation1.skelanim",
  "delay": 200,
  "loop": false,
  "resume-auto": true
}
```

#### Stop Animation

- Topic: `robot/{robot-name}/animation/stop`
- Direction: Input
- Message Format: `{}`

#### System Commands

- Topic: `robot/{robot-name}/system`
- Direction: Input
- Message Format:

```json
{
  "command": "shutdown|reboot"
}
```

## Usage Examples

### Monitor Robot Status

```bash
mosquitto_sub -h mqtt.example.com -t "robot/head1/status"
```

### Play Animation

```bash
mosquitto_pub -h mqtt.example.com \
  -t "robot/head1/animation/play" \
  -m '{"file":"animation1.skelanim","delay":200,"loop":false,"resume-auto":true}'
```

### Stop Animation

```bash
mosquitto_pub -h mqtt.example.com \
  -t "robot/head1/animation/stop" -m '{}'
```

### System Control

```bash
# Shutdown
mosquitto_pub -h mqtt.example.com \
  -t "robot/head1/system" -m '{"command":"shutdown"}'

# Reboot
mosquitto_pub -h mqtt.example.com \
  -t "robot/head1/system" -m '{"command":"reboot"}'
```

## Security Notes

1. The daemon only allows playing animation files from within the specified animations directory
2. System commands (shutdown/reboot) require appropriate system permissions
3. MQTT communication should ideally be secured using TLS
4. The UDP listeners for eye/mouth control are unprotected - consider network security before exposing

## Troubleshooting

### Service Issues

1. Check service status:

```bash
sudo systemctl status mqtt
journalctl -u mqtt -f
```

2. Verify audio permissions:

```bash
groups kenneth
ls -la /run/user/1000/pulse
```

3. Test network connectivity:

```bash
ping mqtt.regins.no
```

### Common Issues

- Authentication failures: Check user/group permissions
- Network connectivity: Verify DNS resolution and network availability
- Audio problems: Check PulseAudio status and user group membership
- File access: Verify animations directory permissions and file locations

## Error Handling

- Invalid animation files will be rejected
- Attempts to access files outside the animations directory will be blocked
- MQTT connection failures will be reported in logs
- UDP communication errors will be logged
- Service failures will trigger automatic restart with appropriate delays
