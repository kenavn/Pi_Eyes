import paho.mqtt.client as mqtt
import subprocess
import json
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional
import logging
from queue import Queue
import signal
import argparse
import asyncio
from bleak import BleakClient, BleakScanner
from functools import partial

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


@dataclass
class ScriptProcess:
    process: subprocess.Popen
    start_time: float
    script_path: str
    status: str = "running"
    thread: Optional[threading.Thread] = None


@dataclass
class BluetoothDevice:
    client: BleakClient
    connected: bool = False


class MQTTController:
    def __init__(
        self,
        client_name: str,
        broker: str = "localhost",
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.client_name = client_name
        self.client = mqtt.Client(
            client_id=client_name, callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.base_topic = f"heads/{client_name}"
        self.running_scripts: Dict[str, ScriptProcess] = {}
        self.command_queue = Queue()
        self.bluetooth_devices: Dict[str, BluetoothDevice] = {}

        # Create event loop for async operations
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        self.setup_mqtt()

        # Start command processing thread
        self.command_thread = threading.Thread(
            target=self.process_commands, daemon=True
        )
        self.command_thread.start()

        # Setup signal handlers
        signal.signal(signal.SIGTERM, self.cleanup)
        signal.signal(signal.SIGINT, self.cleanup)

    def setup_mqtt(self):
        """Setup MQTT callbacks and connection"""
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        if self.username and self.password:
            self.client.username_pw_set(self.username, self.password)
            logging.info(f"Using MQTT credentials for user: {self.username}")

        try:
            self.client.connect(self.broker, self.port, 60)
            logging.info(
                f"Connecting to MQTT broker {self.broker}:{self.port} as {self.client_name}"
            )
        except Exception as e:
            logging.error(f"Failed to connect to MQTT broker: {e}")
            raise

    def on_connect(self, client, userdata, flags, reason_code, properties):
        """Callback for when MQTT connection is established (Version 2)"""
        logging.info(f"Connected to MQTT broker with reason code {reason_code}")
        # Subscribe to control topics with new base topic
        topics = [
            f"{self.base_topic}/control/bluetooth/connect",
            f"{self.base_topic}/control/script/start",
            f"{self.base_topic}/control/script/stop",
            f"{self.base_topic}/control/script/status",
        ]
        for topic in topics:
            self.client.subscribe(topic)
            logging.info(f"Subscribed to {topic}")

    def on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages by putting them in the command queue"""
        try:
            payload = json.loads(msg.payload.decode())
            # Strip base topic from msg.topic for processing
            relative_topic = msg.topic.replace(f"{self.base_topic}/", "")
            self.command_queue.put((relative_topic, payload))
        except json.JSONDecodeError:
            logging.error(f"Invalid JSON payload: {msg.payload}")
        except Exception as e:
            logging.error(f"Error processing message: {e}")

    def process_commands(self):
        """Process commands from the queue"""
        while True:
            try:
                topic, payload = self.command_queue.get()
                if topic == "control/bluetooth/connect":
                    self.handle_bluetooth_connect(payload)
                elif topic == "control/script/start":
                    self.handle_script_start(payload)
                elif topic == "control/script/stop":
                    self.handle_script_stop(payload)
                elif topic == "control/script/status":
                    self.handle_script_status(payload)
            except Exception as e:
                logging.error(f"Error processing command {topic}: {e}")

    def handle_script_start(self, payload):
        """Handle script start requests"""
        try:
            script_id = payload.get("id")
            script_path = payload.get("path")

            if not script_id or not script_path:
                raise ValueError("Script ID and path are required")

            if script_id in self.running_scripts:
                raise ValueError(f"Script with ID {script_id} is already running")

            # Start the script in a separate process
            process = subprocess.Popen(
                ["python3", script_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            # Create monitoring thread for this script
            monitor_thread = threading.Thread(
                target=self.monitor_script, args=(script_id, process), daemon=True
            )

            # Store process information
            self.running_scripts[script_id] = ScriptProcess(
                process=process,
                start_time=time.time(),
                script_path=script_path,
                thread=monitor_thread,
            )

            # Start monitoring
            monitor_thread.start()
            self.publish_script_status(script_id, "running")

        except Exception as e:
            logging.error(f"Error starting script: {e}")
            self.publish_script_status(script_id, "failed", str(e))

    def handle_script_stop(self, payload):
        """Handle script stop requests"""
        script_id = payload.get("id")
        if not script_id:
            logging.error("No script ID provided for stop command")
            return

        if script_id in self.running_scripts:
            try:
                script_process = self.running_scripts[script_id]
                script_process.process.terminate()
                script_process.process.wait(timeout=5)
                self.publish_script_status(script_id, "stopped")
                self.running_scripts.pop(script_id, None)
            except subprocess.TimeoutExpired:
                script_process.process.kill()
                self.publish_script_status(script_id, "killed")
                self.running_scripts.pop(script_id, None)
            except Exception as e:
                logging.error(f"Error stopping script {script_id}: {e}")

    def handle_script_status(self, payload):
        """Handle script status requests"""
        script_id = payload.get("id")
        if script_id:
            if script_id in self.running_scripts:
                self.publish_script_status(
                    script_id, self.running_scripts[script_id].status
                )
            else:
                self.publish_script_status(script_id, "not_found")
        else:
            # Publish status of all scripts
            statuses = {
                script_id: {
                    "status": script.status,
                    "runtime": time.time() - script.start_time,
                    "path": script.script_path,
                }
                for script_id, script in self.running_scripts.items()
            }
            self.publish_status("scripts", statuses)

    def monitor_script(self, script_id: str, process: subprocess.Popen):
        """Monitor a running script and update its status"""
        try:
            process.wait()
            if script_id in self.running_scripts:
                if process.returncode == 0:
                    self.publish_script_status(script_id, "finished")
                else:
                    stderr = process.stderr.read().decode()
                    self.publish_script_status(script_id, "failed", stderr)

                # Clean up
                self.running_scripts.pop(script_id, None)

        except Exception as e:
            logging.error(f"Error monitoring script {script_id}: {e}")
            self.publish_script_status(script_id, "failed", str(e))

    def publish_status(self, subtopic: str, payload: dict):
        """Helper method to publish status messages with correct base topic"""
        full_topic = f"{self.base_topic}/status/{subtopic}"
        self.client.publish(full_topic, json.dumps(payload))
        logging.debug(f"Published to {full_topic}: {payload}")

    def publish_script_status(self, script_id: str, status: str, error: str = None):
        """Publish script status updates to MQTT"""
        payload = {"id": script_id, "status": status, "timestamp": time.time()}
        if error:
            payload["error"] = error

        self.publish_status(f"script/{script_id}", payload)

    def run(self):
        """Start the MQTT client loop"""
        try:
            self.client.loop_start()
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.cleanup(None, None)
        finally:
            self.client.loop_stop()

    def cleanup(self, signum, frame):
        """Clean up resources before shutting down"""
        logging.info("Cleaning up resources...")
        # Clean up running scripts
        for script_id, script_process in self.running_scripts.items():
            try:
                script_process.process.terminate()
                script_process.process.wait(timeout=2)
            except Exception:
                script_process.process.kill()

        self.client.disconnect()
        exit(0)


def main():
    parser = argparse.ArgumentParser(
        description="MQTT Controller for Scripts and Bluetooth"
    )
    parser.add_argument("--host", default="localhost", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--name", required=True, help="Client name for MQTT")
    parser.add_argument("--username", required=True, help="MQTT username")
    parser.add_argument("--password", required=True, help="MQTT password")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    controller = MQTTController(
        client_name=args.name,
        broker=args.host,
        port=args.port,
        username=args.username,
        password=args.password,
    )
    controller.run()


if __name__ == "__main__":
    main()
