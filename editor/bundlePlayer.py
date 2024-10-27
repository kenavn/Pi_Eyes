#!/usr/bin/env python3
import socket
import time
import struct
import sys
from dataclasses import dataclass
from typing import Optional, List, Dict
import pygame
import tempfile
import os
from animation_protocol import FileFormat, CommandType
from queue import Queue, Empty
import threading


class BundlePlayer:
    VERSION = "1.1.0"

    def __init__(
        self, host: str, eye_port: int, mouth_port: int, start_delay_ms: int = 0
    ):
        print(f"BundlePlayer Version {self.VERSION}")
        self.host = host
        self.eye_port = eye_port
        self.mouth_port = mouth_port
        self.start_delay_ms = start_delay_ms

        # Initialize state
        self.initialize_state()

        # Initialize networking and pygame only once
        self.initialize_networking()
        self.initialize_pygame()

    def initialize_state(self):
        """Initialize/reset internal state variables"""
        # Track current states
        self.current_eye_x = 0.5
        self.current_eye_y = 0.5
        self.left_eye_closed = False
        self.right_eye_closed = False
        self.current_mouth_position = 128

        # Animation state
        self.eye_data = []
        self.mouth_data = []
        self.is_playing = False
        self.current_time = 0
        self.recording_start_time = 0
        self.current_audio = None

    def initialize_networking(self):
        """Initialize network sockets"""
        # Create UDP sockets
        self.eye_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.mouth_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Button command queue
        self.button_command_queue = Queue()
        self.running = True
        self.button_command_thread = threading.Thread(
            target=self._process_button_commands, daemon=True
        )
        self.button_command_thread.start()

        # Send initial eye commands
        self.send_eye_command(CommandType.JOYSTICK_CONNECTED)
        time.sleep(0.1)
        self.send_eye_command(CommandType.AUTO_MOVEMENT_OFF)
        time.sleep(0.1)
        self.send_eye_command(CommandType.AUTO_BLINK_OFF)
        time.sleep(0.1)
        self.send_eye_command(CommandType.AUTO_PUPIL_OFF)
        time.sleep(0.1)

    def initialize_pygame(self):
        """Initialize pygame mixer only once"""
        if not pygame.mixer.get_init():
            try:
                pygame.mixer.init()
                print("Pygame mixer initialized successfully")
            except Exception as e:
                print(f"Error initializing pygame mixer: {e}")

    def reset(self):
        """Reset the player state for reuse"""
        # Stop any current playback
        if self.current_audio:
            pygame.mixer.music.stop()
            try:
                os.unlink(self.current_audio)
            except:
                pass
            self.current_audio = None

        # Reset state variables
        self.initialize_state()

        # Clear command queue
        while not self.button_command_queue.empty():
            try:
                self.button_command_queue.get_nowait()
            except Empty:
                break

    def _process_button_commands(self):
        """Process button commands with retries"""
        while self.running:
            try:
                command = self.button_command_queue.get(timeout=0.1)  # 100ms timeout
                if command is None:  # Sentinel value for shutdown
                    break
                # Send command multiple times to ensure delivery
                for _ in range(2):
                    if isinstance(command, tuple):
                        self.send_eye_command(*command)
                    else:
                        self.send_eye_command(command)
                    time.sleep(0.01)  # 10ms between sends
                time.sleep(0.04)  # 40ms before next command
                self.button_command_queue.task_done()
            except Empty:  # Fixed exception
                continue  # Keep running if queue is empty
            except Exception as e:
                print(f"Error processing button command: {e}")
                if not self.running:
                    break

    def send_eye_command(self, command_type: CommandType, *args):
        try:
            if not self.eye_socket:
                return

            if command_type == CommandType.EYE_POSITION:
                message = b"\x20" + struct.pack("BB", *args)
            elif command_type == CommandType.BLINK_LEFT_START:
                message = b"\x40"
            elif command_type == CommandType.BLINK_LEFT_END:
                message = b"\x41"
            elif command_type == CommandType.BLINK_RIGHT_START:
                message = b"\x42"
            elif command_type == CommandType.BLINK_RIGHT_END:
                message = b"\x43"
            elif command_type == CommandType.BLINK_BOTH_START:
                message = b"\x44"
            elif command_type == CommandType.BLINK_BOTH_END:
                message = b"\x45"
            elif command_type == CommandType.AUTO_MOVEMENT_OFF:
                message = b"\x10"
            elif command_type == CommandType.AUTO_MOVEMENT_ON:
                message = b"\x11"
            elif command_type == CommandType.AUTO_BLINK_OFF:
                message = b"\x12"
            elif command_type == CommandType.AUTO_BLINK_ON:
                message = b"\x13"
            elif command_type == CommandType.AUTO_PUPIL_OFF:
                message = b"\x14"
            elif command_type == CommandType.AUTO_PUPIL_ON:
                message = b"\x15"
            elif command_type == CommandType.JOYSTICK_CONNECTED:
                message = b"\x01"
            else:
                message = command_type.code

            self.eye_socket.sendto(message, (self.host, self.eye_port))
        except Exception as e:
            if self.running:  # Only print errors if we're still supposed to be running
                print(f"Error sending eye command: {e}", file=sys.stderr)

    def send_mouth_position(self, position: int):
        try:
            if not self.mouth_socket:
                return
            message = b"\x50" + struct.pack("B", position)
            self.mouth_socket.sendto(message, (self.host, self.mouth_port))
        except Exception as e:
            if self.running:
                print(f"Error sending mouth command: {e}", file=sys.stderr)

    def prepare_bundle(self, filename: str) -> bool:
        """Prepare a new animation bundle for playback"""
        try:
            # Stop any current audio playback but keep mixer alive
            if self.current_audio:
                pygame.mixer.music.stop()

            # Clean up previous temp file if it exists
            if self.current_audio and os.path.exists(self.current_audio):
                try:
                    os.unlink(self.current_audio)
                except:
                    pass

            bundle = FileFormat.load_bundle(filename)
            if not bundle:
                return False

            # Convert eye frames
            self.eye_data = [
                (
                    frame.time_ms,
                    frame.x,
                    frame.y,
                    frame.left_closed,
                    frame.right_closed,
                    frame.both_closed,
                )
                for frame in bundle.eye_frames
            ]

            # Convert mouth frames
            self.mouth_data = [
                (frame.time_ms, frame.position) for frame in bundle.mouth_frames
            ]

            # Reset playback state
            self.current_time = 0
            self.is_playing = False
            self.current_audio = None

            # Handle audio if present
            if bundle.audio_data:
                audio_ext = bundle.metadata.get("audio_format", "wav")
                temp_file = tempfile.NamedTemporaryFile(
                    delete=False, suffix=f".{audio_ext}"
                )
                temp_file.write(bundle.audio_data)
                temp_file.close()

                try:
                    pygame.mixer.music.load(temp_file.name)
                    self.current_audio = temp_file.name
                    print(f"Successfully loaded audio: {temp_file.name}")
                except Exception as e:
                    print(f"Warning: Could not load audio: {e}")
                    os.unlink(temp_file.name)
                    self.current_audio = None

            return True

        except Exception as e:
            print(f"Error preparing bundle: {e}")
            return False

    def apply_eye_movement(self, current_time):
        """Using EyeController's command queue for eye movements"""
        frame_to_play = None
        for frame in self.eye_data:
            if frame[0] <= current_time:
                frame_to_play = frame
            else:
                break

        if frame_to_play:
            time_ms, x, y, left_blink, right_blink, both_eyes = frame_to_play

            # Queue eye position command
            if (x != self.current_eye_x) or (y != self.current_eye_y):
                self.current_eye_x = x
                self.current_eye_y = y
                self.button_command_queue.put(
                    (CommandType.EYE_POSITION, int(x * 255), int(y * 255))
                )

            # Queue blink commands
            if both_eyes:
                if not (self.left_eye_closed and self.right_eye_closed):
                    self.button_command_queue.put(CommandType.BLINK_BOTH_START)
                    self.left_eye_closed = self.right_eye_closed = True
            else:
                if left_blink != self.left_eye_closed:
                    self.button_command_queue.put(
                        CommandType.BLINK_LEFT_START
                        if left_blink
                        else CommandType.BLINK_LEFT_END
                    )
                    self.left_eye_closed = left_blink
                if right_blink != self.right_eye_closed:
                    self.button_command_queue.put(
                        CommandType.BLINK_RIGHT_START
                        if right_blink
                        else CommandType.BLINK_RIGHT_END
                    )
                    self.right_eye_closed = right_blink

    def apply_mouth_movement(self, current_time):
        frame_to_play = None
        for frame in self.mouth_data:
            if frame[0] <= current_time:
                frame_to_play = frame
            else:
                break

        if frame_to_play:
            time_ms, position = frame_to_play
            if position != self.current_mouth_position:
                self.current_mouth_position = position
                self.send_mouth_position(position)

    def playback_movements(self):
        if len(self.eye_data) > 0:
            self.apply_eye_movement(self.current_time)
        if len(self.mouth_data) > 0:
            self.apply_mouth_movement(self.current_time)

    def update(self):
        if self.is_playing:
            if self.current_audio:
                self.current_time = pygame.mixer.music.get_pos()
                if not pygame.mixer.music.get_busy():
                    return False
            else:
                current_time_ms = (time.time() - self.recording_start_time) * 1000
                self.current_time = int(current_time_ms)

                max_time = 0
                if self.eye_data:
                    max_time = max(max_time, self.eye_data[-1][0])
                if self.mouth_data:
                    max_time = max(max_time, self.mouth_data[-1][0])

                if max_time > 0 and self.current_time >= (max_time + 100):
                    return False

            self.playback_movements()
            return True

        return False

    def play_bundle(self, loop: bool = False):
        try:
            while True:
                print("\nStarting playback...")
                self.is_playing = True
                self.recording_start_time = time.time()

                if self.current_audio:
                    print("Starting audio playback")
                    pygame.mixer.music.play()

                while self.is_playing:
                    if not self.update():
                        break
                    time.sleep(1 / 60)

                if not loop:
                    break

                if self.current_audio:
                    pygame.mixer.music.stop()
                time.sleep(0.5)

        except KeyboardInterrupt:
            print("\nPlayback interrupted by user")
        except Exception as e:
            print(f"Error during playback: {e}")
        finally:
            self.is_playing = False

    def cleanup(self):
        """Final cleanup when shutting down"""
        print("\nFinal cleanup...")

        self.running = False
        if (
            hasattr(self, "button_command_thread")
            and self.button_command_thread.is_alive()
        ):
            self.button_command_queue.put(None)
            self.button_command_thread.join(timeout=1.0)

        if hasattr(self, "eye_socket") and self.eye_socket:
            try:
                if self.left_eye_closed:
                    self.send_eye_command(CommandType.BLINK_LEFT_END)
                if self.right_eye_closed:
                    self.send_eye_command(CommandType.BLINK_RIGHT_END)

                self.send_eye_command(CommandType.AUTO_MOVEMENT_ON)
                time.sleep(0.1)
                self.send_eye_command(CommandType.AUTO_BLINK_ON)
                time.sleep(0.1)
                self.send_eye_command(CommandType.AUTO_PUPIL_ON)

                self.eye_socket.close()
            except:
                pass

        if hasattr(self, "mouth_socket") and self.mouth_socket:
            try:
                self.mouth_socket.close()
            except:
                pass

        # Clean up final audio file
        if self.current_audio and os.path.exists(self.current_audio):
            try:
                pygame.mixer.music.stop()
                os.unlink(self.current_audio)
            except:
                pass

        # Only quit pygame when totally shutting down
        if pygame.mixer.get_init():
            pygame.mixer.quit()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Animation Bundle Player")
    parser.add_argument("filename", help="Animation bundle file to play")
    parser.add_argument("--host", default="127.0.0.1", help="Target host IP")
    parser.add_argument(
        "--eye-port", type=int, default=5005, help="UDP port for eye control"
    )
    parser.add_argument(
        "--mouth-port", type=int, default=5006, help="UDP port for mouth control"
    )
    parser.add_argument("--loop", action="store_true", help="Loop the animation")
    parser.add_argument(
        "--start-delay",
        type=int,
        default=0,
        help="Delay in milliseconds before starting playback",
    )

    args = parser.parse_args()

    print(f"Animation Bundle Player")
    print(f"Host: {args.host}")
    print(f"Eye Port: {args.eye_port}")
    print(f"Mouth Port: {args.mouth_port}")
    print(f"File: {args.filename}")
    print(f"Loop: {'Yes' if args.loop else 'No'}")
    print(f"Start Delay: {args.start_delay}ms")

    player = BundlePlayer(args.host, args.eye_port, args.mouth_port, args.start_delay)

    if player.prepare_bundle(args.filename):
        try:
            player.play_bundle(args.loop)
        except KeyboardInterrupt:
            print("\nPlayback interrupted by user")
        finally:
            player.cleanup()
    else:
        print("Failed to prepare bundle for playback")
        player.cleanup()


if __name__ == "__main__":
    main()
