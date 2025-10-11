#!/usr/bin/env python3
import socket
import struct
import time
import argparse
import os
import random
import threading
from pathlib import Path
from typing import Optional

try:
    import pygame
    pygame.mixer.init()
except ImportError:
    print("Error: pygame not installed. Install with: pip3 install pygame")
    exit(1)


class SoundPlayer:
    """
    UDP-based sound player service for Pi_Eyes.
    Supports playing specific MP3 files and random selection from a directory.
    """
    VERSION = "1.0.0"

    def __init__(
        self,
        sounds_dir: str,
        random_dir: str,
        port: int = 5008,
        volume: int = 100
    ):
        self.sounds_dir = Path(sounds_dir).resolve()
        self.random_dir = Path(random_dir).resolve()
        self.port = port
        self.volume = max(0.0, min(1.0, volume / 100.0))  # Convert percentage to 0.0-1.0

        # Verify directories exist
        if not self.sounds_dir.exists():
            print(f"Warning: Sounds directory does not exist: {self.sounds_dir}")
            print(f"Creating directory: {self.sounds_dir}")
            self.sounds_dir.mkdir(parents=True, exist_ok=True)

        if not self.random_dir.exists():
            print(f"Warning: Random sounds directory does not exist: {self.random_dir}")
            print(f"Creating directory: {self.random_dir}")
            self.random_dir.mkdir(parents=True, exist_ok=True)

        # Initialize pygame mixer
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.set_volume(self.volume)

        # Playback state
        self.is_playing = False
        self.current_file = None
        self.playback_thread = None
        self.stop_requested = False

        # UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", self.port))

        print(f"Sound Player v{self.VERSION}")
        print(f"Sounds directory: {self.sounds_dir}")
        print(f"Random sounds directory: {self.random_dir}")
        print(f"UDP port: {self.port}")
        print(f"Volume: {int(self.volume * 100)}%")

    def get_audio_files(self, directory: Path) -> list:
        """Get all audio files from a directory"""
        extensions = ['.mp3', '.wav', '.ogg', '.flac']
        audio_files = []

        if not directory.exists():
            return audio_files

        for ext in extensions:
            audio_files.extend(directory.glob(f"*{ext}"))

        return sorted(audio_files)

    def play_sound(self, filepath: Path):
        """Play a sound file in a separate thread"""
        if not filepath.exists():
            print(f"Error: Sound file not found: {filepath}")
            return

        # Stop any current playback
        self.stop_sound()

        def playback_worker():
            try:
                self.is_playing = True
                self.current_file = filepath
                self.stop_requested = False

                print(f"Playing: {filepath.name}")
                pygame.mixer.music.load(str(filepath))
                pygame.mixer.music.play()

                # Wait for playback to finish or stop to be requested
                while pygame.mixer.music.get_busy() and not self.stop_requested:
                    time.sleep(0.1)

                if self.stop_requested:
                    print(f"Stopped: {filepath.name}")
                else:
                    print(f"Finished: {filepath.name}")

            except Exception as e:
                print(f"Error playing sound: {e}")
            finally:
                self.is_playing = False
                self.current_file = None

        self.playback_thread = threading.Thread(target=playback_worker, daemon=True)
        self.playback_thread.start()

    def play_specific(self, filename: str):
        """Play a specific sound file from the sounds directory"""
        # Try exact filename first
        filepath = self.sounds_dir / filename

        # If not found, try adding common extensions
        if not filepath.exists():
            for ext in ['.mp3', '.wav', '.ogg', '.flac']:
                test_path = self.sounds_dir / f"{filename}{ext}"
                if test_path.exists():
                    filepath = test_path
                    break

        if filepath.exists():
            self.play_sound(filepath)
        else:
            print(f"Error: Sound file not found: {filename}")
            print(f"Searched in: {self.sounds_dir}")

    def play_random(self):
        """Play a random sound from the random directory"""
        audio_files = self.get_audio_files(self.random_dir)

        if not audio_files:
            print(f"Error: No audio files found in {self.random_dir}")
            return

        selected_file = random.choice(audio_files)
        print(f"Selected random file: {selected_file.name}")
        self.play_sound(selected_file)

    def stop_sound(self):
        """Stop current playback"""
        if self.is_playing:
            self.stop_requested = True
            pygame.mixer.music.stop()

            # Wait for playback thread to finish
            if self.playback_thread and self.playback_thread.is_alive():
                self.playback_thread.join(timeout=1.0)

    def set_volume(self, volume: int):
        """Set volume (0-100)"""
        self.volume = max(0.0, min(1.0, volume / 100.0))
        pygame.mixer.music.set_volume(self.volume)
        print(f"Volume set to: {int(self.volume * 100)}%")

    def decode_message(self, data: bytes) -> Optional[tuple]:
        """
        Decode incoming UDP message.

        Command types:
        - 0x60: Play specific file (followed by null-terminated filename string)
        - 0x61: Play random file from random directory
        - 0x62: Stop playback
        - 0x63: Set volume (followed by single byte 0-100)
        """
        if len(data) < 1:
            return None

        command_type = data[0]

        if command_type == 0x60:  # Play specific
            if len(data) < 2:
                return None
            # Extract null-terminated string
            try:
                filename = data[1:].split(b'\x00')[0].decode('utf-8')
                return ('play_specific', filename)
            except UnicodeDecodeError:
                print("Error: Invalid filename encoding")
                return None

        elif command_type == 0x61:  # Play random
            return ('play_random', None)

        elif command_type == 0x62:  # Stop
            return ('stop', None)

        elif command_type == 0x63:  # Set volume
            if len(data) < 2:
                return None
            volume = data[1]
            return ('set_volume', volume)

        else:
            print(f"Unknown command type: 0x{command_type:02x}")
            return None

    def run(self):
        """Main service loop"""
        print("Sound Player service started")
        print("Listening for commands...")

        try:
            while True:
                try:
                    # Non-blocking receive with timeout
                    self.sock.settimeout(0.1)
                    data, addr = self.sock.recvfrom(1024)

                    message = self.decode_message(data)
                    if not message:
                        continue

                    command, param = message

                    if command == 'play_specific':
                        self.play_specific(param)
                    elif command == 'play_random':
                        self.play_random()
                    elif command == 'stop':
                        self.stop_sound()
                    elif command == 'set_volume':
                        self.set_volume(param)

                except socket.timeout:
                    continue
                except socket.error as e:
                    print(f"Socket error: {e}")
                    time.sleep(0.01)
                except Exception as e:
                    print(f"Error: {e}")

        except KeyboardInterrupt:
            print("\nShutting down gracefully...")
        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up resources"""
        self.stop_sound()
        self.sock.close()
        pygame.mixer.quit()
        print("Sound Player stopped")


def main():
    parser = argparse.ArgumentParser(
        description="Sound Player Service for Pi_Eyes"
    )
    parser.add_argument(
        "--sounds-dir",
        default="/boot/Pi_Eyes/sounds",
        help="Directory containing sound files (default: /boot/Pi_Eyes/sounds)"
    )
    parser.add_argument(
        "--random-dir",
        default="/boot/Pi_Eyes/sounds/random",
        help="Directory for random sound selection (default: /boot/Pi_Eyes/sounds/random)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5008,
        help="UDP port to listen on (default: 5008)"
    )
    parser.add_argument(
        "--volume",
        type=int,
        default=100,
        help="Initial volume level 0-100 (default: 100)"
    )

    args = parser.parse_args()

    player = SoundPlayer(
        sounds_dir=args.sounds_dir,
        random_dir=args.random_dir,
        port=args.port,
        volume=args.volume
    )

    player.run()


if __name__ == "__main__":
    main()
