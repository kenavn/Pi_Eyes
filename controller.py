import socket
import time
from inputs import devices, get_gamepad
import math
import threading
import atexit
import struct
import csv
from datetime import datetime, timedelta
import queue
import argparse


class EyeController:
    def __init__(self):
        self.UDP_IP = "10.0.1.151"  # Replace with the IP of your eye device
        self.UDP_PORT = 5005  # Make sure this matches the port in your eye script
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.record_queue = queue.Queue()
        self.disk_writer_thread = None
        self.recording_start_time = None

        self.current_eye_x = 0
        self.current_eye_y = 0
        self.current_left_eyelid = 0
        self.current_right_eyelid = 0
        self.left_eye_closed = False
        self.right_eye_closed = False

        self.gamepad_state = {
            "LX": 0, "LY": 0, "RX": 0, "RY": 0, "LT": 0, "RT": 0,
            "BTN_NORTH": 0, "BTN_EAST": 0, "BTN_SOUTH": 0, "BTN_WEST": 0, "BTN_SELECT": 0
        }

        self.controller_type = None
        self.joystick_connected = False
        self.auto_movement = True
        self.auto_blink = True
        self.auto_pupil = True

        self.is_recording = False
        self.record_file = None
        self.record_writer = None
        self.last_state = {}
        self.last_state_time = None

    def encode_message(self, command, data=None):
        if command == "joystick_connected":
            return b'\x01'
        elif command == "joystick_disconnected":
            return b'\x00'
        elif command == "auto_movement_on":
            return b'\x11'
        elif command == "auto_movement_off":
            return b'\x10'
        elif command == "auto_blink_on":
            return b'\x13'
        elif command == "auto_blink_off":
            return b'\x12'
        elif command == "auto_pupil_on":
            return b'\x15'
        elif command == "auto_pupil_off":
            return b'\x14'
        elif command.startswith("joystick"):
            _, x, y = command.split(',')
            x_byte = int(float(x) * 255)
            y_byte = int(float(y) * 255)
            return b'\x20' + struct.pack('BB', x_byte, y_byte)
        elif command.startswith("left_eyelid"):
            _, position = command.split(',')
            pos_byte = int(float(position) * 255)
            return b'\x30' + struct.pack('B', pos_byte)
        elif command.startswith("right_eyelid"):
            _, position = command.split(',')
            pos_byte = int(float(position) * 255)
            return b'\x31' + struct.pack('B', pos_byte)
        elif command == "blink_left_start":
            return b'\x40'
        elif command == "blink_left_end":
            return b'\x41'
        elif command == "blink_right_start":
            return b'\x42'
        elif command == "blink_right_end":
            return b'\x43'
        elif command == "blink_both_start":
            return b'\x44'
        elif command == "blink_both_end":
            return b'\x45'
        else:
            raise ValueError(f"Unknown command: {command}")

    def send_message(self, message):
        encoded_message = self.encode_message(message)
        self.sock.sendto(encoded_message, (self.UDP_IP, self.UDP_PORT))
        print(f"Sent: {message} (encoded: {encoded_message.hex()})")

    def normalize_joystick(self, value):
        return value / 32768.0  # This converts the raw value to a range of -1 to 1

    def set_joystick(self, x, y):
        # Define the observed ranges
        x_min, x_max = 0, 0.00778198
        y_min, y_max = 0, 0.00778190

        # Map the joystick range to 0 to 1 range
        eye_x = round((x - x_min) / (x_max - x_min), 2)
        eye_y = round(1 - (y - y_min) / (y_max - y_min), 2)  # Invert Y axis

        # Ensure the values stay within the 0 to 1 range
        eye_x = max(min(eye_x, 1), 0)
        eye_y = max(min(eye_y, 1), 0)

        if eye_x != self.current_eye_x or eye_y != self.current_eye_y:
            self.send_message(f"joystick,{eye_x},{eye_y}")
            self.current_eye_x = eye_x
            self.current_eye_y = eye_y
            if self.is_recording:
                self.record_state_change()

    def set_eyelids(self, position):
        # Convert the -1 to 1 range to the 0 to 1 range expected by the eye script
        eyelid_position = round((position + 1) / 2, 2)

        if eyelid_position != self.current_left_eyelid or eyelid_position != self.current_right_eyelid:
            self.send_message(f"left_eyelid,{eyelid_position}")
            self.send_message(f"right_eyelid,{eyelid_position}")
            self.current_left_eyelid = eyelid_position
            self.current_right_eyelid = eyelid_position
            if self.is_recording:
                self.record_state_change()

    def start_blink(self, eye):
        if eye in ['left', 'both']:
            self.left_eye_closed = True
            self.send_message("blink_left_start")
        if eye in ['right', 'both']:
            self.right_eye_closed = True
            self.send_message("blink_right_start")
        if self.is_recording:
            self.record_state_change()

    def end_blink(self, eye):
        if eye in ['left', 'both']:
            self.left_eye_closed = False
            self.send_message("blink_left_end")
        if eye in ['right', 'both']:
            self.right_eye_closed = False
            self.send_message("blink_right_end")
        if self.is_recording:
            self.record_state_change()

    def connect_joystick(self):
        self.send_message("joystick_connected")
        self.joystick_connected = True
        self.auto_movement = False
        self.auto_blink = False
        self.auto_pupil = False
        print("Joystick connected")

    def disconnect_joystick(self):
        self.send_message("joystick_disconnected")
        self.joystick_connected = False
        self.auto_movement = True
        self.auto_blink = True
        self.auto_pupil = True
        self.send_message("auto_movement_on")
        self.send_message("auto_blink_on")
        self.send_message("auto_pupil_on")
        print("Joystick disconnected")

    def toggle_auto_feature(self, feature):
        if feature == "movement":
            self.auto_movement = not self.auto_movement
            self.send_message(
                f"auto_movement_{'on' if self.auto_movement else 'off'}")
        elif feature == "blink":
            self.auto_blink = not self.auto_blink
            self.send_message(
                f"auto_blink_{'on' if self.auto_blink else 'off'}")
        elif feature == "pupil":
            self.auto_pupil = not self.auto_pupil
            self.send_message(
                f"auto_pupil_{'on' if self.auto_pupil else 'off'}")
        print(f"Auto {feature} {'enabled' if getattr(
            self, f'auto_{feature}') else 'disabled'}")

    def detect_controller(self):
        for device in devices:
            if "XBOX" in device.name.upper():
                self.controller_type = "xbox"
                break
            elif "SONY" in device.name.upper() or "PS4" in device.name.upper():
                self.controller_type = "ps4"
                break

        if self.controller_type:
            print(f"Detected {self.controller_type.upper()} controller")
        else:
            print(
                "No compatible controller detected. Please connect an Xbox or PS4 controller.")

    def gamepad_reader(self):
        last_share_state = 0
        while True:
            events = get_gamepad()
            for event in events:
                if event.code in self.gamepad_state:
                    self.gamepad_state[event.code] = event.state
                elif event.code == "ABS_X":
                    self.gamepad_state["LX"] = event.state
                elif event.code == "ABS_Y":
                    self.gamepad_state["LY"] = event.state
                elif event.code == "ABS_RX":
                    self.gamepad_state["RX"] = event.state
                elif event.code == "ABS_RY":
                    self.gamepad_state["RY"] = event.state

                # Check for SHARE button press (BTN_SELECT)
                if event.code == "BTN_SELECT":
                    if event.state == 1 and last_share_state == 0:  # Button just pressed
                        if self.is_recording:
                            print("Stopping recording...")
                            self.stop_recording()
                        else:
                            print("Starting recording...")
                            self.start_recording()
                    last_share_state = event.state

    def eye_controller(self):
        last_x = 0
        last_y = 0
        last_eyelid_position = 0
        last_left_blink_state = 0
        last_right_blink_state = 0
        last_both_blink_state = 0

        while True:
            if self.controller_type and self.joystick_connected:
                x = self.normalize_joystick(self.gamepad_state["LX"])
                y = self.normalize_joystick(self.gamepad_state["LY"])

                if x != last_x or y != last_y:
                    self.set_joystick(x, y)
                    last_x = x
                    last_y = y

                eyelid_position = self.normalize_joystick(
                    self.gamepad_state["RY"])

                if eyelid_position != last_eyelid_position:
                    self.set_eyelids(eyelid_position)
                    last_eyelid_position = eyelid_position

                left_blink_state = self.gamepad_state["BTN_WEST"]
                right_blink_state = self.gamepad_state["BTN_EAST"]
                both_blink_state = self.gamepad_state["BTN_SOUTH"]

                if left_blink_state != last_left_blink_state:
                    if left_blink_state == 1:
                        self.start_blink('left')
                    else:
                        self.end_blink('left')
                    last_left_blink_state = left_blink_state

                if right_blink_state != last_right_blink_state:
                    if right_blink_state == 1:
                        self.start_blink('right')
                    else:
                        self.end_blink('right')
                    last_right_blink_state = right_blink_state

                if both_blink_state != last_both_blink_state:
                    if both_blink_state == 1:
                        self.start_blink('both')
                    else:
                        self.end_blink('both')
                    last_both_blink_state = both_blink_state

            time.sleep(0.01)

    def start_recording(self):
        if not self.is_recording:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"eye_recording_{timestamp}.csv"
            self.record_file = open(filename, 'w', newline='')
            self.record_writer = csv.writer(self.record_file)
            self.record_writer.writerow(['time_ms', 'eye_x', 'eye_y',
                                        'left_eyelid', 'right_eyelid', 'left_eye_closed', 'right_eye_closed'])
            self.is_recording = True
            self.last_state = {}
            self.recording_start_time = datetime.now()
            self.last_state_time = self.recording_start_time

            # Start the disk writer thread
            self.disk_writer_thread = threading.Thread(
                target=self.disk_writer, daemon=True)
            self.disk_writer_thread.start()

            print(f"Recording started: {filename}")

    def stop_recording(self):
        if self.is_recording:
            self.is_recording = False

            # Wait for the disk writer thread to finish processing
            if self.disk_writer_thread is not None:
                self.disk_writer_thread.join()
                self.disk_writer_thread = None

            self.record_file.close()
            print("Recording stopped")

    def record_state_change(self):
        if not self.is_recording:
            return

        current_time = datetime.now()
        current_state = {
            'eye_x': self.current_eye_x,
            'eye_y': self.current_eye_y,
            'left_eyelid': self.current_left_eyelid,
            'right_eyelid': self.current_right_eyelid,
            'left_eye_closed': self.left_eye_closed,
            'right_eye_closed': self.right_eye_closed
        }

        # Calculate the time since recording started
        time_ms = int(
            (current_time - self.recording_start_time).total_seconds() * 1000)

        # Put the state change into the queue
        self.record_queue.put([
            time_ms,
            current_state['eye_x'],
            current_state['eye_y'],
            current_state['left_eyelid'],
            current_state['right_eyelid'],
            current_state['left_eye_closed'],
            current_state['right_eye_closed']
        ])

        self.last_state = current_state
        self.last_state_time = current_time

    def replay_recording(self, filename, loop=False, freeze=False):
        print(f"Replaying recording: {filename}")
        last_state = None
        while True:
            with open(filename, 'r') as file:
                reader = csv.DictReader(file)
                last_time = 0
                for row in reader:
                    current_time = int(row['time_ms'])

                    time_diff = (current_time - last_time) / \
                        1000  # Convert to seconds
                    time.sleep(time_diff)

                    # Send eye position
                    self.set_joystick(float(row['eye_x']), float(row['eye_y']))

                    # Send eyelid position
                    # Assuming left and right are the same
                    self.set_eyelids(float(row['left_eyelid']))

                    # Handle eye blink states
                    if row['left_eye_closed'] == 'True':
                        self.start_blink('left')
                    else:
                        self.end_blink('left')

                    if row['right_eye_closed'] == 'True':
                        self.start_blink('right')
                    else:
                        self.end_blink('right')

                    last_time = current_time
                    last_state = row

            if not loop:
                break

        print("Replay completed")

        if freeze and last_state:
            print("Freezing final state...")
            self.set_joystick(
                float(last_state['eye_x']), float(last_state['eye_y']))
            self.set_eyelids(float(last_state['left_eyelid']))
            if last_state['left_eye_closed'] == 'True':
                self.start_blink('left')
            else:
                self.end_blink('left')
            if last_state['right_eye_closed'] == 'True':
                self.start_blink('right')
            else:
                self.end_blink('right')
        else:
            print("Returning to neutral position...")
            self.set_joystick(0.5, 0.5)  # Center position
            self.set_eyelids(0)  # Fully open
            self.end_blink('both')

    def run(self):
        print("Controller Eye Control")
        print("Detecting controller...")
        self.detect_controller()

        if not self.controller_type:
            return

        print("Controller detected. Connecting joystick...")
        self.connect_joystick()

        print("Use left stick to move eyes")
        print("Use right stick (vertical) to control eyelids")
        print("Square/X: Hold to close left eye")
        print("Circle/B: Hold to close right eye")
        print("X/A: Hold to close both eyes")
        print("SHARE: Start/Stop recording")
        print("Press Ctrl+C to exit")

        # Start the gamepad reader thread
        gamepad_thread = threading.Thread(
            target=self.gamepad_reader, daemon=True)
        gamepad_thread.start()

        # Start the eye controller thread
        eye_thread = threading.Thread(target=self.eye_controller, daemon=True)
        eye_thread.start()

        # Main loop for handling program exit
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("Exiting...")
            self.cleanup()

    def disk_writer(self):
        while self.is_recording or not self.record_queue.empty():
            try:
                # Wait for a state change to be available in the queue
                state_change = self.record_queue.get(timeout=0.1)
                # Write the state change to the CSV file
                self.record_writer.writerow(state_change)
                self.record_queue.task_done()
            except queue.Empty:
                continue

    def cleanup(self):
        print("\nDisconnecting joystick and exiting...")
        self.disconnect_joystick()
        if self.is_recording:
            self.stop_recording()
        self.sock.close()


def main():
    parser = argparse.ArgumentParser(
        description="Controller Eye Control with recording and replay")
    parser.add_argument("-r", "--replay", help="Specify a file to replay")
    parser.add_argument("-l", "--loop", action="store_true",
                        help="Loop the replay")
    parser.add_argument("-f", "--freeze", action="store_true",
                        help="Freeze the final state after replay")
    args = parser.parse_args()

    controller = EyeController()

    if args.replay:
        controller.replay_recording(args.replay, args.loop, args.freeze)
    else:
        controller.run()


if __name__ == "__main__":
    main()
