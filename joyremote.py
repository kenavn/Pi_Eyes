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


def set_joystick(x, y):
    # Convert the -1 to 1 range to the -30 to 30 range expected by the eye script
    # and apply additional scaling to make the movement more noticeable
    eye_x = round(x * 30, 2)
    eye_y = round(y * -30, 2)  # Invert Y axis to match eye movement

    # Apply a scaling factor to make the values larger
    scaling_factor = 5  # Adjust this value as needed
    eye_x *= scaling_factor
    eye_y *= scaling_factor

    # Ensure the values stay within the -30 to 30 range
    eye_x = max(min(eye_x, 30), -30)
    eye_y = max(min(eye_y, 30), -30)

    send_message(f"joystick,{eye_x},{eye_y}")


def trigger_blink(eye):
    send_message(f"blink_{eye}")


def connect_joystick():
    global joystick_connected, auto_movement, auto_blink, auto_pupil
    send_message("joystick_connected")
    joystick_connected = True
    auto_movement = False
    auto_blink = False
    auto_pupil = False
    send_message("auto_movement_off")
    send_message("auto_blink_off")
    send_message("auto_pupil_off")
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


def eye_controller():
    global joystick_connected
    last_blink_time = 0
    blink_cooldown = 0.5  # Cooldown time between blinks in seconds

    while True:
        if controller_type and joystick_connected:
            # Map left stick to eye movement
            x = normalize_joystick(gamepad_state["LX"])
            y = normalize_joystick(gamepad_state["LY"])
            set_joystick(x, y)

            # Use buttons for blinking
            current_time = time.time()
            if current_time - last_blink_time > blink_cooldown:
                if gamepad_state["BTN_WEST"] == 1:  # X on Xbox, Square on PS4
                    trigger_blink("left")
                    last_blink_time = current_time
                elif gamepad_state["BTN_EAST"] == 1:  # B on Xbox, Circle on PS4
                    trigger_blink("right")
                    last_blink_time = current_time
                elif gamepad_state["BTN_SOUTH"] == 1:  # A on Xbox, X on PS4
                    trigger_blink("both")
                    last_blink_time = current_time

        # Add a small delay to prevent overwhelming the network
        time.sleep(0.05)


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
    print("Square/X: Blink left eye")
    print("Circle/B: Blink right eye")
    print("X/A: Blink both eyes")
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
