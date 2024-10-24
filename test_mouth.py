import socket
import struct
import time
import curses
import argparse


def main(stdscr):
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Servo Keyboard Control")
    parser.add_argument("--port", type=int, default=5006,
                        help="UDP port (default: 5006)")
    parser.add_argument("--host", type=str, default="localhost",
                        help="Target host (default: localhost)")
    args = parser.parse_args()

    # Set up UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Set up curses
    curses.curs_set(0)  # Hide cursor
    stdscr.nodelay(1)   # Non-blocking input
    stdscr.timeout(100)  # 100ms timeout

    # Initialize position
    position = 128  # Start at middle position

    # Clear screen and draw initial interface
    stdscr.clear()
    stdscr.addstr(0, 0, "Servo Control")
    stdscr.addstr(2, 0, "Controls:")
    stdscr.addstr(3, 0, "↑/↓ - Increment/decrement by 1")
    stdscr.addstr(4, 0, "Page Up/Down - Increment/decrement by 10")
    stdscr.addstr(5, 0, "Home - Set to minimum (0)")
    stdscr.addstr(6, 0, "End - Set to maximum (255)")
    stdscr.addstr(7, 0, "Space - Set to middle (128)")
    stdscr.addstr(8, 0, "Q - Quit")

    while True:
        # Update position display
        stdscr.addstr(10, 0, f"Current position: {
                      position}/255 ({position/255*100:.1f}%)")
        stdscr.refresh()

        # Get keyboard input
        try:
            key = stdscr.getch()
        except:
            key = -1

        old_position = position

        if key == curses.KEY_UP and position < 255:
            position = min(255, position + 1)
        elif key == curses.KEY_DOWN and position > 0:
            position = max(0, position - 1)
        elif key == curses.KEY_PPAGE and position < 255:  # Page Up
            position = min(255, position + 10)
        elif key == curses.KEY_NPAGE and position > 0:    # Page Down
            position = max(0, position - 10)
        elif key == curses.KEY_HOME:  # Home key
            position = 0
        elif key == curses.KEY_END:   # End key
            position = 255
        elif key == ord(' '):         # Space bar
            position = 128
        elif key == ord('q') or key == ord('Q'):
            break

        # Send UDP message if position changed
        if position != old_position:
            message = struct.pack('BB', 0x50, position)
            sock.sendto(message, (args.host, args.port))

    # Clean up
    sock.close()


if __name__ == '__main__':
    curses.wrapper(main)
