import socket
import time
import threading
import struct
from typing import Optional
from queue import Queue


class EyeController:
    def __init__(self, ip: str, port: int, joystick_controller):
        # Socket setup
        self.UDP_IP = ip
        self.UDP_PORT = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Control state
        self.joystick_enabled = True

        # State variables
        self.current_eye_x = 0.5
        self.current_eye_y = 0.5
        self.current_eyelid = 0
        self.left_eye_closed = False
        self.right_eye_closed = False

        # Button command handling
        self.button_command_queue = Queue()
        self.button_command_thread = threading.Thread(
            target=self._process_button_commands, daemon=True
        )
        self.button_command_thread.start()

        # Button state tracking for recording
        self.prev_button_states = {
            "BTN_WEST": 0,  # Left eye
            "BTN_EAST": 0,  # Right eye
            "BTN_SOUTH": 0,  # Both eyes
        }

        # Subscribe to joystick
        self.joystick_controller = joystick_controller
        self.joystick_controller.subscribe(self._handle_joystick_update)

        # Send initial commands
        self.send_message("joystick_connected")
        self.send_message("auto_movement_off")
        self.send_message("auto_blink_off")
        self.send_message("auto_pupil_off")

        print("EyeController: Initialized")

    def _process_button_commands(self):
        """Process button commands with retries"""
        while True:
            try:
                command = self.button_command_queue.get()
                # Send command multiple times to ensure delivery
                for _ in range(2):
                    self.send_message(command)
                    time.sleep(0.01)  # 10ms between sends
                time.sleep(0.04)  # 40ms before next command
                self.button_command_queue.task_done()
            except Exception as e:
                print(f"EyeController: Error processing button command: {e}")

    def _handle_joystick_update(self, state):
        """Handle joystick state updates"""
        try:
            if self.joystick_enabled:
                # Update button states for recording
                if state.btn_west != self.prev_button_states["BTN_WEST"]:
                    self.prev_button_states["BTN_WEST"] = state.btn_west
                    self.button_command_queue.put(
                        "blink_left_start" if state.btn_west else "blink_left_end"
                    )
                    self.left_eye_closed = bool(state.btn_west)

                if state.btn_east != self.prev_button_states["BTN_EAST"]:
                    self.prev_button_states["BTN_EAST"] = state.btn_east
                    self.button_command_queue.put(
                        "blink_right_start" if state.btn_east else "blink_right_end"
                    )
                    self.right_eye_closed = bool(state.btn_east)

                if state.btn_south != self.prev_button_states["BTN_SOUTH"]:
                    self.prev_button_states["BTN_SOUTH"] = state.btn_south
                    if state.btn_south:
                        self.button_command_queue.put("blink_both_start")
                        self.left_eye_closed = self.right_eye_closed = True
                    else:
                        self.button_command_queue.put("blink_both_end")
                        self.left_eye_closed = self.right_eye_closed = False

                # Handle eye position (left stick)
                x = (state.left_x - 128) / 128.0
                y = (state.left_y - 128) / 128.0

                # Add deadzone
                x = x if abs(x) > 0.1 else 0
                y = y if abs(y) > 0.1 else 0

                # Map to 0-1 range
                eye_x = (x + 1) / 2
                eye_y = (-y + 1) / 2  # Invert Y axis

                # Send position if changed significantly
                if (
                    abs(eye_x - self.current_eye_x) > 0.03
                    or abs(eye_y - self.current_eye_y) > 0.03
                ):
                    self.current_eye_x = eye_x
                    self.current_eye_y = eye_y
                    self.send_message(f"joystick,{eye_x:.2f},{eye_y:.2f}")

                # Handle eyelid position (right stick)
                eyelid_pos = (255 - state.right_y) / 255.0
                if abs(eyelid_pos - self.current_eyelid) > 0.05:
                    self.current_eyelid = eyelid_pos
                    self.send_message(f"left_eyelid,{eyelid_pos:.2f}")
                    self.send_message(f"right_eyelid,{eyelid_pos:.2f}")

        except Exception as e:
            print(f"EyeController: Error handling joystick update: {e}")

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

    def apply_recorded_movement(self, current_time, eye_data):
        """Apply recorded eye movements during playback"""
        if not self.joystick_enabled:  # Only apply during playback
            frame_to_play = None
            for frame in eye_data:
                if frame[0] <= current_time:
                    frame_to_play = frame
                else:
                    break

            if frame_to_play:
                time_ms, x, y, left_blink, right_blink, both_eyes = frame_to_play

                # Apply eye position
                if (x != self.current_eye_x) or (y != self.current_eye_y):
                    self.current_eye_x = x
                    self.current_eye_y = y
                    self.send_message(f"joystick,{x:.2f},{y:.2f}")
                    print(f"Applied eye position: X={x:.2f}, Y={y:.2f}")

                # Apply blink states
                if both_eyes:
                    if not self.left_eye_closed or not self.right_eye_closed:
                        self.send_message("blink_both_start")
                        self.left_eye_closed = self.right_eye_closed = True
                else:
                    if left_blink != self.left_eye_closed:
                        self.send_message(
                            "blink_left_start" if left_blink else "blink_left_end"
                        )
                        self.left_eye_closed = left_blink
                    if right_blink != self.right_eye_closed:
                        self.send_message(
                            "blink_right_start" if right_blink else "blink_right_end"
                        )
                        self.right_eye_closed = right_blink

                print(
                    f"Applied blink states - Left: {left_blink}, Right: {right_blink}, Both: {both_eyes}"
                )

    def send_message(self, message: str):
        """Send UDP message"""
        try:
            encoded_message = self.encode_message(message)
            self.sock.sendto(encoded_message, (self.UDP_IP, self.UDP_PORT))
            print(f"EyeController: Sent {message}")
        except Exception as e:
            print(f"EyeController: Error sending message: {e}")

    def cleanup(self):
        """Clean up resources"""
        print("EyeController: Cleaning up...")

        # Unsubscribe from joystick
        self.joystick_controller.unsubscribe(self._handle_joystick_update)

        # End any active blinks
        if self.left_eye_closed:
            self.send_message("blink_left_end")
        if self.right_eye_closed:
            self.send_message("blink_right_end")

        # Re-enable auto features
        self.send_message("joystick_disconnected")
        self.send_message("auto_movement_on")
        self.send_message("auto_blink_on")
        self.send_message("auto_pupil_on")

        # Close socket
        self.sock.close()
        print("EyeController: Cleanup complete")
