import tkinter as tk
from tkinter import ttk
import numpy as np
import wave
import math


class TimelineCanvas(tk.Canvas):
    def __init__(self, parent, height=400, **kwargs):
        super().__init__(parent, height=height, bg="white", **kwargs)

        # Track dimensions
        self.total_height = height
        self.track_heights = {
            "audio": height // 3,
            "eyes": height // 3,
            "mouth": height // 3,
        }

        # Track positions (y-coordinates)
        self.track_positions = {
            "audio": 0,
            "eyes": self.track_heights["audio"],
            "mouth": self.track_heights["audio"] + self.track_heights["eyes"],
        }

        # Colors
        self.colors = {
            "audio": "#2196F3",  # Blue
            "eye_x": "#4CAF50",  # Green
            "eye_y": "#FFC107",  # Amber
            "blink": "#9C27B0",  # Purple
            "mouth": "#FF5722",  # Deep Orange
            "grid": "#E0E0E0",  # Light Gray
        }

        # Data storage
        self.audio_data = None
        self.eye_data = []
        self.mouth_data = []
        self.duration_ms = 10000  # Start with 10 seconds

        # Playback marker
        self.time_marker = self.create_line(
            0, 0, 0, height, fill="red", width=2, tags=("marker", "top"), state="normal"
        )

        # Create tracks
        self.setup_tracks()

        # Bind resize event
        self.bind("<Configure>", self.on_resize)

    def setup_tracks(self):
        """Create track backgrounds, labels, and gridlines"""
        self.delete("track_bg", "track_label", "grid", "axis_label")

        width = self.winfo_width()
        if width == 0:
            width = self.winfo_reqwidth()

        # Audio track
        y_audio = self.track_positions["audio"]
        self.create_rectangle(
            0,
            y_audio,
            width,
            y_audio + self.track_heights["audio"],
            fill="#f8f9fa",
            tags="track_bg",
        )
        self.create_text(5, y_audio + 10, text="Audio", anchor="w", tags="track_label")

        # Eyes track with grid
        y_eyes = self.track_positions["eyes"]
        h_eyes = self.track_heights["eyes"]
        self.create_rectangle(
            0, y_eyes, width, y_eyes + h_eyes, fill="#f8f9fa", tags="track_bg"
        )

        # Add grid lines for eye track
        grid_spacing = h_eyes / 4
        for i in range(1, 4):
            y = y_eyes + i * grid_spacing
            self.create_line(
                0, y, width, y, fill=self.colors["grid"], dash=(2, 4), tags="grid"
            )

        # Add axis labels for eye track
        self.create_text(5, y_eyes + 10, text="Eyes", anchor="w", tags="track_label")

        # Y-axis labels for eye track
        label_positions = {
            "1.0": y_eyes,
            "0.75": y_eyes + grid_spacing,
            "0.5": y_eyes + 2 * grid_spacing,
            "0.25": y_eyes + 3 * grid_spacing,
            "0.0": y_eyes + h_eyes,
        }

        for label, y in label_positions.items():
            self.create_text(
                25, y, text=label, anchor="e", font=("Arial", 8), tags="axis_label"
            )

        # Legend for eye track
        legend_y = y_eyes + 20
        legend_items = [
            ("X Position", self.colors["eye_x"]),
            ("Y Position", self.colors["eye_y"]),
            ("Blinks", self.colors["blink"]),
        ]

        for i, (label, color) in enumerate(legend_items):
            x = width - 100
            y = legend_y + i * 15
            self.create_line(x, y, x + 20, y, fill=color, width=2, tags="track_label")
            self.create_text(
                x + 25, y, text=label, anchor="w", font=("Arial", 8), tags="track_label"
            )

        # Mouth track
        y_mouth = self.track_positions["mouth"]
        self.create_rectangle(
            0,
            y_mouth,
            width,
            y_mouth + self.track_heights["mouth"],
            fill="#f8f9fa",
            tags="track_bg",
        )
        self.create_text(5, y_mouth + 10, text="Mouth", anchor="w", tags="track_label")

    def draw_eye_data(self):
        """Draw eye movement visualization"""
        self.delete("eye_data")

        if not self.eye_data:
            print("No eye data to draw")
            return

        print(f"Drawing {len(self.eye_data)} points")

        width = self.winfo_width()
        if width == 0:
            width = 800  # Default width if not yet set

        track_height = self.track_heights["eyes"]
        y_base = self.track_positions["eyes"]

        # Prepare points for each data type
        x_points = []
        y_points = []
        blink_points = []

        for time_ms, x, y, left_blink, right_blink, both_eyes in self.eye_data:
            # Calculate x position on timeline
            canvas_x = (
                (time_ms / self.duration_ms) * width if self.duration_ms > 0 else 0
            )

            # Calculate y positions
            y_x = y_base + (1 - x) * track_height
            y_y = y_base + (1 - y) * track_height

            # Add points
            x_points.extend([canvas_x, y_x])
            y_points.extend([canvas_x, y_y])

            # Handle blinks
            if both_eyes:
                blink_y = y_base
            elif left_blink or right_blink:
                blink_y = y_base + (track_height * 0.25)
            else:
                blink_y = y_base + track_height
            blink_points.extend([canvas_x, blink_y])

        # Draw the lines
        if len(x_points) > 2:
            self.create_line(
                *x_points, fill=self.colors["eye_x"], width=2, tags="eye_data"
            )
            self.create_line(
                *y_points, fill=self.colors["eye_y"], width=2, tags="eye_data"
            )
            self.create_line(
                *blink_points, fill=self.colors["blink"], width=2, tags="eye_data"
            )
            print("Drew all graph lines")

    def draw_mouth_data(self):
        """Draw mouth movement visualization"""
        self.delete("mouth_data")

        if not self.mouth_data:
            return

        width = self.winfo_width()
        track_height = self.track_heights["mouth"]
        y_base = self.track_positions["mouth"]

        points = []
        for time_ms, value in self.mouth_data:
            canvas_x = (time_ms / self.duration_ms) * width
            canvas_y = y_base + (1 - value) * track_height
            points.extend([canvas_x, canvas_y])

        if len(points) > 2:
            self.create_line(
                *points, fill=self.colors["mouth"], width=1, tags="mouth_data"
            )

    def add_eye_data_point(self, time_ms, x, y, left_blink, right_blink, both_eyes):
        """Add eye movement data point and update visualization"""
        print(f"Timeline: Adding point - Time: {time_ms}ms, X: {x:.3f}, Y: {y:.3f}")

        # Store the data point
        self.eye_data.append([time_ms, x, y, left_blink, right_blink, both_eyes])

        # Extend timeline if needed
        if time_ms > self.duration_ms:
            self.duration_ms = max(time_ms + 5000, 10000)
            print(f"Extended timeline duration to {self.duration_ms}ms")

        # Draw immediately
        self.draw_eye_data()
        print(f"Drew graph with {len(self.eye_data)} points")

    def add_mouth_data_point(self, time_ms, value):
        """Add mouth movement data point and update visualization"""
        self.mouth_data.append([time_ms, value])
        self.draw_mouth_data()

    def update_time_marker(self, time_ms):
        """Update playback position marker"""
        if self.duration_ms <= 0:
            self.duration_ms = 10000  # Default to 10 seconds if no duration set

        # Calculate x position
        width = self.winfo_width()
        x_pos = (time_ms / self.duration_ms) * width
        # Update marker position
        self.coords(self.time_marker, x_pos, 0, x_pos, self.total_height)
        self.tag_raise(self.time_marker)  # Ensure marker stays on top

    def clear_eye_data(self):
        """Clear eye movement data"""
        self.eye_data = []
        self.delete("eye_data")

    def clear_mouth_data(self):
        """Clear mouth movement data"""
        self.mouth_data = []
        self.delete("mouth_data")

    def set_audio_duration(self, duration_ms):
        """Set the timeline duration"""
        self.duration_ms = max(duration_ms, 10000)  # Minimum 10 seconds

    def on_resize(self, event):
        """Handle window resize"""
        self.setup_tracks()
        if self.eye_data:
            self.draw_eye_data()
        if self.mouth_data:
            self.draw_mouth_data()

        # Make sure the time marker spans the full height after resize
        _, _, x, _ = self.coords(self.time_marker)
        self.coords(self.time_marker, x, 0, x, self.total_height)
