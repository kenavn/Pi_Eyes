#!/usr/bin/env python3
import paho.mqtt.client as mqtt
import argparse
import time
import json
import signal
import sys
import os
import subprocess
from enum import Enum
from pathlib import Path
from typing import Optional
from bundlePlayer import BundlePlayer


class PlayerStatus(Enum):
    IDLE = "idle"
    PLAYING = "playing"


class AnimationDaemon:
    def __init__(
        self,
        mqtt_host: str,
        mqtt_port: int,
        mqtt_user: str,
        mqtt_pass: str,
        robot_name: str,
        robot_host: str,
        eye_port: int,
        mouth_port: int,
        animations_dir: str,
    ):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.mqtt_user = mqtt_user
        self.mqtt_pass = mqtt_pass
        self.robot_name = robot_name
        self.robot_host = robot_host
        self.eye_port = eye_port
        self.mouth_port = mouth_port
        self.animations_dir = Path(animations_dir).resolve()

        # Verify animations directory
        if not self.animations_dir.is_dir():
            raise ValueError(
                f"Animations directory does not exist: {self.animations_dir}"
            )

        # Initialize MQTT client
        self.client = mqtt.Client()
        if mqtt_user and mqtt_pass:
            self.client.username_pw_set(mqtt_user, mqtt_pass)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        # Initialize player
        self.player: Optional[BundlePlayer] = None
        self.current_animation = None
        self.status = PlayerStatus.IDLE

        # Topic structure
        self.base_topic = f"robot/{robot_name}"
        self.command_topics = {
            "play": f"{self.base_topic}/animation/play",
            "stop": f"{self.base_topic}/animation/stop",
            "status": f"{self.base_topic}/status",
            "system": f"{self.base_topic}/system",
        }

    def start(self):
        """Start the daemon"""
        print(f"Starting Animation Daemon for robot: {self.robot_name}")
        print(f"Animations directory: {self.animations_dir}")

        # Connect to MQTT broker with last will
        try:
            self.client.will_set(
                self.command_topics["status"],
                json.dumps({"online": False}),
                qos=1,
                retain=True,
            )
            self.client.connect(self.mqtt_host, self.mqtt_port, 60)
            print(f"Connected to MQTT broker at {self.mqtt_host}:{self.mqtt_port}")

            # Publish online status
            self.publish_status()

        except Exception as e:
            print(f"Failed to connect to MQTT broker: {e}")
            sys.exit(1)

        # Create player
        self.player = BundlePlayer(self.robot_host, self.eye_port, self.mouth_port)

        # Start MQTT loop
        self.client.loop_forever()

    def publish_status(self):
        """Publish current status"""
        status_data = {
            "online": True,
            "state": self.status.value,
            "current_animation": (
                self.current_animation if self.current_animation else None
            ),
        }
        self.client.publish(
            self.command_topics["status"], json.dumps(status_data), qos=1, retain=True
        )

    def validate_animation_file(self, filename: str) -> Optional[Path]:
        """Validate that the animation file exists and is within animations directory"""
        try:
            print(f"Validating file: {filename}")
            print(f"Animations directory: {self.animations_dir}")

            file_path = Path(filename)
            if not file_path.is_absolute():
                file_path = self.animations_dir / file_path

            file_path = file_path.resolve()
            print(f"Resolved path: {file_path}")

            # Check if the file is within the animations directory
            if self.animations_dir in file_path.parents and file_path.exists():
                print(f"File validation successful: {file_path}")
                return file_path

            print(
                f"File validation failed - file: {file_path}, animations dir: {self.animations_dir}"
            )
            if not file_path.exists():
                print(f"File does not exist")
            if self.animations_dir not in file_path.parents:
                print(f"File is not in animations directory")
            return None

        except Exception as e:
            print(f"Error validating animation file: {e}")
            import traceback

            traceback.print_exc()
            return None

    def handle_system_command(self, command: str):
        """Handle system commands"""
        try:
            if command == "shutdown":
                print("Executing shutdown command...")
                self.client.publish(
                    self.command_topics["status"],
                    json.dumps({"online": False}),
                    qos=1,
                    retain=True,
                )
                self.client.disconnect()
                # Perform system shutdown
                subprocess.run("sudo shutdown -h now", shell=True)
            elif command == "reboot":
                print("Executing reboot command...")
                self.client.publish(
                    self.command_topics["status"],
                    json.dumps({"online": False}),
                    qos=1,
                    retain=True,
                )
                self.client.disconnect()
                # Perform system reboot
                subprocess.run("sudo reboot", shell=True)
            else:
                print(f"Unknown system command: {command}")
        except Exception as e:
            print(f"Error executing system command: {e}")

    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals"""
        print("\nShutting down...")
        if self.player:
            self.player.cleanup()

        # Publish offline status
        self.client.publish(
            self.command_topics["status"],
            json.dumps({"online": False}),
            qos=1,
            retain=True,
        )

        self.client.disconnect()
        sys.exit(0)

    def on_connect(self, client, userdata, flags, rc):
        """Called when connected to MQTT broker"""
        print(f"Connected to MQTT broker with result code {rc}")

        # Subscribe to control topics
        for topic in self.command_topics.values():
            client.subscribe(topic)
            print(f"Subscribed to {topic}")

        # Publish initial status
        self.publish_status()

    def on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        try:
            if msg.topic == self.command_topics["play"]:
                payload = json.loads(msg.payload)
                self.handle_play_command(payload)
            elif msg.topic == self.command_topics["stop"]:
                self.handle_stop_command()
            elif msg.topic == self.command_topics["system"]:
                payload = json.loads(msg.payload)
                command = payload.get("command")
                if command:
                    self.handle_system_command(command)

        except json.JSONDecodeError:
            print(f"Error: Invalid JSON payload in message")
        except Exception as e:
            print(f"Error handling message: {e}")

    def handle_play_command(self, payload):
        """Handle play command from MQTT"""
        try:
            filename = payload.get("file")
            delay_ms = payload.get("delay", 0)
            loop = payload.get("loop", False)

            if not filename:
                print("Error: No filename provided in play command")
                return

            # Validate file path
            file_path = self.validate_animation_file(filename)
            if not file_path:
                print(f"Error: Invalid animation file path: {filename}")
                return

            print(f"Playing animation: {file_path} (delay: {delay_ms}ms, loop: {loop})")

            # Stop any current playback
            if self.player:
                self.player.is_playing = False

            # Load and play new animation
            if self.player.prepare_bundle(str(file_path)):
                self.status = PlayerStatus.PLAYING
                self.current_animation = file_path.name
                self.publish_status()

                self.player.start_delay_ms = delay_ms
                self.player.play_bundle(loop)

                self.status = PlayerStatus.IDLE
                self.current_animation = None
                self.publish_status()
                print(f"Finished playing: {file_path}")
            else:
                print(f"Failed to load animation: {file_path}")

        except Exception as e:
            print(f"Error in play command: {e}")
            self.status = PlayerStatus.IDLE
            self.current_animation = None
            self.publish_status()

    def handle_stop_command(self):
        """Handle stop command from MQTT"""
        if self.player:
            self.player.is_playing = False
            self.status = PlayerStatus.IDLE
            self.current_animation = None
            self.publish_status()
            print("Stopping current animation")


def main():
    parser = argparse.ArgumentParser(description="Animation Daemon")
    parser.add_argument("--mqtt-host", default="localhost", help="MQTT broker host")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--mqtt-user", help="MQTT username")
    parser.add_argument("--mqtt-pass", help="MQTT password")
    parser.add_argument(
        "--robot-name", required=True, help="Robot name for MQTT topics"
    )
    parser.add_argument("--robot-host", default="127.0.0.1", help="Robot host IP")
    parser.add_argument(
        "--eye-port", type=int, default=5005, help="UDP port for eye control"
    )
    parser.add_argument(
        "--mouth-port", type=int, default=5006, help="UDP port for mouth control"
    )
    parser.add_argument(
        "--animations-dir", required=True, help="Directory containing animation files"
    )

    args = parser.parse_args()

    daemon = AnimationDaemon(
        args.mqtt_host,
        args.mqtt_port,
        args.mqtt_user,
        args.mqtt_pass,
        args.robot_name,
        args.robot_host,
        args.eye_port,
        args.mouth_port,
        args.animations_dir,
    )

    daemon.start()


if __name__ == "__main__":
    main()
