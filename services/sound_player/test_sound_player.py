#!/usr/bin/env python3
"""
Test utility for the Sound Player service.
Sends UDP commands to trigger sound playback.
"""
import socket
import struct
import argparse
import time


class SoundPlayerClient:
    """Client for sending commands to the Sound Player service"""

    def __init__(self, host: str = "127.0.0.1", port: int = 5008):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def play_specific(self, filename: str):
        """Play a specific sound file"""
        # Command: 0x60 + null-terminated filename
        message = b'\x60' + filename.encode('utf-8') + b'\x00'
        self.sock.sendto(message, (self.host, self.port))
        print(f"Sent command: Play specific file '{filename}'")

    def play_random(self):
        """Play a random sound"""
        # Command: 0x61
        message = b'\x61'
        self.sock.sendto(message, (self.host, self.port))
        print("Sent command: Play random sound")

    def stop(self):
        """Stop playback"""
        # Command: 0x62
        message = b'\x62'
        self.sock.sendto(message, (self.host, self.port))
        print("Sent command: Stop playback")

    def set_volume(self, volume: int):
        """Set volume (0-100)"""
        # Command: 0x63 + volume byte
        volume = max(0, min(100, volume))  # Clamp to 0-100
        message = struct.pack('BB', 0x63, volume)
        self.sock.sendto(message, (self.host, self.port))
        print(f"Sent command: Set volume to {volume}%")

    def close(self):
        """Close the socket"""
        self.sock.close()


def interactive_mode(client: SoundPlayerClient):
    """Interactive command-line interface"""
    print("\n=== Sound Player Test Client ===")
    print("Commands:")
    print("  play <filename>  - Play specific sound file")
    print("  random           - Play random sound")
    print("  stop             - Stop playback")
    print("  volume <0-100>   - Set volume")
    print("  quit             - Exit")
    print()

    try:
        while True:
            try:
                command = input("> ").strip().lower()

                if not command:
                    continue

                parts = command.split(maxsplit=1)
                cmd = parts[0]

                if cmd == 'quit' or cmd == 'exit' or cmd == 'q':
                    break

                elif cmd == 'play' or cmd == 'p':
                    if len(parts) < 2:
                        print("Error: Please specify a filename")
                        continue
                    filename = parts[1]
                    client.play_specific(filename)

                elif cmd == 'random' or cmd == 'r':
                    client.play_random()

                elif cmd == 'stop' or cmd == 's':
                    client.stop()

                elif cmd == 'volume' or cmd == 'v':
                    if len(parts) < 2:
                        print("Error: Please specify volume (0-100)")
                        continue
                    try:
                        volume = int(parts[1])
                        client.set_volume(volume)
                    except ValueError:
                        print("Error: Volume must be a number between 0 and 100")

                elif cmd == 'help' or cmd == 'h':
                    print("Commands:")
                    print("  play <filename>  - Play specific sound file")
                    print("  random           - Play random sound")
                    print("  stop             - Stop playback")
                    print("  volume <0-100>   - Set volume")
                    print("  quit             - Exit")

                else:
                    print(f"Unknown command: {cmd}")
                    print("Type 'help' for available commands")

            except KeyboardInterrupt:
                print()
                break
            except Exception as e:
                print(f"Error: {e}")

    finally:
        print("\nExiting...")


def main():
    parser = argparse.ArgumentParser(
        description="Test client for Sound Player service"
    )
    parser.add_argument(
        "-i", "--host",
        default="127.0.0.1",
        help="Host IP address (default: 127.0.0.1)"
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=5008,
        help="UDP port (default: 5008)"
    )

    # Command modes
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--play",
        metavar="FILENAME",
        help="Play specific sound file and exit"
    )
    group.add_argument(
        "--random",
        action="store_true",
        help="Play random sound and exit"
    )
    group.add_argument(
        "--stop",
        action="store_true",
        help="Stop playback and exit"
    )
    group.add_argument(
        "--volume",
        type=int,
        metavar="0-100",
        help="Set volume and exit"
    )

    args = parser.parse_args()

    # Create client
    client = SoundPlayerClient(args.host, args.port)

    try:
        # Single command mode
        if args.play:
            client.play_specific(args.play)
        elif args.random:
            client.play_random()
        elif args.stop:
            client.stop()
        elif args.volume is not None:
            client.set_volume(args.volume)
        else:
            # Interactive mode
            interactive_mode(client)

    finally:
        client.close()


if __name__ == "__main__":
    main()
