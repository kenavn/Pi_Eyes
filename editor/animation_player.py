#!/usr/bin/env python3
import argparse
import socket
import time
import sys
from animation_protocol import (
    FileFormat,
    CommandType,
    UDPProtocol,
    DEFAULT_HOST,
    DEFAULT_EYE_PORT,
    DEFAULT_MOUTH_PORT,
)


class AnimationPlayer:
    def __init__(self, host: str, eye_port: int, mouth_port: int):
        """Initialize the movement player with network settings"""
        self.host = host
        self.eye_port = eye_port
        self.mouth_port = mouth_port

        # Create UDP sockets
        self.eye_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.mouth_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Track current states
        self.current_eye_x = 0.5
        self.current_eye_y = 0.5
        self.left_eye_closed = False
        self.right_eye_closed = False
        self.current_mouth_position = 128

    def send_eye_command(self, command_type: CommandType, *args):
        """Send command to eye controller"""
        try:
            encoded = UDPProtocol.encode_eye_message(command_type, *args)
            self.eye_socket.sendto(encoded, (self.host, self.eye_port))
            print(f"Sent eye command: {command_type.name}")
        except Exception as e:
            print(f"Error sending eye command: {e}", file=sys.stderr)

    def send_mouth_position(self, position: int):
        """Send position to mouth controller"""
        try:
            encoded = UDPProtocol.encode_mouth_position(position)
            self.mouth_socket.sendto(encoded, (self.host, self.mouth_port))
            print(f"Sent mouth position: {position}")
        except Exception as e:
            print(f"Error sending mouth command: {e}", file=sys.stderr)

    def play_recording(self, filename: str, loop: bool = False):
        """Play back a recorded animation"""
        print(f"Playing recording from {filename}")

        while True:
            try:
                # Load frames using protocol module
                eye_frames, mouth_frames = FileFormat.load_from_csv(filename)

                # Combine and sort frames by timestamp
                all_frames = []
                all_frames.extend((frame.time_ms, "eye", frame) for frame in eye_frames)
                all_frames.extend(
                    (frame.time_ms, "mouth", frame) for frame in mouth_frames
                )
                all_frames.sort(key=lambda x: x[0])

                last_time = 0
                for time_ms, frame_type, frame in all_frames:
                    # Handle timing
                    time_diff = (time_ms - last_time) / 1000
                    if time_diff > 0:
                        time.sleep(time_diff)

                    # Apply frame
                    if frame_type == "eye":
                        # Handle eye position
                        if (
                            frame.x != self.current_eye_x
                            or frame.y != self.current_eye_y
                        ):
                            self.send_eye_command(
                                CommandType.EYE_POSITION,
                                int(frame.x * 255),
                                int(frame.y * 255),
                            )
                            self.current_eye_x, self.current_eye_y = frame.x, frame.y

                        # Handle blink states
                        if frame.both_closed:
                            if not (self.left_eye_closed and self.right_eye_closed):
                                self.send_eye_command(CommandType.BLINK_BOTH_START)
                                self.left_eye_closed = self.right_eye_closed = True
                        else:
                            if frame.left_closed != self.left_eye_closed:
                                self.send_eye_command(
                                    CommandType.BLINK_LEFT_START
                                    if frame.left_closed
                                    else CommandType.BLINK_LEFT_END
                                )
                                self.left_eye_closed = frame.left_closed
                            if frame.right_closed != self.right_eye_closed:
                                self.send_eye_command(
                                    CommandType.BLINK_RIGHT_START
                                    if frame.right_closed
                                    else CommandType.BLINK_RIGHT_END
                                )
                                self.right_eye_closed = frame.right_closed

                    else:  # mouth frame
                        if frame.position != self.current_mouth_position:
                            self.send_mouth_position(frame.position)
                            self.current_mouth_position = frame.position

                    last_time = time_ms

                if not loop:
                    break

                print("Looping playback...")
                time.sleep(0.5)  # Small pause between loops

            except KeyboardInterrupt:
                print
