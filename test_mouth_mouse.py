import socket
import struct
import tkinter as tk
import argparse


class ServoControl:
    def __init__(self, root, host, port):
        self.root = root
        self.root.title("Servo Mouse Control")

        # UDP setup
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.host = host
        self.port = port

        # Initialize position
        self.position = 128

        # Create canvas for mouse movement
        self.canvas = tk.Canvas(root, width=400, height=100, bg='white')
        self.canvas.pack(pady=10)

        # Draw slider background
        self.canvas.create_rectangle(50, 40, 350, 60, fill='lightgray')

        # Create slider handle
        self.handle = self.canvas.create_oval(190, 35, 210, 65, fill='blue')

        # Position display label
        self.pos_label = tk.Label(root, text="Position: 128/255 (50.2%)")
        self.pos_label.pack(pady=5)

        # Control instructions
        instructions = """
        Mouse Controls:
        - Click and drag the blue handle left/right
        - Click anywhere on the slider to jump to position
        
        Keyboard Shortcuts:
        - Space: Center position (128)
        - Home: Minimum (0)
        - End: Maximum (255)
        """
        tk.Label(root, text=instructions, justify=tk.LEFT).pack(pady=10)

        # Bind mouse events
        self.canvas.bind('<Button-1>', self.on_click)
        self.canvas.bind('<B1-Motion>', self.on_drag)

        # Bind keyboard events
        self.root.bind('<space>', lambda e: self.set_position(128))
        self.root.bind('<Home>', lambda e: self.set_position(0))
        self.root.bind('<End>', lambda e: self.set_position(255))

        # Set initial position
        self.update_handle_position()

    def x_to_position(self, x):
        """Convert canvas X coordinate to servo position"""
        # Map 50-350 (canvas) to 0-255 (servo)
        x = max(50, min(350, x))
        return int((x - 50) * 255 / 300)

    def position_to_x(self, position):
        """Convert servo position to canvas X coordinate"""
        # Map 0-255 (servo) to 50-350 (canvas)
        return 50 + (position * 300 / 255)

    def update_handle_position(self):
        """Update the visual position of the slider handle"""
        x = self.position_to_x(self.position)
        self.canvas.coords(self.handle, x-10, 35, x+10, 65)
        self.pos_label.config(
            text=f"Position: {self.position}/255 ({self.position/255*100:.1f}%)")

    def set_position(self, position):
        """Set the servo position and update the display"""
        old_position = self.position
        self.position = max(0, min(255, position))
        self.update_handle_position()

        # Send UDP message if position changed
        if self.position != old_position:
            message = struct.pack('BB', 0x50, self.position)
            self.sock.sendto(message, (self.host, self.port))

    def on_click(self, event):
        """Handle mouse click on the slider"""
        self.set_position(self.x_to_position(event.x))

    def on_drag(self, event):
        """Handle mouse drag on the slider"""
        self.set_position(self.x_to_position(event.x))


def main():
    parser = argparse.ArgumentParser(description="Servo Mouse Control")
    parser.add_argument("--port", type=int, default=5006,
                        help="UDP port (default: 5006)")
    parser.add_argument("--host", type=str, default="localhost",
                        help="Target host (default: localhost)")
    args = parser.parse_args()

    root = tk.Tk()
    app = ServoControl(root, args.host, args.port)

    # Set window size and position
    root.geometry("400x300")
    root.resizable(False, False)

    print(f"Controlling servo at {args.host}:{args.port}")
    root.mainloop()


if __name__ == '__main__':
    main()
