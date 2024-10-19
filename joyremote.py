import socket
import time
from inputs import devices, get_gamepad
import math
import threading
import atexit

# UDP settings
UDP_IP = "10.0.1.151"  # Replace with the IP of your eye device
UDP_PORT = 5005  # Make sure this matches the port in your eye script

# Create a UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

current_eye_x = 0
current_eye_y = 0
current_left_eyelid = 0
current_right_eyelid = 0
left_eyelid_position = 0.0
right_eyelid_position = 0.0
left_eye_closed = False
right_eye_closed = False

# Gamepad state
gamepad_state = {
    "LX": 0,
    "LY": 0,
    "RX": 0,
    "RY": 0,
    "LT": 0,
    "RT": 0,
    "BTN_NORTH": 0,
    "BTN_EAST": 0,
    "BTN_SOUTH": 0,
    "BTN_WEST": 0
}

# Controller type
controller_type = None

# Joystick connection state
joystick_connected = False

# Auto features state
auto_movement = True
auto_blink = True
auto_pupil = True


def send_message(message):
    sock.sendto(message.encode(), (UDP_IP, UDP_PORT))
    print(f"Sent: {message}")


def normalize_joystick(value):
    return value / 32768.0  # This converts the raw value to a range of -1 to 1


def set_eyelids(position):
    global current_left_eyelid, current_right_eyelid
    # Convert the -1 to 1 range to the 0 to 1 range expected by the eye script
    eyelid_position = round((position + 1) / 2, 2)

    # Only send messages if the positions have changed
    if eyelid_position != current_left_eyelid:
        send_message(f"left_eyelid,{eyelid_position}")
        current_left_eyelid = eyelid_position

    if eyelid_position != current_right_eyelid:
        send_message(f"right_eyelid,{eyelid_position}")
        current_right_eyelid = eyelid_position


def start_blink(eye):
    global left_eye_closed, right_eye_closed
    if eye in ['left', 'both']:
        left_eye_closed = True
        send_message("blink_left_start")
    if eye in ['right', 'both']:
        right_eye_closed = True
        send_message("blink_right_start")


def end_blink(eye):
    global left_eye_closed, right_eye_closed
    if eye in ['left', 'both']:
        left_eye_closed = False
        send_message("blink_left_end")
    if eye in ['right', 'both']:
        right_eye_closed = False
        send_message("blink_right_end")


def set_joystick(x, y):
    # Define the observed ranges
    x_min, x_max = 0, 0.00778198
    y_min, y_max = 0, 0.00778190

    # Calculate the middle points
    x_mid = (x_min + x_max) / 2
    y_mid = (y_min + y_max) / 2

    # Map the joystick range to 0 to 1 range, with center at 0.5
    eye_x = round((x - x_min) / (x_max - x_min), 2)
    eye_y = round(1 - (y - y_min) / (y_max - y_min), 2)  # Invert Y axis

    # Ensure the values stay within the 0 to 1 range
    eye_x = max(min(eye_x, 1), 0)
    eye_y = max(min(eye_y, 1), 0)

    # Only send message if the position has changed
    global current_eye_x, current_eye_y
    if eye_x != current_eye_x or eye_y != current_eye_y:
        send_message(f"joystick,{eye_x},{eye_y}")
        current_eye_x = eye_x
        current_eye_y = eye_y

    # Debug output
    # print(f"Raw joystick: x={x}, y={y}")
    # print(f"Eye position: x={eye_x}, y={eye_y}")


def trigger_blink(eye):
    send_message(f"blink_{eye}")


def connect_joystick():
    global joystick_connected, auto_movement, auto_blink, auto_pupil
    send_message("joystick_connected")
    joystick_connected = True
    auto_movement = False
    auto_blink = False
    auto_pupil = False
    # send_message("auto_movement_off")
    # send_message("auto_blink_off")
    # send_message("auto_pupil_off")
    print("Joystick connected")


def disconnect_joystick():
    global joystick_connected, auto_movement, auto_blink, auto_pupil
    send_message("joystick_disconnected")
    joystick_connected = False
    auto_movement = True
    auto_blink = True
    auto_pupil = True
    send_message("auto_movement_on")
    send_message("auto_blink_on")
    send_message("auto_pupil_on")
    print("Joystick disconnected")


def toggle_auto_feature(feature):
    global auto_movement, auto_blink, auto_pupil
    if feature == "movement":
        auto_movement = not auto_movement
        send_message(f"auto_movement_{'on' if auto_movement else 'off'}")
    elif feature == "blink":
        auto_blink = not auto_blink
        send_message(f"auto_blink_{'on' if auto_blink else 'off'}")
    elif feature == "pupil":
        auto_pupil = not auto_pupil
        send_message(f"auto_pupil_{'on' if auto_pupil else 'off'}")
    print(f"Auto {feature} {'enabled' if globals()
          [f'auto_{feature}'] else 'disabled'}")


