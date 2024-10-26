import threading
import time
from inputs import devices, get_gamepad
from queue import Queue
from dataclasses import dataclass
from typing import Callable, Dict, List


@dataclass
class JoystickState:
    """Data class to hold complete joystick state"""

    # Analog sticks (0-255 range)
    left_x: int = 128
    left_y: int = 128
    right_x: int = 128
    right_y: int = 128

    # Buttons (0 or 1)
    btn_west: int = 0  # Square/X
    btn_east: int = 0  # Circle/B
    btn_south: int = 0  # X/A
    btn_north: int = 0  # Triangle/Y


class JoystickController:
    def __init__(self):
        self.running = True
        self.state = JoystickState()
        self.state_lock = threading.Lock()

        # Subscribers for state updates
        self.subscribers: List[Callable[[JoystickState], None]] = []

        # Start reader thread
        self.reader_thread = threading.Thread(target=self._read_gamepad, daemon=True)
        self.reader_thread.start()

        print("JoystickController: Started")

    def _read_gamepad(self):
        """Read gamepad events and update state"""
        print("JoystickController: Gamepad reader thread started")

        while self.running:
            try:
                events = get_gamepad()
                state_changed = False

                with self.state_lock:
                    for event in events:
                        if event.code == "ABS_X":
                            self.state.left_x = event.state
                            state_changed = True
                        elif event.code == "ABS_Y":
                            self.state.left_y = event.state
                            state_changed = True
                        elif event.code == "ABS_RX":
                            self.state.right_x = event.state
                            state_changed = True
                        elif event.code == "ABS_RY":
                            self.state.right_y = event.state
                            state_changed = True
                        elif event.code == "BTN_WEST":
                            self.state.btn_west = event.state
                            state_changed = True
                        elif event.code == "BTN_EAST":
                            self.state.btn_east = event.state
                            state_changed = True
                        elif event.code == "BTN_SOUTH":
                            self.state.btn_south = event.state
                            state_changed = True
                        elif event.code == "BTN_NORTH":
                            self.state.btn_north = event.state
                            state_changed = True

                # Notify subscribers if state changed
                if state_changed:
                    self._notify_subscribers()

            except Exception as e:
                print(f"JoystickController: Gamepad error: {e}")
                time.sleep(0.1)

    def _notify_subscribers(self):
        """Notify all subscribers of state change"""
        with self.state_lock:
            state_copy = JoystickState(
                left_x=self.state.left_x,
                left_y=self.state.left_y,
                right_x=self.state.right_x,
                right_y=self.state.right_y,
                btn_west=self.state.btn_west,
                btn_east=self.state.btn_east,
                btn_south=self.state.btn_south,
                btn_north=self.state.btn_north,
            )

        for subscriber in self.subscribers:
            try:
                subscriber(state_copy)
            except Exception as e:
                print(f"JoystickController: Error notifying subscriber: {e}")

    def subscribe(self, callback: Callable[[JoystickState], None]):
        """Add a subscriber for joystick state updates"""
        self.subscribers.append(callback)
        print(
            f"JoystickController: Added subscriber. Total subscribers: {len(self.subscribers)}"
        )

    def unsubscribe(self, callback: Callable[[JoystickState], None]):
        """Remove a subscriber"""
        if callback in self.subscribers:
            self.subscribers.remove(callback)
            print(
                f"JoystickController: Removed subscriber. Total subscribers: {len(self.subscribers)}"
            )

    def get_current_state(self) -> JoystickState:
        """Get current joystick state"""
        with self.state_lock:
            return JoystickState(
                left_x=self.state.left_x,
                left_y=self.state.left_y,
                right_x=self.state.right_x,
                right_y=self.state.right_y,
                btn_west=self.state.btn_west,
                btn_east=self.state.btn_east,
                btn_south=self.state.btn_south,
                btn_north=self.state.btn_north,
            )

    def cleanup(self):
        """Clean up resources"""
        print("JoystickController: Cleaning up...")
        self.running = False
        if self.reader_thread:
            self.reader_thread.join(timeout=1)
        print("JoystickController: Cleanup complete")
