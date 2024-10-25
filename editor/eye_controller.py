import socket
import time
import threading
import csv
from datetime import datetime
import queue
from inputs import devices, get_gamepad
import struct


class EyeController:
    def __init__(self, ip, port):
        self.UDP_IP = ip
        self.UDP_PORT = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Joystick and eye state variables
        self.current_eye_x = 0.5
        self.current_eye_y = 0.5
        self.current_left_eyelid = 0
        self.current_right_eyelid = 0
        self.left_eye_closed = False
        self.right_eye_closed = False

        # Add joystick enable flag
        self.joystick_enabled = True  # Add this line

        # Gamepad state tracking
        self.gamepad_state = {
            "ABS_X": 0,  # Left stick X
            "ABS_Y": 0,  # Left stick Y
            "ABS_RX": 0,  # Right stick X
            "ABS_RY": 0,  # Right stick Y
            "BTN_WEST": 0,  # Square on PS4, X on Xbox
            "BTN_EAST": 0,  # Circle on PS4, B on Xbox
            "BTN_SOUTH": 0,  # X on PS4, A on Xbox
            "BTN_NORTH": 0,  # Triangle on PS4, Y on Xbox
        }

        # Track previous button states
        self.prev_button_states = {"BTN_WEST": 0, "BTN_EAST": 0, "BTN_SOUTH": 0}

        # Recording related variables
        self.is_recording = False
        self.recording_start_time = None
        self.recorded_data = []  # Store frames in memory
        self.record_queue = queue.Queue()  # For temporary storage during recording
        self.writer_thread = None

        # Thread control
        self.running = True
        self.controller_thread = None
        self.eye_control_thread = None

        # Initialize joystick control
        self.detect_controller()
        self.start_controller_thread()
        self.connect_joystick()

    def detect_controller(self):
        """Detect and identify the controller type"""
        print("Available devices:", [device.name for device in devices])
        self.controller_type = None
        for device in devices:
            if "XBOX" in device.name.upper():
                self.controller_type = "xbox"
                break
            elif "SONY" in device.name.upper() or "PS4" in device.name.upper():
                self.controller_type = "ps4"
                break
            elif "GAMEPAD" in device.name.upper():
                self.controller_type = "gamepad"
                break

        if self.controller_type:
            print(f"Detected {self.controller_type.upper()} controller")
        else:
            print("No compatible controller detected. Please connect a controller.")

    def encode_message(self, command):
        """Encode command messages for UDP transmission"""
        if command == "joystick_connected":
            return b"\x01"
        elif command == "joystick_disconnected":
            return b"\x00"
        elif command == "auto_movement_on":
            return b"\x11"
        elif command == "auto_movement_off":
            return b"\x10"
        elif command == "auto_blink_on":
            return b"\x13"
        elif command == "auto_blink_off":
            return b"\x12"
        elif command == "auto_pupil_on":
            return b"\x15"
        elif command == "auto_pupil_off":
            return b"\x14"
        elif command.startswith("joystick"):
            _, x, y = command.split(",")
            x_byte = int(float(x) * 255)
            y_byte = int(float(y) * 255)
            return b"\x20" + struct.pack("BB", x_byte, y_byte)
        elif command.startswith("left_eyelid"):
            _, position = command.split(",")
            pos_byte = int(float(position) * 255)
            return b"\x30" + struct.pack("B", pos_byte)
        elif command.startswith("right_eyelid"):
            _, position = command.split(",")
            pos_byte = int(float(position) * 255)
            return b"\x31" + struct.pack("B", pos_byte)
        elif command == "blink_left_start":
            return b"\x40"
        elif command == "blink_left_end":
            return b"\x41"
        elif command == "blink_right_start":
            return b"\x42"
        elif command == "blink_right_end":
            return b"\x43"
        elif command == "blink_both_start":
            return b"\x44"
        elif command == "blink_both_end":
            return b"\x45"
        else:
            raise ValueError(f"Unknown command: {command}")

    def start_controller_thread(self):
        """Start the controller and eye control threads"""
        self.controller_thread = threading.Thread(
            target=self.gamepad_reader, daemon=True
        )
        self.controller_thread.start()

        self.eye_control_thread = threading.Thread(
            target=self.eye_controller, daemon=True
        )
        self.eye_control_thread.start()

    def connect_joystick(self):
        """Connect joystick and disable auto features"""
        self.send_message("joystick_connected")
        self.send_message("auto_movement_off")
        self.send_message("auto_blink_off")
        self.send_message("auto_pupil_off")
        print("Joystick connected and auto features disabled")

    def gamepad_reader(self):
        """Read gamepad events and update state"""
        print("Gamepad reader thread started")
        while self.running:
            try:
                events = get_gamepad()
                for event in events:
                    if event.code in self.gamepad_state:
                        self.gamepad_state[event.code] = event.state
            except Exception as e:
                print(f"Gamepad error: {e}")
                time.sleep(0.1)

    def eye_controller(self):
        """Main eye control loop"""
        print("Eye controller thread started")
        while self.running:
            try:
                if self.joystick_enabled:
                    # Get joystick values
                    x = self.gamepad_state.get("ABS_X", 0)
                    y = self.gamepad_state.get("ABS_Y", 0)

                    # Map from observed range (0-255) to -1 to 1
                    x = (x - 128) / 128.0  # Maps 0->-1, 128->0, 255->1
                    y = (y - 128) / 128.0

                    # Add deadzone
                    x = x if abs(x) > 0.1 else 0
                    y = y if abs(y) > 0.1 else 0

                    # Map to 0-1 range
                    eye_x = (x + 1) / 2
                    eye_y = (-y + 1) / 2  # Invert Y axis

                    # Send eye position if changed significantly
                    if (
                        abs(eye_x - self.current_eye_x) > 0.01
                        or abs(eye_y - self.current_eye_y) > 0.01
                    ):
                        self.current_eye_x = eye_x
                        self.current_eye_y = eye_y
                        self.send_message(f"joystick,{eye_x:.2f},{eye_y:.2f}")

                    # Handle eyelid control
                    ry = self.gamepad_state.get("ABS_RY", 0)
                    eyelid_pos = (
                        (-ry / 128.0 + 1) / 2
                        if abs(ry - 128) > 12
                        else self.current_left_eyelid
                    )

                    if abs(eyelid_pos - self.current_left_eyelid) > 0.01:
                        self.current_left_eyelid = eyelid_pos
                        self.current_right_eyelid = eyelid_pos
                        self.send_message(f"left_eyelid,{eyelid_pos:.2f}")
                        self.send_message(f"right_eyelid,{eyelid_pos:.2f}")

                    # Handle button state changes
                    # Left eye (Square/X button on Xbox)
                    if (
                        self.gamepad_state["BTN_WEST"]
                        != self.prev_button_states["BTN_WEST"]
                    ):
                        if self.gamepad_state["BTN_WEST"] == 1:
                            self.send_message("blink_left_start")
                        else:
                            self.send_message("blink_left_end")
                        self.prev_button_states["BTN_WEST"] = self.gamepad_state[
                            "BTN_WEST"
                        ]

                    # Right eye (Circle/B button)
                    if (
                        self.gamepad_state["BTN_EAST"]
                        != self.prev_button_states["BTN_EAST"]
                    ):
                        if self.gamepad_state["BTN_EAST"] == 1:
                            self.send_message("blink_right_start")
                        else:
                            self.send_message("blink_right_end")
                        self.prev_button_states["BTN_EAST"] = self.gamepad_state[
                            "BTN_EAST"
                        ]

                    # Both eyes (X/A button)
                    if (
                        self.gamepad_state["BTN_SOUTH"]
                        != self.prev_button_states["BTN_SOUTH"]
                    ):
                        if self.gamepad_state["BTN_SOUTH"] == 1:
                            self.send_message("blink_both_start")
                        else:
                            self.send_message("blink_both_end")
                        self.prev_button_states["BTN_SOUTH"] = self.gamepad_state[
                            "BTN_SOUTH"
                        ]

                    # Record state if recording is active
                    if self.is_recording:
                        self.record_state()

                    pass

                time.sleep(0.016)  # ~60Hz update rate

            except Exception as e:
                print(f"Eye controller error: {e}")
                time.sleep(0.1)

    def start_recording(self):
        """Start recording eye movements to memory"""
        if not self.is_recording:
            self.recorded_data = []  # Clear any previous recording
            self.recording_start_time = datetime.now()
            self.is_recording = True

            # Start the memory writer thread
            self.writer_thread = threading.Thread(
                target=self.memory_writer, daemon=True
            )
            self.writer_thread.start()
            print("Recording started")

    def stop_recording(self):
        """Stop recording and process remaining queue items"""
        if self.is_recording:
            self.is_recording = False
            if self.writer_thread:
                self.writer_thread.join()  # Wait for remaining frames
            print(f"Recording stopped. {len(self.recorded_data)} frames captured")

    def clear_recording(self):
        """Clear the current recording from memory"""
        self.recorded_data = []
        print("Recording cleared from memory")

    def save_recording(self, filename=None):
        """Save the current recording to a CSV file"""
        if not self.recorded_data:
            print("No recording data to save")
            return False

        if not filename:
            print("No filename provided")
            return False

        try:
            with open(filename, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "time_ms",
                        "eye_x",
                        "eye_y",
                        "left_eyelid",
                        "right_eyelid",
                        "left_eye_closed",
                        "right_eye_closed",
                    ]
                )
                writer.writerows(self.recorded_data)
            print(f"Recording saved to {filename}")
            return True
        except Exception as e:
            print(f"Error saving recording: {e}")
            return False

    def apply_recorded_movement(self, current_time, eye_data):
        """Apply recorded eye movements during playback"""
        frame_to_play = None
        for frame in eye_data:
            if frame[0] <= current_time:
                frame_to_play = frame
            else:
                break

        if frame_to_play:
            time_ms, x, y, left_blink, right_blink, both_eyes = frame_to_play
            if (x != self.current_eye_x) or (y != self.current_eye_y):
                self.current_eye_x = x
                self.current_eye_y = y
                command = f"joystick,{x:.2f},{y:.2f}"
                self.send_message(command)
                print(
                    f"EyeController: Applied eye frame at {current_time}ms: X={x:.2f}, Y={y:.2f}"
                )

            # Handle blinks
            self.set_blink_state(left=left_blink, right=right_blink, both=both_eyes)

    def record_state(self):
        """Add current state to recording queue"""
        if self.is_recording:
            current_time = datetime.now()
            time_ms = int(
                (current_time - self.recording_start_time).total_seconds() * 1000
            )

            state = [
                time_ms,
                self.current_eye_x,
                self.current_eye_y,
                self.current_left_eyelid,
                self.current_right_eyelid,
                self.prev_button_states["BTN_WEST"] == 1,  # left eye closed
                self.prev_button_states["BTN_EAST"] == 1,  # right eye closed
            ]

            self.record_queue.put(state)

    def memory_writer(self):
        """Write queued states to memory"""
        while self.is_recording or not self.record_queue.empty():
            try:
                state = self.record_queue.get(timeout=0.1)
                self.recorded_data.append(state)
                self.record_queue.task_done()
            except queue.Empty:
                continue

    def send_message(self, message):
        """Send UDP message to the eye device"""
        try:
            encoded_message = self.encode_message(message)
            self.sock.sendto(encoded_message, (self.UDP_IP, self.UDP_PORT))
            print(f"Sent UDP: {message} (encoded: {encoded_message.hex()})")
        except Exception as e:
            print(f"Error sending message: {e}")

    def disable_joystick(self):
        """Disable joystick input"""
        self.joystick_enabled = False
        print("Joystick control disabled")

    def enable_joystick(self):
        """Enable joystick input"""
        self.joystick_enabled = True
        print("Joystick control enabled")

    def set_position(self, x, y):
        """Set eye position directly (for playback)"""
        if not self.joystick_enabled:
            print(f"Setting eye position: X={x:.3f}, Y={y:.3f}")
            self.current_eye_x = x
            self.current_eye_y = y
            command = f"joystick,{x:.2f},{y:.2f}"
            self.send_message(command)

    def blink_left(self, state):
        """Control left eye blink"""
        if not self.joystick_enabled:
            if state != self.left_eye_closed:
                command = "blink_left_start" if state else "blink_left_end"
                print(f"Setting left blink: {command}")
                self.send_message(command)
                self.left_eye_closed = state

    def blink_right(self, state):
        """Control right eye blink"""
        if not self.joystick_enabled:
            if state != self.right_eye_closed:
                command = "blink_right_start" if state else "blink_right_end"
                print(f"Setting right blink: {command}")
                self.send_message(command)
                self.right_eye_closed = state

    def blink_both(self, state):
        """Control both eyes blink"""
        if not self.joystick_enabled:
            if state != (self.left_eye_closed and self.right_eye_closed):
                command = "blink_both_start" if state else "blink_both_end"
                print(f"Setting both blinks: {command}")
                self.send_message(command)
                self.left_eye_closed = state
                self.right_eye_closed = state

    def set_blink_state(self, left=False, right=False, both=False):
        """Set blink state directly (for playback)"""
        if not self.joystick_enabled:
            if both:
                self.send_message("blink_both_start" if both else "blink_both_end")
            else:
                if left != self.left_eye_closed:
                    self.send_message("blink_left_start" if left else "blink_left_end")
                if right != self.right_eye_closed:
                    self.send_message(
                        "blink_right_start" if right else "blink_right_end"
                    )

            self.left_eye_closed = left or both
            self.right_eye_closed = right or both

    def cleanup(self):
        """Clean up resources and threads"""
        self.running = False
        if self.controller_thread:
            self.controller_thread.join(timeout=1)
        if self.eye_control_thread:
            self.eye_control_thread.join(timeout=1)
        if self.is_recording:
            self.stop_recording()
        self.send_message("joystick_disconnected")
        self.send_message("auto_movement_on")
        self.send_message("auto_blink_on")
        self.send_message("auto_pupil_on")
        self.sock.close()
