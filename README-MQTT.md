# MQTT Controller for Robot Head Management

## Overview

The MQTT controller provides a way to manage scripts and Bluetooth connections through MQTT messages. All topics are prefixed with `heads/{client_name}/` where `{client_name}` is specified when starting the service.

## Starting the Service

```bash
python3 mqtt_service.py \
    --name [client_name] \
    --host [mqtt_broker] \
    --port [mqtt_port] \
    --username [mqtt_username] \
    --password [mqtt_password] \
    --debug  # Optional, for verbose logging
```

## MQTT Topics Structure

### Control Topics

Topics used to send commands to the controller:

#### Script Management

1. Start a script:

```
Topic: heads/{client_name}/control/script/start
Payload: {
    "id": "unique_script_id",
    "path": "/path/to/script.py"
}
```

2. Stop a script:

```
Topic: heads/{client_name}/control/script/stop
Payload: {
    "id": "unique_script_id"
}
```

3. Get script status:

```
Topic: heads/{client_name}/control/script/status
Payload: {
    "id": "unique_script_id"  # Optional - omit for all scripts
}
```

#### Bluetooth Management

1. Connect to a Bluetooth device:

```
Topic: heads/{client_name}/control/bluetooth/connect
Payload: {
    "address": "XX:XX:XX:XX:XX:XX"
}
```

### Status Topics

Topics where the controller publishes status updates:

#### Script Status Updates

```
Topic: heads/{client_name}/status/script/{script_id}
Payload: {
    "id": "script_id",
    "status": "status_value",
    "timestamp": unix_timestamp,
    "error": "error_message"  # Only present if there was an error
}
```

Possible status values:

- `running`: Script is currently executing
- `finished`: Script completed successfully
- `failed`: Script failed with error
- `stopped`: Script was manually stopped
- `killed`: Script was forcefully terminated
- `not_found`: Script ID doesn't exist

#### All Scripts Status

```
Topic: heads/{client_name}/status/scripts
Payload: {
    "script_id_1": {
        "status": "status_value",
        "runtime": seconds_since_start,
        "path": "/path/to/script.py"
    },
    "script_id_2": {
        ...
    }
}
```

#### Bluetooth Status

```
Topic: heads/{client_name}/status/bluetooth
Payload: {
    "status": "status_value",
    "address": "XX:XX:XX:XX:XX:XX",
    "error": "error_message"  # Only present if there was an error
}
```

Possible status values:

- `connected`: Successfully connected to device
- `failed`: Failed to connect
- `disconnected`: Device disconnected

## Example Usage

### Starting a Script

```bash
mosquitto_pub -t "heads/head1/control/script/start" \
    -m '{"id": "eyes1", "path": "/scripts/wherever/eyes.py"}'
```

### Stopping the Eyes Script

```bash
mosquitto_pub -t "heads/head1/control/script/stop" \
    -m '{"id": "eyes1"}'
```

### Connecting to a Bluetooth Speaker

```bash
mosquitto_pub -t "heads/head1/control/bluetooth/connect" \
    -m '{"address": "00:11:22:33:44:55"}'
```

### Getting Status of All Running Scripts

```bash
mosquitto_pub -t "heads/head1/control/script/status" \
    -m '{}'
```

## Monitoring Status Updates

You can monitor all status updates using:

```bash
mosquitto_sub -v -t "heads/head1/status/#"
```

## Notes

- Scripts are run asynchronously, allowing multiple scripts to run simultaneously
- Each script must have a unique ID
- Starting a script with an ID that's already running will result in an error
- The service automatically cleans up any running scripts on shutdown
- All Bluetooth connections are automatically closed on shutdown
