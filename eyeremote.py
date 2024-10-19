import socket
import time
import csv
import argparse
from itertools import cycle

# UDP settings
UDP_IP = "10.0.1.151"  # Replace with the IP of your eye device
UDP_PORT = 5005  # Make sure this matches the port in your eye script

# Create a UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def send_message(message):
    sock.sendto(message.encode(), (UDP_IP, UDP_PORT))
    print(f"Sent: {message}")


def toggle_auto_movement(enable):
    send_message("auto_movement_on" if enable else "auto_movement_off")


def toggle_auto_blink(enable):
    send_message("auto_blink_on" if enable else "auto_blink_off")


def set_joystick(x, y):
    send_message(f"joystick,{x},{y}")


def trigger_blink(eye):
    if eye.lower() == "left":
        send_message("blink_left")
    elif eye.lower() == "right":
        send_message("blink_right")
    elif eye.lower() == "both":
        send_message("blink_both")
    else:
        print("Invalid eye specified. Use 'left', 'right', or 'both'.")


def play_csv_animation(file_path, loop=False):
    try:
        with open(file_path, 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            rows = list(reader)

            if loop:
                row_iterator = cycle(rows)
            else:
                row_iterator = iter(rows)

            while True:
                try:
                    row = next(row_iterator)
                    x = float(row['x'])
                    y = float(row['y'])
                    set_joystick(x, y)

                    if 'blink' in row and row['blink'].lower() in ['left', 'right', 'both']:
                        trigger_blink(row['blink'])

                    # Default delay of 0.1 seconds if not specified
                    delay = float(row.get('delay', 0.1))
                    time.sleep(delay)
                except StopIteration:
                    break
    except FileNotFoundError:
        print(f"CSV file not found: {file_path}")
    except KeyError as e:
        print(f"Missing column in CSV: {e}")
    except ValueError as e:
        print(f"Invalid value in CSV: {e}")


def main():
    parser = argparse.ArgumentParser(description="Remote eye control script")
    parser.add_argument("--csv", help="Path to CSV file for animation")
    parser.add_argument("--loop", action="store_true",
                        help="Loop the CSV animation")
    args = parser.parse_args()

    if args.csv:
        play_csv_animation(args.csv, args.loop)
    else:
        while True:
            command = input(
                "Enter command (auto_movement, auto_blink, joystick, blink, quit): ").lower()

            if command == "quit":
                break
            elif command == "auto_movement":
                toggle_auto_movement(
                    input("Enable auto movement? (y/n): ").lower() == 'y')
            elif command == "auto_blink":
                toggle_auto_blink(
                    input("Enable auto blink? (y/n): ").lower() == 'y')
            elif command == "joystick":
                x = float(input("Enter x coordinate (-1 to 1): "))
                y = float(input("Enter y coordinate (-1 to 1): "))
                set_joystick(x, y)
            elif command == "blink":
                eye = input("Which eye to blink? (left/right/both): ")
                trigger_blink(eye)
            else:
                print("Invalid command")


if __name__ == "__main__":
    main()
