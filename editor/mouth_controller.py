import socket
import time
import threading
import struct
from typing import Optional
from queue import Queue


class MouthController:
    def __init__(self, ip: str, port: int, joystick_controller):
        # Socket setup
        self.UDP_IP = ip
        self.UDP_PORT = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # State variables
        self.current_mouth_position = 128  # Initial mouth position (0-255)
        self.joystick_enabled = True

        # Subscribe to joystick
        self.joystick_controller = joystick_controller
        self.joystick_controller.subscribe(self._handle_joystick_update)

        print("MouthController: Initialized")

    def _handle_joystick_update(self, state):
        """Handle joystick state updates"""
        try:
            if self.joystick_enabled:
                # Use right stick vertical axis for mouth control
                ry = state.right_y

                # Map from 0-255 to -1 to 1
                ry = (ry - 128) / 128.0

                # Add deadzone
                ry = ry if abs(ry) > 0.05 else 0

                # Map to 0-255 range for mouth position
                # Note: Changed to store actual position value
                mouth_position = int(((ry + 1) / 2) * 255)

                # Send mouth position if changed significantly
                if abs(mouth_position - self.current_mouth_position) > 2:
                    self.current_mouth_position = mouth_position
                    self.send_message(f"mouth,{mouth_position}")

        except Exception as e:
            print(f"MouthController: Error handling joystick update: {e}")

    def encode_message(self, command):
        """Encode command messages for UDP transmission"""
        if command.startswith("mouth"):
            _, position = command.split(",")
            pos_byte = int(position)  # Should be 0-255
            return b"\x50" + struct.pack("B", pos_byte)
        else:
            raise ValueError(f"MouthController: Unknown command: {command}")

    def send_message(self, message: str):
        """Send UDP message"""
        try:
            encoded_message = self.encode_message(message)
            self.sock.sendto(encoded_message, (self.UDP_IP, self.UDP_PORT))
            print(f"MouthController: Sent {message}")
        except Exception as e:
            print(f"MouthController: Error sending message: {e}")

    def apply_recorded_movement(self, current_time, mouth_data):
        """Apply recorded mouth movements during playback"""
        if not self.joystick_enabled:  # Only apply during playback
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

    def cleanup(self):
        """Clean up resources"""
        print("MouthController: Cleaning up...")

        # Unsubscribe from joystick
        self.joystick_controller.unsubscribe(self._handle_joystick_update)

        # Close socket
        self.sock.close()
        print("MouthController: Cleanup complete")
