# mouth_controller.py
import socket
import time
import threading
from datetime import datetime
import queue
from inputs import devices, get_gamepad
import struct


class MouthController:
    def __init__(self, ip, port):
        self.UDP_IP = ip
        self.UDP_PORT = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Mouth state variable
        self.current_mouth_position = 128  # Initial mouth position (0-255)

        # Mouth joystick enable flag
        self.joystick_enabled = True

        # Gamepad state tracking
        self.gamepad_state = {
            "ABS_RY": 0,  # Right stick vertical axis
        }

        # Recording related variables
        self.is_recording = False
        self.recording_start_time = None
        self.recorded_data = []
        self.record_queue = queue.Queue()
        self.writer_thread = None

        # Thread control
        self.running = True
        self.controller_thread = None
        self.mouth_control_thread = None

        # Initialize joystick control
        self.start_controller_thread()

    def start_controller_thread(self):
        """Start the controller and mouth control threads"""
        self.controller_thread = threading.Thread(
            target=self.gamepad_reader, daemon=True
        )
        self.controller_thread.start()

        self.mouth_control_thread = threading.Thread(
            target=self.mouth_controller_loop, daemon=True
        )
        self.mouth_control_thread.start()

    def gamepad_reader(self):
        """Read gamepad events and update state"""
        print("MouthController: Gamepad reader thread started")
        while self.running:
            try:
                events = get_gamepad()
                for event in events:
                    if event.code in self.gamepad_state:
                        self.gamepad_state[event.code] = event.state
            except Exception as e:
                print(f"MouthController: Gamepad error: {e}")
                time.sleep(0.1)

    def mouth_controller_loop(self):
        """Main mouth control loop"""
        print("MouthController: Mouth control thread started")
        while self.running:
            try:
                if self.joystick_enabled:
                    # Read right stick vertical axis for mouth control
                    ry = self.gamepad_state.get("ABS_RY", 128)

                    # Map from 0-255 to -1 to 1
                    ry = (ry - 128) / 128.0

                    # Add deadzone
                    ry = ry if abs(ry) > 0.05 else 0

                    # Map to 0-255 range for mouth position
                    mouth_position = int(((ry + 1) / 2) * 255)

                    # Send mouth position if changed significantly
                    if abs(mouth_position - self.current_mouth_position) > 2:
                        self.current_mouth_position = mouth_position
                        self.send_message(f"mouth,{mouth_position}")

                # Record state if recording is active
                if self.is_recording:
                    self.record_state()

                time.sleep(0.016)  # ~60Hz update rate

            except Exception as e:
                print(f"MouthController: Mouth control error: {e}")
                time.sleep(0.1)

    def send_message(self, message):
        """Send UDP message to the mouth device"""
        try:
            encoded_message = self.encode_message(message)
            self.sock.sendto(encoded_message, (self.UDP_IP, self.UDP_PORT))
            print(
                f"MouthController: Sent UDP: {message} (encoded: {encoded_message.hex()})"
            )
        except Exception as e:
            print(f"MouthController: Error sending message: {e}")

    def encode_message(self, command):
        """Encode command messages for UDP transmission"""
        if command.startswith("mouth"):
            _, position = command.split(",")
            pos_byte = int(position)  # Should be 0-255
            return b"\x50" + struct.pack("B", pos_byte)
        else:
            raise ValueError(f"MouthController: Unknown command: {command}")

    def record_state(self):
        """Add current state to recording queue"""
        if self.is_recording:
            current_time = datetime.now()
            time_ms = int(
                (current_time - self.recording_start_time).total_seconds() * 1000
            )

            state = [
                time_ms,
                self.current_mouth_position,
            ]

            self.record_queue.put(state)

    def start_recording(self):
        """Start recording mouth movements to memory"""
        if not self.is_recording:
            self.recorded_data = []  # Clear any previous recording
            self.recording_start_time = datetime.now()
            self.is_recording = True

            # Start the memory writer thread
            self.writer_thread = threading.Thread(
                target=self.memory_writer, daemon=True
            )
            self.writer_thread.start()
            print("MouthController: Recording started")

    def stop_recording(self):
        """Stop recording and process remaining queue items"""
        if self.is_recording:
            self.is_recording = False
            if self.writer_thread:
                self.writer_thread.join()  # Wait for remaining frames
            print(
                f"MouthController: Recording stopped. {len(self.recorded_data)} frames captured"
            )

    def memory_writer(self):
        """Write queued states to memory"""
        while self.is_recording or not self.record_queue.empty():
            try:
                state = self.record_queue.get(timeout=0.1)
                self.recorded_data.append(state)
                self.record_queue.task_done()
            except queue.Empty:
                continue

    def apply_recorded_movement(self, current_time, mouth_data):
        """Apply recorded mouth movements during playback"""
        frame_to_play = None
        for frame in mouth_data:
            if frame[0] <= current_time:
                frame_to_play = frame
            else:
                break

        if frame_to_play:
            time_ms, position = frame_to_play
            if position != self.current_mouth_position:
                self.current_mouth_position = position
                self.send_message(f"mouth,{position}")
                print(
                    f"MouthController: Applied mouth frame at {current_time}ms: Position={position}"
                )
        else:
            print(f"MouthController: No mouth frame to apply at {current_time}ms")

    def cleanup(self):
        """Clean up resources and threads"""
        self.running = False
        if self.controller_thread:
            self.controller_thread.join(timeout=1)
        if self.mouth_control_thread:
            self.mouth_control_thread.join(timeout=1)
        if self.is_recording:
            self.stop_recording()
        self.sock.close()
