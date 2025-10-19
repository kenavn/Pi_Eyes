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
parser.add_argument("--idle", type=int, default=128,
                    help="Idle position to return to (0-255, default: 128)")
parser.add_argument("--idle-timeout", type=float, default=2.0,
                    help="Seconds of inactivity before returning to idle (default: 2.0)")
parser.add_argument("--idle-ease-duration", type=float, default=0.5,
                    help="Duration in seconds for easing to idle position (default: 0.5)")
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


def ease_in_out(t):
    """Ease-in-out interpolation function (smooth acceleration and deceleration)"""
    if t < 0.5:
        return 2 * t * t
    else:
        return -1 + (4 - 2 * t) * t


def update_easing():
    """Update easing animation if active. Returns True if easing is complete."""
    global is_easing, current_position

    if not is_easing:
        return False

    # Calculate progress (0.0 to 1.0)
    elapsed = time.time() - ease_start_time
    progress = min(elapsed / args.idle_ease_duration, 1.0)

    # Apply easing function
    eased_progress = ease_in_out(progress)

    # Interpolate position
    position_delta = args.idle - ease_start_position
    new_position = int(ease_start_position + (position_delta * eased_progress))

    # Only update if position changed
    if new_position != current_position:
        current_position = new_position
        set_servo_position(current_position)

    # Check if easing is complete
    if progress >= 1.0:
        is_easing = False
        return True

    return False


def start_easing_to_idle():
    """Start easing to idle position"""
    global is_easing, ease_start_time, ease_start_position

    # Don't start easing if already at idle position
    if current_position == args.idle:
        return

    is_easing = True
    ease_start_time = time.time()
    ease_start_position = current_position
    print(f"Starting ease from {ease_start_position} to {args.idle}")


def cancel_easing():
    """Cancel any active easing"""
    global is_easing
    if is_easing:
        is_easing = False
        print("Easing cancelled")


def decode_message(data):
    """Decode incoming UDP message"""
    command_type = data[0]
    if command_type == 0x50:
        position, = struct.unpack('B', data[1:2])
        return f"set_position,{position}"
    else:
        raise ValueError(f"Unknown command type: {command_type}")


# Idle position tracking
last_activity_time = time.time()
current_position = args.idle  # Start at idle position
is_easing = False
ease_start_time = 0
ease_start_position = 0

print(f"Starting servo control with following settings:")
print(f"PWM range: {args.min} to {args.max}")
print(f"GPIO pin: {args.pin}")
print(f"UDP port: {args.port}")
print(f"Idle position: {args.idle}/255")
print(f"Idle timeout: {args.idle_timeout}s")
print(f"Idle ease duration: {args.idle_ease_duration}s")

try:
    while True:
        try:
            # Non-blocking socket receive
            sock.settimeout(0.01)  # Shorter timeout for responsive easing
            data, addr = sock.recvfrom(1024)
            message = decode_message(data)

            if message.startswith("set_position"):
                _, position = message.split(',')
                position = int(position)

                # Cancel any active easing
                cancel_easing()

                # Update position and servo
                current_position = position
                set_servo_position(position)

                # Reset activity timer
                last_activity_time = time.time()

        except socket.timeout:
            # Check if we should start easing to idle
            time_since_activity = time.time() - last_activity_time

            if not is_easing and time_since_activity >= args.idle_timeout:
                start_easing_to_idle()

            # Update easing animation if active
            if is_easing:
                update_easing()

            # Small delay to prevent busy-waiting
            time.sleep(0.01)

        except socket.error:
            time.sleep(0.01)
        except ValueError as e:
            print(f"Error: {e}")

except KeyboardInterrupt:
    print("\nShutting down gracefully...")
    pi.set_servo_pulsewidth(args.pin, 0)  # Disable servo
    pi.stop()
    sock.close()
