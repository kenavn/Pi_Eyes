# Animation Daemon Documentation

The Animation Daemon is a Python service that controls robot animations via MQTT commands. It manages eye and mouth animations, handles audio playback, and provides status updates about the robot's current state.

## Installation

### Requirements

- Python 3.7+
- paho-mqtt
- pygame (for audio playback)

### Dependencies

```bash
pip install paho-mqtt pygame
```

## Running the Daemon

```bash
python animation_daemon.py \
  --mqtt-host mqtt.example.com \
  --mqtt-port 1883 \
  --mqtt-user "username" \
  --mqtt-pass "password" \
  --robot-name robot1 \
  --robot-host 192.168.1.100 \
  --animations-dir /path/to/animations
```

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

## MQTT Interface

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
  "state": "idle",
  "current_animation": null
}
```

or

```json
{
  "online": true,
  "state": "playing",
  "current_animation": "animation1.skelanim"
}
```

or when offline:

```json
{
  "online": false
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
  "loop": false
}
```

| Field | Type    | Description                                    | Required            |
| ----- | ------- | ---------------------------------------------- | ------------------- |
| file  | string  | Animation filename (must be in animations-dir) | Yes                 |
| delay | number  | Delay in milliseconds before starting          | No (default: 0)     |
| loop  | boolean | Whether to loop the animation                  | No (default: false) |

#### Stop Animation

- Topic: `robot/{robot-name}/animation/stop`
- Direction: Input
- Message Format: `{}` (empty JSON object)

#### System Commands

- Topic: `robot/{robot-name}/system`
- Direction: Input
- Message Format:

```json
{
  "command": "shutdown"
}
```

or

```json
{
  "command": "reboot"
}
```

## Example Usage

### Monitor Robot Status

```bash
mosquitto_sub -h mqtt.example.com -u username -P password \
  -t "robot/robot1/status"
```

### Play Animation

```bash
mosquitto_pub -h mqtt.example.com -u username -P password \
  -t "robot/robot1/animation/play" \
  -m '{"file":"animation1.skelanim","delay":200,"loop":false}'
```

### Stop Current Animation

```bash
mosquitto_pub -h mqtt.example.com -u username -P password \
  -t "robot/robot1/animation/stop" \
  -m '{}'
```

### Shutdown Robot

```bash
mosquitto_pub -h mqtt.example.com -u username -P password \
  -t "robot/robot1/system" \
  -m '{"command":"shutdown"}'
```

### Reboot Robot

```bash
mosquitto_pub -h mqtt.example.com -u username -P password \
  -t "robot/robot1/system" \
  -m '{"command":"reboot"}'
```

## Security Notes

1. The daemon only allows playing animation files from within the specified animations directory
2. System commands (shutdown/reboot) require appropriate system permissions
3. MQTT communication should ideally be secured using TLS
4. Authentication credentials should be kept secure

## Status Messages

### Online Status

The daemon uses MQTT's last will feature to notify when the robot goes offline unexpectedly. The status topic will be updated with `{"online": false}` if the daemon disconnects abnormally.

### Animation States

- `idle`: No animation is currently playing
- `playing`: An animation is currently being played

## Error Handling

- Invalid animation files will be rejected
- Attempts to access files outside the animations directory will be blocked
- MQTT connection failures will be reported
- UDP communication errors will be logged

## Startup Sequence

1. Connects to MQTT broker with authentication
2. Sets up last will message
3. Publishes initial online status
4. Subscribes to command topics
5. Begins processing MQTT messages

## Shutdown Sequence

1. Stops any playing animation
2. Publishes offline status
3. Closes MQTT connection
4. Cleans up resources
