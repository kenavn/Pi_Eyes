#!/usr/bin/env python3
import argparse
import socket
import time
from typing import Optional, List, Tuple
from dataclasses import dataclass
from animation_protocol import FileFormat, UDPProtocol, CommandType, AnimationBundle
from audio_player import AudioPlayer


@dataclass
class Frame:
    """Unified frame class for sorting once during loading"""

    time_ms: int
    frame_type: str  # 'eye' or 'mouth'
    data: any  # Original frame data


class BundlePlayer:
    def __init__(
        self, host: str, eye_port: int, mouth_port: int, start_delay_ms: int = 0
    ):
        """Initialize the bundle player"""
        self.host = host
        self.eye_port = eye_port
        self.mouth_port = mouth_port
        self.start_delay_ms = start_delay_ms

        # Create UDP sockets
        self.eye_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.mouth_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Initialize audio player
        self.audio_player = AudioPlayer()

        # Playback state
        self.is_playing = False
        self.sorted_frames = []

    def prepare_bundle(self, filename: str) -> bool:
        """Load and prepare the bundle for playback"""
        try:
            # Load the bundle
            load_start = time.time()
            bundle = FileFormat.load_bundle(filename)
            if not bundle:
                print("Error: Could not load animation bundle")
                return False
            print(f"Loading bundle file took: {(time.time() - load_start)*1000:.1f}ms")

            # Store frames directly - they're already sorted in the CSV
            frame_start = time.time()
            self.sorted_frames = []
            for frame in bundle.eye_frames:
                self.sorted_frames.append(Frame(frame.time_ms, "eye", frame))
            for frame in bundle.mouth_frames:
                self.sorted_frames.append(Frame(frame.time_ms, "mouth", frame))
            print(f"Frame processing took: {(time.time() - frame_start)*1000:.1f}ms")

            # If there's audio, prepare it
            if bundle.audio_data:
                audio_start = time.time()
                import tempfile

                audio_ext = bundle.metadata.get("audio_format", "wav")
                with tempfile.NamedTemporaryFile(
                    suffix=f".{audio_ext}", delete=False
                ) as temp_file:
                    temp_file.write(bundle.audio_data)
                    if not self.audio_player.load_file(temp_file.name):
                        print("Warning: Could not load audio file")
                        return False
                print(
                    f"Audio preparation took: {(time.time() - audio_start)*1000:.1f}ms"
                )

            return True

        except Exception as e:
            print(f"Error preparing bundle: {e}")
            return False

    def play_bundle(self, loop: bool = False):
        """Play the prepared animation bundle"""
        if not self.sorted_frames:
            print("Error: No bundle prepared for playback")
            return

        try:
            while True:
                self.is_playing = True
                self.disable_autonomous_mode()  # No sleep needed

                # Start audio and begin playback immediately
                if self.audio_player.is_loaded():
                    self.audio_player.play()

                playback_start = time.time() * 1000 + self.start_delay_ms

                for frame in self.sorted_frames:
                    if not self.is_playing:
                        break

                    current_time = time.time() * 1000
                    wait_time = (playback_start + frame.time_ms - current_time) / 1000

                    if wait_time > 0:
                        time.sleep(wait_time)

                    if frame.frame_type == "mouth":
                        self.send_mouth_frame(frame.data)
                    else:
                        self.send_eye_frame(frame.data)

                if not loop:
                    break

                self.audio_player.stop()
                time.sleep(0.1)  # Minimal delay between loops

        except KeyboardInterrupt:
            print("\nPlayback interrupted by user")
        finally:
            self.is_playing = False
            self.audio_player.stop()
            self.enable_autonomous_mode()

    def cleanup(self):
        """Clean up resources"""
        self.audio_player.unload()
        self.eye_socket.close()
        self.mouth_socket.close()

    def disable_autonomous_mode(self):
        """Disable autonomous eye movements and blinking"""
        try:
            self.eye_socket.sendto(
                UDPProtocol.encode_eye_message(CommandType.AUTO_MOVEMENT_OFF),
                (self.host, self.eye_port),
            )
            self.eye_socket.sendto(
                UDPProtocol.encode_eye_message(CommandType.AUTO_BLINK_OFF),
                (self.host, self.eye_port),
            )
        except Exception as e:
            print(f"Error disabling autonomous mode: {e}")

    def enable_autonomous_mode(self):
        """Re-enable autonomous eye movements and blinking"""
        try:
            self.eye_socket.sendto(
                UDPProtocol.encode_eye_message(CommandType.AUTO_MOVEMENT_ON),
                (self.host, self.eye_port),
            )
            self.eye_socket.sendto(
                UDPProtocol.encode_eye_message(CommandType.AUTO_BLINK_ON),
                (self.host, self.eye_port),
            )
        except Exception as e:
            print(f"Error enabling autonomous mode: {e}")

    def send_mouth_frame(self, frame):
        """Send mouth frame via UDP"""
        try:
            encoded = UDPProtocol.encode_mouth_position(frame.position)
            self.mouth_socket.sendto(encoded, (self.host, self.mouth_port))
        except Exception as e:
            print(f"Error sending mouth frame: {e}")

    def send_eye_frame(self, frame):
        """Send eye frame via UDP"""
        try:
            encoded = UDPProtocol.encode_eye_position(frame.x, frame.y)
            self.eye_socket.sendto(encoded, (self.host, self.eye_port))

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
    print("\nPress Ctrl+C to stop playback")

    start_time = time.time()
    player = BundlePlayer(args.host, args.eye_port, args.mouth_port, args.start_delay)
    print(f"Player initialization took: {(time.time() - start_time)*1000:.1f}ms")

    load_start = time.time()
    if player.prepare_bundle(args.filename):
        print(f"Bundle loading took: {(time.time() - load_start)*1000:.1f}ms")
        play_start = time.time()
        player.play_bundle(args.loop)
        print(f"Playback took: {(time.time() - play_start)*1000:.1f}ms")
    player.cleanup()


if __name__ == "__main__":
    main()
