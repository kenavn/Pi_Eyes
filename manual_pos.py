import socket
import sys
import time


def send_udp_message(sock, message):
    sock.sendto(message.encode(), ('10.0.1.151', 5005))
    time.sleep(0.1)  # Small delay to ensure messages are processed in order


def main():
    if len(sys.argv) != 3:
        print("Usage: python script_name.py <x_position> <y_position>")
        print("x_position and y_position should be float values between -1 and 1")
        sys.exit(1)

    try:
        x_pos = float(sys.argv[1])
        y_pos = float(sys.argv[2])
    except ValueError:
        print("Error: x_position and y_position must be numeric values")
        sys.exit(1)

    if not (-1 <= x_pos <= 1) or not (-1 <= y_pos <= 1):
        print("Error: x_position and y_position must be between -1 and 1")
        sys.exit(1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Turn off automatic functions
    send_udp_message(sock, "auto_movement_off")
    send_udp_message(sock, "auto_blink_off")
    send_udp_message(sock, "auto_pupil_off")

    # Enable joystick control
    send_udp_message(sock, "joystick_connected")

    # Set eye position
    send_udp_message(sock, f"joystick,{x_pos},{y_pos}")

    print(f"Eye position set to x:{x_pos}, y:{y_pos}")

    sock.close()


if __name__ == "__main__":
    main()
