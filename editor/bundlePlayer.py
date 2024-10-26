#!/usr/bin/env python3
import argparse
import socket
import time
import tempfile
import os
from animation_protocol import FileFormat, UDPProtocol, CommandType
import pygame
from typing import Optional


class BundlePlayer:
    def __init__(self, host: str, eye_port: int, mouth_port: int):
        """Initialize the bundle player"""
        self.host = host
        self.eye_port = eye_port
        self.mouth_port = mouth_port

        # Create UDP sockets
        self.eye_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.mouth_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Initialize pygame for audio
        pygame.init()
        pygame.mixer.init()

        # Playback state
        self.is_playing = False
        self.start_time = 0
        self.temp_audio_file: Optional[str] = None

    def cleanup(self):
        """Clean up resources"""
        pygame.mixer.quit()
        pygame.quit()
        self.eye_socket.close()
        self.mouth_socket.close()

        # Remove temporary audio file if it exists
        if self.temp_audio_file and os.path.exists(self.temp_audio_file):
            try:
                os.remove(self.temp_audio_file)
            except Exception as e:
                print(f"Warning: Could not remove temporary audio file: {e}")

    def play_bundle(self, filename: str, loop: bool = False):
        """Play an animation bundle file"""
        try:
            # Load the bundle
            bundle = FileFormat.load_bundle(filename)
            if not bundle:
                print("Error: Could not load animation bundle")
                return

            print(
                f"Loaded bundle: {len(bundle.eye_frames)} eye frames, {len(bundle.mouth_frames)} mouth frames"
            )
            print(f"Bundle metadata: {bundle.metadata}")

            # If there's audio, save it to a temporary file and load it with pygame
            if bundle.audio_data:
                # Create temporary file with correct extension
                audio_ext = bundle.metadata.get("audio_format", "wav")
                with tempfile.NamedTemporaryFile(
                    suffix=f".{audio_ext}", delete=False
                ) as temp_file:
                    temp_file.write(bundle.audio_data)
                    self.temp_audio_file = temp_file.name

                # Load audio
                pygame.mixer.music.load(self.temp_audio_file)

            while True:
                try:
                    # Start playback
                    self.is_playing = True
                    self.start_time = time.time()

                    if bundle.audio_data:
                        pygame.mixer.music.play()

                    # Combine and sort all frames by timestamp
                    all_frames = []
                    all_frames.extend(
                        (frame.time_ms, "eye", frame) for frame in bundle.eye_frames
                    )
                    all_frames.extend(
                        (frame.time_ms, "mouth", frame) for frame in bundle.mouth_frames
                    )
                    all_frames.sort(key=lambda x: x[0])

                    last_time = 0
                    for time_ms, frame_type, frame in all_frames:
                        if not self.is_playing:
                            break

                        # Handle timing
                        time_diff = (time_ms - last_time) / 1000
                        if time_diff > 0:
                            time.sleep(time_diff)

                        # Send appropriate UDP commands
                        if frame_type == "eye":
                            self.send_eye_frame(frame)
                        else:
                            self.send_mouth_frame(frame)

                        last_time = time_ms

                    if not loop:
                        break

                    print("Looping playback...")
                    time.sleep(0.5)

                except KeyboardInterrupt:
                    print("\nPlayback interrupted by user")
                    break

        except Exception as e:
            print(f"Error during playback: {e}")
        finally:
            self.is_playing = False
            if bundle.audio_data:
                pygame.mixer.music.stop()
            self.cleanup()

    def send_eye_frame(self, frame):
        """Send eye frame via UDP"""
        try:
            # Send eye position
            encoded = UDPProtocol.encode_eye_position(frame.x, frame.y)
            self.eye_socket.sendto(encoded, (self.host, self.eye_port))

            # Handle blinks
            if frame.both_closed:
                self.eye_socket.sendto(
                    UDPProtocol.encode_eye_message(CommandType.BLINK_BOTH_START),
                    (self.host, self.eye_port),
                )
            else:
                if frame.left_closed:
                    self.eye_socket.sendto(
                        UDPProtocol.encode_eye_message(CommandType.BLINK_LEFT_START),
                        (self.host, self.eye_port),
                    )
                if frame.right_closed:
                    self.eye_socket.sendto(
                        UDPProtocol.encode_eye_message(CommandType.BLINK_RIGHT_START),
                        (self.host, self.eye_port),
                    )

        except Exception as e:
            print(f"Error sending eye frame: {e}")

    def send_mouth_frame(self, frame):
        """Send mouth frame via UDP"""
        try:
            encoded = UDPProtocol.encode_mouth_position(frame.position)
            self.mouth_socket.sendto(encoded, (self.host, self.mouth_port))
        except Exception as e:
            print(f"Error sending mouth frame: {e}")


def main():
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

    args = parser.parse_args()

    print(f"Animation Bundle Player")
    print(f"Host: {args.host}")
    print(f"Eye Port: {args.eye_port}")
    print(f"Mouth Port: {args.mouth_port}")
    print(f"File: {args.filename}")
    print(f"Loop: {'Yes' if args.loop else 'No'}")
    print("\nPress Ctrl+C to stop playback")

    player = BundlePlayer(args.host, args.eye_port, args.mouth_port)
    player.play_bundle(args.filename, args.loop)


if __name__ == "__main__":
    main()
