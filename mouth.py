import socket
import struct
import time
import argparse
import pigpio

# Parse command-line arguments
parser = argparse.ArgumentParser(
    description="Servo Control for Skeleton Mouth")
parser.add_argument("--min", type=int, default=102,
                    help="Minimum PWM value (default: 84)")
parser.add_argument("--max", type=int, default=180,
                    help="Maximum PWM value (default: 150)")
parser.add_argument("--pin", type=int, default=22,
                    help="GPIO pin for servo (default: 22)")
parser.add_argument("--port", type=int, default=5006,
                    help="UDP port to listen on (default: 5006)")
args = parser.parse_args()

# Initialize pigpio
pi = pigpio.pi()
if not pi.connected:
    print("Error: Could not connect to pigpio daemon. Is it running?")
    print("Try: sudo pigpiod")
    exit(1)

# Set up PWM frequency
pi.set_PWM_frequency(args.pin, 50)  # 50Hz for standard servos

# UDP settings
UDP_IP = "0.0.0.0"
UDP_PORT = args.port
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))


def map_value(value, in_min, in_max, out_min, out_max):
    """Map a value from one range to another"""
    return int((value - in_min) * (out_max - out_min) / (in_max - in_min) + out_min)


def set_servo_position(position):
    """Set servo position directly"""
    # Map input position (0-255) to PWM range
    pwm = map_value(position, 0, 255, args.min, args.max)

    # Convert to microseconds
    pulsewidth = pwm * 10

    print(f"Received position: {position}/255 -> PWM: {pwm} -> Pulsewidth: {pulsewidth}µs")

    # Set the servo position
    pi.set_servo_pulsewidth(args.pin, pulsewidth)


def decode_message(data):
    """Decode incoming UDP message"""
    command_type = data[0]
    if command_type == 0x50:
        position, = struct.unpack('B', data[1:2])
        return f"set_position,{position}"
    else:
        raise ValueError(f"Unknown command type: {command_type}")


print(f"Starting servo control with following settings:")
print(f"PWM range: {args.min} to {args.max}")
print(f"GPIO pin: {args.pin}")
print(f"UDP port: {args.port}")

try:
    while True:
        try:
            # Non-blocking socket receive
            sock.settimeout(0.1)
            data, addr = sock.recvfrom(1024)
            message = decode_message(data)

            if message.startswith("set_position"):
                _, position = message.split(',')
                position = int(position)
                set_servo_position(position)

        except socket.timeout:
            continue
        except socket.error:
            time.sleep(0.01)
        except ValueError as e:
            print(f"Error: {e}")

except KeyboardInterrupt:
    print("\nShutting down gracefully...")
    pi.set_servo_pulsewidth(args.pin, 0)  # Disable servo
    pi.stop()
    sock.close()
