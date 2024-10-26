import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pygame
from datetime import datetime, timedelta
from timeline_widget import TimelineCanvas
from audio_player import AudioPlayer  # Changed from AudioPlayer
from eye_controller import EyeController
from mouth_controller import MouthController
from joystick_controller import JoystickController
from settings import Settings
import time


class AnimationControlGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Skeleton Studio")

        # Initialize controllers and settings
        pygame.init()
        self.settings = Settings()
        self.audio_player = AudioPlayer()

        # Initialize centralized joystick controller
        self.joystick_controller = JoystickController()

        # Initialize controllers with joystick controller
        self.eye_controller = EyeController(
            self.settings.get_setting("host"),
            self.settings.get_setting("eye_port"),
            self.joystick_controller,
        )

        self.mouth_controller = MouthController(
            self.settings.get_setting("host"),
            self.settings.get_setting("mouth_port"),
            self.joystick_controller,
        )

        # State variables
        self.is_recording = False
        self.is_playing = False
        self.is_paused = False
        self.elapsed_time = 0

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

        self.pause_button = ttk.Button(
            control_frame, text="⏸", command=self.pause, state="disabled"
        )
        self.pause_button.grid(row=0, column=1, padx=2)

        self.stop_button = ttk.Button(
            control_frame, text="⏹", command=self.stop, state="disabled"
        )
        self.stop_button.grid(row=0, column=2, padx=2)

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
            # Record mode
            target = self.record_target_var.get()
            if target == "eyes":
                print("Starting new eye recording")
                self.timeline.clear_eye_data()
            elif target == "mouth":
                print("Starting new mouth recording")
                self.timeline.clear_mouth_data()
            elif target == "both":
                print("Starting new recording for both eyes and mouth")
                self.timeline.clear_eye_data()
                self.timeline.clear_mouth_data()

            self.is_playing = True
            self.is_recording = True

            # Start audio playback if loaded
            if self.audio_player.is_loaded():
                self.audio_player.play()
            else:
                # No audio, set recording start time
                self.recording_start_time = time.time()

            # Enable joystick control for the selected target
            self.eye_controller.joystick_enabled = target in ["eyes", "both"]
            self.mouth_controller.joystick_enabled = target in ["mouth", "both"]

            print("Recording started")
            self.status_var.set(f"Recording {target}")
        else:
            # Playback mode
            if self.is_paused:
                # Resume playback
                self.is_playing = True
                self.is_paused = False

                if self.audio_player.is_loaded():
                    self.audio_player.unpause()
                else:
                    # Adjust recording_start_time to account for elapsed_time
                    self.recording_start_time = time.time() - (self.elapsed_time / 1000)

                self.status_var.set("Resuming playback")
            else:
                # Start playback from beginning
                has_recording = (
                    len(self.timeline.eye_data) > 0 or len(self.timeline.mouth_data) > 0
                )
                print(
                    f"Attempting playback with {len(self.timeline.eye_data)} eye frames and {len(self.timeline.mouth_data)} mouth frames"
                )

                if not has_recording and not self.audio_player.is_loaded():
                    messagebox.showwarning("Warning", "No recording or audio to play")
                    return

                # Start playback
                self.is_playing = True
                self.is_recording = False
                self.is_paused = False
                self.elapsed_time = 0  # Reset elapsed time

                # Disable joystick during playback
                self.eye_controller.joystick_enabled = False
                self.mouth_controller.joystick_enabled = False
                print("Disabled joystick for playback")

                if self.audio_player.is_loaded():
                    self.audio_player.play()
                else:
                    # No audio, set recording start time
                    self.recording_start_time = time.time()

                self.status_var.set("Playing back recording")

        self.update_button_states()

    def update_button_states(self):
        """Update button states based on current playback/recording state"""
        if self.is_playing:
            self.play_record_button.config(state="disabled")
            self.pause_button.config(state="normal")
            self.stop_button.config(state="normal")
        else:
            self.play_record_button.config(state="normal")
            self.pause_button.config(state="disabled")
            if self.is_paused:
                self.stop_button.config(state="normal")
            else:
                self.stop_button.config(state="disabled")

    def pause(self):
        if self.audio_player.is_loaded():
            self.audio_player.pause()
        self.is_playing = False
        self.is_paused = True
        self.elapsed_time = self.current_time
        self.status_var.set("Paused")
        self.update_button_states()

    def stop(self):
        print("Stopping playback")
        if self.audio_player.is_loaded():
            self.audio_player.stop()
        self.is_playing = False
        self.is_recording = False
        self.is_paused = False
        self.elapsed_time = 0
        self.current_time = 0  # Reset current_time
        # Re-enable joystick when stopping
        self.eye_controller.joystick_enabled = True
        self.mouth_controller.joystick_enabled = True  # Add this line
        self.timeline.update_time_marker(0)
        self.status_var.set("Stopped")
        self.update_button_states()

    def update_gui(self):
        """Update GUI state and timeline"""
        if self.is_playing:
            if self.audio_player.is_loaded():
                # Get current time from audio player
                self.current_time = self.audio_player.get_position()
                # Check if audio has finished playing
                if (
                    not self.audio_player.is_playing()
                    or self.current_time >= self.audio_player.get_duration()
                ):
                    print("Audio playback finished")
                    self.stop()
                    self.update_button_states()  # Make sure buttons update
            else:
                # If no audio is loaded, use time elapsed since playback started
                current_time_ms = (time.time() - self.recording_start_time) * 1000
                self.current_time = int(current_time_ms)

                # Check if we've reached the end of our recorded data
                max_time = 0
                if self.timeline.eye_data:
                    max_time = max(max_time, self.timeline.eye_data[-1][0])
                if self.timeline.mouth_data:
                    max_time = max(max_time, self.timeline.mouth_data[-1][0])

                # Add a small buffer to max_time to ensure we catch the end
                if max_time > 0 and self.current_time >= (
                    max_time + 100
                ):  # 100ms buffer
                    print("Reached end of recorded data")
                    self.stop()
                    self.update_button_states()  # Make sure buttons update

        elif self.is_paused:
            # Keep current_time as is during pause
            pass
        else:
            self.current_time = 0

        # Always update timeline marker
        self.timeline.update_time_marker(self.current_time)

        # Handle playback/recording states
        if self.is_playing:
            if self.is_recording:
                target = self.record_target_var.get()
                if target == "eyes":
                    self.record_eye_data()
                elif target == "mouth":
                    self.record_mouth_data()
                elif target == "both":
                    self.record_eye_data()
                    self.record_mouth_data()
            else:
                self.playback_movements()

        # Schedule the next update (~60fps)
        self.root.after(16, self.update_gui)

    def record_eye_data(self):
        """Record eye movement data"""
        print(
            f"Recording eye frame at {self.current_time}ms:",
            f"X: {self.eye_controller.current_eye_x:.3f}",
            f"Y: {self.eye_controller.current_eye_y:.3f}",
        )
        self.timeline.add_eye_data_point(
            self.current_time,
            self.eye_controller.current_eye_x,
            self.eye_controller.current_eye_y,
            self.eye_controller.prev_button_states["BTN_WEST"] == 1,
            self.eye_controller.prev_button_states["BTN_EAST"] == 1,
            self.eye_controller.prev_button_states["BTN_SOUTH"] == 1,
        )

    def record_mouth_data(self):
        """Record mouth movement data"""
        print(
            f"Recording mouth frame at {self.current_time}ms:",
            f"Position: {self.mouth_controller.current_mouth_position}",
        )
        self.timeline.add_mouth_data_point(
            self.current_time,
            self.mouth_controller.current_mouth_position,
        )
        print(f"Added mouth data point at {self.current_time}ms")

    def playback_movements(self):
        """Playback recorded movements"""
        if len(self.timeline.eye_data) > 0:
            print(f"Playback: Applying eye movements at {self.current_time}ms")
            self.apply_recorded_movements(self.current_time)
        if len(self.timeline.mouth_data) > 0:
            print(f"Playback: Applying mouth movements at {self.current_time}ms")
            self.apply_recorded_mouth_movements(self.current_time)

    def apply_recorded_movements(self, current_time):
        """Apply recorded eye movements during playback"""
        self.eye_controller.apply_recorded_movement(
            current_time, self.timeline.eye_data
        )

    def apply_recorded_mouth_movements(self, current_time):
        """Apply recorded mouth movements during playback"""
        self.mouth_controller.apply_recorded_movement(
            current_time, self.timeline.mouth_data
        )

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

        self.joystick_controller.cleanup()
        self.eye_controller.cleanup()
        self.mouth_controller.cleanup()
        pygame.quit()
        self.root.quit()


def main():
    root = tk.Tk()
    app = AnimationControlGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_exit)
    root.mainloop()


if __name__ == "__main__":
    main()
