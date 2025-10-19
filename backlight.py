#!/usr/bin/python3

import socket
import struct
import time
import argparse
import pigpio

# Parse command-line arguments
parser = argparse.ArgumentParser(
    description="Backlight Control for Snake Eyes Bonnet LED Panels")
parser.add_argument("--pin", type=int, default=18,
                    help="GPIO pin for backlight (default: 18)")
parser.add_argument("--brightness", type=int, default=255,
                    help="Initial brightness 0-255 (default: 255)")
parser.add_argument("--port", type=int, default=5007,
                    help="UDP port to listen on (default: 5007)")
parser.add_argument("--freq", type=int, default=1000,
                    help="PWM frequency in Hz (default: 1000)")
args = parser.parse_args()

# Initialize pigpio
pi = pigpio.pi()
if not pi.connected:
    print("Error: Could not connect to pigpio daemon. Is it running?")
    print("Try: sudo pigpiod")
    exit(1)

# Set up PWM for backlight control
pi.set_PWM_frequency(args.pin, args.freq)
pi.set_PWM_range(args.pin, 255)  # 0-255 range for brightness

# UDP settings
UDP_IP = "0.0.0.0"
UDP_PORT = args.port
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))


def set_brightness(brightness):
    """Set backlight brightness (0-255)"""
    brightness = max(0, min(255, brightness))  # Clamp to 0-255
    print(f"Setting brightness: {brightness}/255 ({int(brightness/255*100)}%)")
    pi.set_PWM_dutycycle(args.pin, brightness)


def decode_message(data):
    """Decode incoming UDP message"""
    command_type = data[0]
    if command_type == 0x60:  # Brightness command
        brightness, = struct.unpack('B', data[1:2])
        return f"set_brightness,{brightness}"
    else:
        raise ValueError(f"Unknown command type: {command_type}")


print(f"Starting backlight control with following settings:")
print(f"GPIO pin: {args.pin}")
print(f"PWM frequency: {args.freq} Hz")
print(f"Initial brightness: {args.brightness}/255 ({int(args.brightness/255*100)}%)")
print(f"UDP port: {args.port}")

# Set initial brightness
set_brightness(args.brightness)

try:
    while True:
        try:
            # Non-blocking socket receive
            sock.settimeout(0.1)
            data, addr = sock.recvfrom(1024)
            message = decode_message(data)

            if message.startswith("set_brightness"):
                _, brightness = message.split(',')
                brightness = int(brightness)
                set_brightness(brightness)

        except socket.timeout:
            continue
        except socket.error:
            time.sleep(0.01)
        except ValueError as e:
            print(f"Error: {e}")

except KeyboardInterrupt:
    print("\nShutting down gracefully...")
    pi.set_PWM_dutycycle(args.pin, 255)  # Set to full brightness on exit
    pi.stop()
    sock.close()
