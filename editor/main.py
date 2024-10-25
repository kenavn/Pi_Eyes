import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pygame
from datetime import datetime
from timeline_widget import TimelineCanvas
from audio_player import AudioPlayer  # Changed from AudioPlayer
from eye_controller import EyeController
from settings import Settings


class AnimationControlGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Animation Control Studio")

        # Initialize controllers and settings
        pygame.init()
        self.settings = Settings()
        self.audio_player = AudioPlayer()
        self.eye_controller = EyeController(
            self.settings.get_setting("host"), self.settings.get_setting("eye_port")
        )

        # State variables
        self.is_recording = False
        self.is_playing = False

        self.setup_gui()

    def setup_gui(self):
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Create menu
        self.create_menu()

        # Create main control section
        self.create_transport_controls(main_frame)

        # Create timeline
        self.timeline = TimelineCanvas(main_frame, height=400)
        self.timeline.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        # Create recording controls
        self.create_recording_controls(main_frame)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(main_frame, textvariable=self.status_var).grid(
            row=4, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5
        )

        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        # Start update loop
        self.update_gui()

    def create_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Load Audio", command=self.load_audio)
        file_menu.add_command(label="Save Recording", command=self.save_recording)
        file_menu.add_separator()
        file_menu.add_command(label="Settings", command=self.show_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_exit)

    def create_transport_controls(self, parent):
        transport_frame = ttk.LabelFrame(parent, text="Transport Controls", padding="5")
        transport_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        # Audio file controls
        ttk.Button(transport_frame, text="Load Audio", command=self.load_audio).grid(
            row=0, column=0, padx=5
        )
        self.audio_label = ttk.Label(transport_frame, text="No audio loaded")
        self.audio_label.grid(row=0, column=1, sticky=tk.W)

    def create_recording_controls(self, parent):
        control_frame = ttk.LabelFrame(parent, text="Recording Controls", padding="5")
        control_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        # Record options frame
        options_frame = ttk.Frame(control_frame)
        options_frame.grid(row=0, column=0, columnspan=2, pady=5)

        # Record on playback option
        self.record_on_play_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options_frame,
            text="Record on Playback",
            variable=self.record_on_play_var,
            command=self.update_record_controls,
        ).grid(row=0, column=0, padx=5)

        # Target selection (one must be selected, eyes default)
        self.record_target_var = tk.StringVar(value="eyes")
        self.eye_radio = ttk.Radiobutton(
            options_frame,
            text="Record Eyes",
            variable=self.record_target_var,
            value="eyes",
            state="disabled",
        )
        self.eye_radio.grid(row=0, column=1, padx=5)

        self.mouth_radio = ttk.Radiobutton(
            options_frame,
            text="Record Mouth",
            variable=self.record_target_var,
            value="mouth",
            state="disabled",
        )
        self.mouth_radio.grid(row=0, column=2, padx=5)

        # Playback/Record controls
        control_frame = ttk.Frame(control_frame)
        control_frame.grid(row=1, column=0, columnspan=2, pady=5)

        self.play_record_button = ttk.Button(
            control_frame, text="▶", command=self.play_or_record
        )
        self.play_record_button.grid(row=0, column=0, padx=2)

        ttk.Button(control_frame, text="⏸", command=self.pause).grid(
            row=0, column=1, padx=2
        )
        ttk.Button(control_frame, text="⏹", command=self.stop).grid(
            row=0, column=2, padx=2
        )

        # Clear buttons
        clear_frame = ttk.Frame(control_frame)
        clear_frame.grid(row=2, column=0, columnspan=2, pady=5)

        ttk.Button(
            clear_frame, text="Clear Eye Track", command=self.clear_eye_track
        ).grid(row=0, column=0, padx=5)
        ttk.Button(
            clear_frame, text="Clear Mouth Track", command=self.clear_mouth_track
        ).grid(row=0, column=1, padx=5)

    def update_record_controls(self):
        """Update controls based on record on playback setting"""
        if self.record_on_play_var.get():
            self.play_record_button.config(
                text="▶/⏺"
            )  # Combined play and record symbols
            self.eye_radio.config(state="normal")
            self.mouth_radio.config(state="normal")
        else:
            self.play_record_button.config(text="▶")
            self.eye_radio.config(state="disabled")
            self.mouth_radio.config(state="disabled")

    def load_audio(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("Audio files", "*.wav"), ("All files", "*.*")]
        )
        if file_path:
            if self.audio_player.load_file(file_path):
                self.audio_label.config(text=file_path.split("/")[-1])
                # Set audio duration for timeline
                duration_ms = self.audio_player.get_duration()
                self.timeline.set_audio_duration(duration_ms)
                # Load audio data for visualization
                self.timeline.load_audio_file(file_path)
                self.status_var.set("Audio loaded")
            else:
                messagebox.showerror("Error", "Failed to load audio file")

    def play_or_record(self):
        """Handle play or record based on current mode"""
        if self.record_on_play_var.get():
            # Record mode [existing recording code remains the same]
            target = self.record_target_var.get()
            if target == "eyes":
                print("Starting new eye recording")
                self.timeline.clear_eye_data()
            else:
                self.timeline.clear_mouth_data()

            self.recording_start_time = datetime.now()
            self.is_playing = True
            self.is_recording = True
            print("Recording started")
            self.status_var.set(f"Recording {target}")
        else:
            # Playback mode
            has_recording = len(self.timeline.eye_data) > 0
            print(f"Attempting playback with {len(self.timeline.eye_data)} frames")

            if not has_recording and not self.audio_player.is_loaded():
                messagebox.showwarning("Warning", "No recording or audio to play")
                return

            # Start playback
            self.recording_start_time = datetime.now()
            self.is_playing = True
            self.is_recording = False

            # Disable joystick during playback
            self.eye_controller.joystick_enabled = False
            print("Disabled joystick for playback")

            if self.audio_player.is_loaded():
                self.audio_player.play()

            self.status_var.set("Playing back recording")

    def pause(self):
        if self.audio_player.is_loaded():
            self.audio_player.pause()
        self.is_playing = False
        self.is_recording = False
        self.status_var.set("Paused")

    def stop(self):
        if self.audio_player.is_loaded():
            self.audio_player.stop()
        self.is_playing = False
        self.is_recording = False
        # Re-enable joystick when stopping
        self.eye_controller.joystick_enabled = True
        self.timeline.update_time_marker(0)
        self.status_var.set("Stopped")

    def update_gui(self):
        """Update GUI state and timeline"""
        current_time = 0

        if self.is_playing:
            if self.audio_player.is_loaded():
                current_time = self.audio_player.get_position()
            elif self.is_recording:
                current_time = int(
                    (datetime.now() - self.recording_start_time).total_seconds() * 1000
                )
            else:  # Playback without audio
                current_time = int(
                    (datetime.now() - self.recording_start_time).total_seconds() * 1000
                )

            # Update timeline marker
            self.timeline.update_time_marker(current_time)

            if self.is_recording and self.record_target_var.get() == "eyes":
                # Recording mode [existing recording code remains the same]
                print(
                    f"Recording frame at {current_time}ms:",
                    f"X: {self.eye_controller.current_eye_x:.3f}",
                    f"Y: {self.eye_controller.current_eye_y:.3f}",
                )

                self.timeline.add_eye_data_point(
                    current_time,
                    self.eye_controller.current_eye_x,
                    self.eye_controller.current_eye_y,
                    self.eye_controller.prev_button_states["BTN_WEST"] == 1,
                    self.eye_controller.prev_button_states["BTN_EAST"] == 1,
                    self.eye_controller.prev_button_states["BTN_SOUTH"] == 1,
                )
            elif not self.is_recording:
                # Playback mode
                self.apply_recorded_movements(current_time)

        self.root.after(16, self.update_gui)  # ~60fps update

    def apply_recorded_movements(self, current_time):
        """Apply recorded movements during playback"""
        if (
            not self.is_recording
            and self.is_playing
            and len(self.timeline.eye_data) > 0
        ):
            # Find the appropriate frame for current time
            frame_to_play = None
            for frame in self.timeline.eye_data:
                if frame[0] <= current_time:
                    frame_to_play = frame
                else:
                    break

            if frame_to_play:
                time_ms, x, y, left_blink, right_blink, both_eyes = frame_to_play
                print(f"Playing frame at {current_time}ms: X={x:.2f}, Y={y:.2f}")

                # Send position to device
                command = f"joystick,{x:.2f},{y:.2f}"
                self.eye_controller.send_message(command)

                # Handle blinks
                if both_eyes:
                    if not self.eye_controller.left_eye_closed:
                        self.eye_controller.send_message("blink_both_start")
                elif not both_eyes and self.eye_controller.left_eye_closed:
                    self.eye_controller.send_message("blink_both_end")

                # Update controller state
                self.eye_controller.current_eye_x = x
                self.eye_controller.current_eye_y = y
                self.eye_controller.left_eye_closed = both_eyes
                self.eye_controller.right_eye_closed = both_eyes

    def clear_eye_track(self):
        if messagebox.askyesno("Clear Track", "Clear eye movement recording?"):
            self.timeline.clear_eye_data()

    def clear_mouth_track(self):
        if messagebox.askyesno("Clear Track", "Clear mouth movement recording?"):
            self.timeline.clear_mouth_data()

    def save_recording(self):
        # To be implemented
        pass

    def show_settings(self):
        # To be implemented
        pass

    def on_exit(self):
        if self.is_recording:
            if not messagebox.askyesno("Exit", "Recording in progress. Exit anyway?"):
                return
        self.eye_controller.cleanup()
        pygame.quit()
        self.root.quit()


def main():
    root = tk.Tk()
    app = AnimationControlGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_exit)
    root.mainloop()


if __name__ == "__main__":
    main()