def detect_controller():
    global controller_type
    for device in devices:
        if "XBOX" in device.name.upper():
            controller_type = "xbox"
            break
        elif "SONY" in device.name.upper() or "PS4" in device.name.upper():
            controller_type = "ps4"
            break

    if controller_type:
        print(f"Detected {controller_type.upper()} controller")
    else:
        print(
            "No compatible controller detected. Please connect an Xbox or PS4 controller.")


def gamepad_reader():
    while True:
        events = get_gamepad()
        for event in events:
            if event.code in gamepad_state:
                gamepad_state[event.code] = event.state
            elif event.code == "ABS_X":
                gamepad_state["LX"] = event.state
            elif event.code == "ABS_Y":
                gamepad_state["LY"] = event.state
            elif event.code == "ABS_RX":
                gamepad_state["RX"] = event.state
            elif event.code == "ABS_RY":
                gamepad_state["RY"] = event.state


def eye_controller():
    global joystick_connected, left_eye_closed, right_eye_closed
    last_x = 0
    last_y = 0
    last_eyelid_position = 0
    last_left_blink_state = 0
    last_right_blink_state = 0
    last_both_blink_state = 0

    while True:
        if controller_type and joystick_connected:
            # Map left stick to eye movement
            x = normalize_joystick(gamepad_state["LX"])
            y = normalize_joystick(gamepad_state["LY"])

            # Only update if position has changed
            if x != last_x or y != last_y:
                set_joystick(x, y)
                last_x = x
                last_y = y

            # Map right stick vertical axis to eyelid control
            eyelid_position = normalize_joystick(gamepad_state["RY"])

            # Only update eyelids if position has changed
            if eyelid_position != last_eyelid_position:
                set_eyelids(eyelid_position)
                last_eyelid_position = eyelid_position

            # Handle blinking with buttons
            left_blink_state = gamepad_state["BTN_WEST"]
            right_blink_state = gamepad_state["BTN_EAST"]
            both_blink_state = gamepad_state["BTN_SOUTH"]

            if left_blink_state != last_left_blink_state:
                if left_blink_state == 1:
                    send_message("blink_left_start")
                else:
                    send_message("blink_left_end")
                last_left_blink_state = left_blink_state

            if right_blink_state != last_right_blink_state:
                if right_blink_state == 1:
                    send_message("blink_right_start")
                else:
                    send_message("blink_right_end")
                last_right_blink_state = right_blink_state

            if both_blink_state != last_both_blink_state:
                if both_blink_state == 1:
                    send_message("blink_both_start")
                else:
                    send_message("blink_both_end")
                last_both_blink_state = both_blink_state

        # Add a small delay to prevent busy-waiting
        time.sleep(0.01)


def cleanup():
    print("\nDisconnecting joystick and exiting...")
    disconnect_joystick()
    sock.close()


def main():
    global joystick_connected
    print("Controller Eye Control")
    print("Detecting controller...")
    detect_controller()

    if not controller_type:
        return

    print("Use left stick to move eyes")
    print("Use right stick (vertical) to control eyelids")
    print("Square/X: Hold to close left eye")
    print("Circle/B: Hold to close right eye")
    print("X/A: Hold to close both eyes")
    print("Press 'C' to connect/disconnect joystick")
    print("Press 'M' to toggle auto movement")
    print("Press 'B' to toggle auto blink")
    print("Press 'P' to toggle auto pupil")
    print("Press Ctrl+C to exit")

    # Register the cleanup function to be called on exit
    atexit.register(cleanup)

    # Start the gamepad reader thread
    gamepad_thread = threading.Thread(target=gamepad_reader, daemon=True)
    gamepad_thread.start()

    # Start the eye controller thread
    eye_thread = threading.Thread(target=eye_controller, daemon=True)
    eye_thread.start()

    # Main loop for handling joystick connection/disconnection and auto feature toggling
    try:
        while True:
            command = input().lower()
            if command == 'c':
                if joystick_connected:
                    disconnect_joystick()
                else:
                    connect_joystick()
            elif command == 'm':
                toggle_auto_feature("movement")
            elif command == 'b':
                toggle_auto_feature("blink")
            elif command == 'p':
                toggle_auto_feature("pupil")
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass  # The cleanup function will handle the exit process


if __name__ == "__main__":
    main()
