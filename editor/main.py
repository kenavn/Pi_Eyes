import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pygame
from datetime import datetime, timedelta
import time
import csv
import tempfile  # Add this
import os  # Add this
from timeline_widget import TimelineCanvas
from audio_player import AudioPlayer
from eye_controller import EyeController
from mouth_controller import MouthController
from joystick_controller import JoystickController
from settings_dialog import SettingsDialog
from settings import Settings
from animation_protocol import FileFormat

NM_FILE = "File"
NM_BUNDLE_SAVE = "Save Animation Bundle ..."
NM_BUNDLE_LOAD = "Load Animation Bundle ..."
NM_BUNDLE_NEW = "New Animation"
NM_REC = "Recording"
NM_REC_SAVE = "Save CSV Recording ..."
NM_REC_LOAD = "Load CSV Recording ..."
NM_AUDIO_LOAD = "Load Audio ..."
NM_AUDIO_SAVE = "Save Audio ..."
NM_SETTINGS = "Settings ..."
NM_REC_EYE_RESET = "Reset Eye Recording"
NM_REC_MOUTH_RESET = "Reset Mouth Recording"
NM_REC_ALL_RESET = "Reset All Recordings"
NM_EXIT = "Exit"
LBL_WINDOW = "Animatronics Studio"


class AnimationControlGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(LBL_WINDOW)

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
        """Set up the GUI with stable layout"""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Create menu
        self.create_menu()

        # Create main control section
        self.create_audio_controls(main_frame)

        # Create timeline frame container
        timeline_frame = ttk.Frame(main_frame)
        timeline_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        timeline_frame.grid_propagate(False)  # Prevent automatic resizing
        timeline_frame.configure(height=400)  # Set fixed height

        # Create timeline with fixed dimensions
        self.timeline = TimelineCanvas(timeline_frame, height=400, width=800)
        self.timeline.grid(row=0, column=0, sticky=(tk.W, tk.E))

        # Configure timeline frame grid
        timeline_frame.columnconfigure(0, weight=1)
        timeline_frame.rowconfigure(0, weight=0)  # Don't allow vertical expansion

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

        # Set minimum window size
        self.root.minsize(800, 600)

        # Start update loop
        self.update_gui()

    def create_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File menu
        self.file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=NM_FILE, menu=self.file_menu)

        # Artifacts submenu
        self.file_menu.add_command(label=NM_AUDIO_LOAD, command=self.load_audio)
        self.file_menu.add_separator()
        self.file_menu.add_command(label=NM_REC_LOAD, command=self.load_recording)
        self.file_menu.add_command(
            label=NM_REC_SAVE,
            command=self.save_recording,
            state="disabled",
        )

        # Animation submenu
        self.file_menu.add_separator()
        self.file_menu.add_command(label=NM_BUNDLE_NEW, command=self.new_animation)
        self.file_menu.add_command(label=NM_BUNDLE_LOAD, command=self.load_bundle)
        self.file_menu.add_command(
            label=NM_BUNDLE_SAVE, command=self.save_bundle, state="disabled"
        )

        self.file_menu.add_separator()
        self.file_menu.add_command(label=NM_SETTINGS, command=self.show_settings)
        self.file_menu.add_separator()
        self.file_menu.add_command(label=NM_EXIT, command=self.on_exit)

        # Recording menu
        self.edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label=NM_REC, menu=self.edit_menu)
        self.edit_menu.add_command(
            label=NM_REC_EYE_RESET, command=self.clear_eye_track, state="disabled"
        )
        self.edit_menu.add_command(
            label=NM_REC_MOUTH_RESET,
            command=self.clear_mouth_track,
            state="disabled",
        )
        self.edit_menu.add_command(
            label=NM_REC_ALL_RESET,
            command=self.clear_all_tracks,
            state="disabled",
        )

    def create_audio_controls(self, parent):
        audio_frame = ttk.LabelFrame(parent, text="Audio Controls", padding="5")
        audio_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        # Audio file controls
        ttk.Button(audio_frame, text="Load Audio", command=self.load_audio).grid(
            row=0, column=0, padx=5
        )
        self.audio_label = ttk.Label(audio_frame, text="No audio loaded")
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

    def new_animation(self):
        """Clear all current animation data and audio"""
        if self.timeline.eye_data or self.timeline.mouth_data:
            if not messagebox.askyesno(
                "New Animation", "This will clear all current animation data. Continue?"
            ):
                return

        self.timeline.clear_eye_data()
        self.timeline.clear_mouth_data()
        self.audio_player.unload()
        self.audio_label.config(text="No audio loaded")
        self.timeline.clear_audio_data()
        self.update_menu_states()
        self.status_var.set("New animation started")

    def save_bundle(self):
        """Save animation as a bundle including audio if present"""
        if not self.timeline.eye_data and not self.timeline.mouth_data:
            messagebox.showwarning("No Data", "No animation data available to save.")
            return

        # Get filename from user
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = filedialog.asksaveasfilename(
            initialfile=f"animation_bundle_{timestamp}",
            defaultextension=FileFormat.BUNDLE_EXTENSION,
            filetypes=[
                (f"Animation Bundle", f"*{FileFormat.BUNDLE_EXTENSION}"),
                ("All files", "*.*"),
            ],
        )

        if not filename:
            return

        try:
            # Get current audio file path if audio is loaded
            audio_path = (
                self.audio_player.get_current_file()
                if self.audio_player.is_loaded()
                else None
            )

            if self.audio_player.is_loaded() and not audio_path:
                messagebox.showwarning(
                    "Audio File Missing",
                    "Audio is loaded but the file path is not available. "
                    "Audio will not be included in the bundle.",
                )

            # Save bundle
            if FileFormat.save_bundle(
                filename, audio_path, self.timeline.eye_data, self.timeline.mouth_data
            ):
                messagebox.showinfo("Success", f"Animation bundle saved to {filename}")
                self.status_var.set(f"Animation bundle saved to {filename}")
            else:
                messagebox.showerror("Error", "Failed to save animation bundle")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save bundle: {str(e)}")
            print(f"Error details: {e}")

    def load_bundle(self):
        """Load an animation bundle"""
        filename = filedialog.askopenfilename(
            filetypes=[
                (f"Animation Bundle", f"*{FileFormat.BUNDLE_EXTENSION}"),
                ("All files", "*.*"),
            ],
            title="Load Animation Bundle",
        )

        if not filename:
            return

        try:
            # Load the bundle
            bundle = FileFormat.load_bundle(filename)
            if not bundle:
                raise ValueError("Failed to load animation bundle")

            # Clear existing data
            self.timeline.clear_eye_data()
            self.timeline.clear_mouth_data()
            self.audio_player.unload()

            # If bundle has audio, save it to temp file and load it
            if bundle.audio_data:
                audio_ext = bundle.metadata.get("audio_format", "wav")
                with tempfile.NamedTemporaryFile(
                    suffix=f".{audio_ext}", delete=False
                ) as temp_file:
                    temp_file.write(bundle.audio_data)
                    temp_path = temp_file.name

                if self.audio_player.load_file(temp_path):
                    self.audio_label.config(text=bundle.audio_file or "Bundled audio")
                    duration_ms = self.audio_player.get_duration()
                    self.timeline.set_audio_duration(duration_ms)
                    self.timeline.load_audio_file(temp_path)

                # Clean up temp file
                try:
                    os.remove(temp_path)
                except Exception as e:
                    print(f"Warning: Could not remove temporary audio file: {e}")

            # Load animation data
            for frame in bundle.eye_frames:
                self.timeline.add_eye_data_point(
                    frame.time_ms,
                    frame.x,
                    frame.y,
                    frame.left_closed,
                    frame.right_closed,
                    frame.both_closed,
                )

            for frame in bundle.mouth_frames:
                self.timeline.add_mouth_data_point(frame.time_ms, frame.position)

            # Update UI
            self.timeline.update_time_marker(0)
            self.update_menu_states()

            # Update status
            total_frames = len(bundle.eye_frames) + len(bundle.mouth_frames)
            max_time = max(
                (
                    [frame.time_ms for frame in bundle.eye_frames]
                    + [frame.time_ms for frame in bundle.mouth_frames]
                ),
                default=0,
            )

            self.status_var.set(
                f"Loaded {total_frames} frames ({max_time/1000:.1f} seconds) from bundle"
            )

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load bundle: {str(e)}")
            print(f"Error details: {e}")

    def load_audio(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("Audio files", "*.wav *.mp3"), ("All files", "*.*")]
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

    def update_menu_states(self):
        """Update the state of menu items based on recording presence"""
        has_eye_recording = len(self.timeline.eye_data) > 0
        has_mouth_recording = len(self.timeline.mouth_data) > 0
        has_any_recording = has_eye_recording or has_mouth_recording

        # Update eye recording reset button
        self.edit_menu.entryconfig(
            NM_REC_EYE_RESET, state="normal" if has_eye_recording else "disabled"
        )

        # Update mouth recording reset button
        self.edit_menu.entryconfig(
            NM_REC_MOUTH_RESET,
            state="normal" if has_mouth_recording else "disabled",
        )

        # Update reset all button
        self.edit_menu.entryconfig(
            NM_REC_ALL_RESET,
            state="normal" if has_any_recording else "disabled",
        )

        # Update save buttons
        self.file_menu.entryconfig(
            NM_BUNDLE_SAVE,
            state="normal" if has_any_recording else "disabled",
        )
        self.file_menu.entryconfig(
            NM_REC_SAVE,
            state="normal" if has_any_recording else "disabled",
        )

        print(f"Menu states updated - Has recordings: {has_any_recording}")

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

        if self.is_recording:
            self.record_on_play_var.set(False)  # Turn off the recording mode
            self.update_record_controls()  # Update controls

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
        self.update_menu_states()

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
        self.update_menu_states()  # Update menu states when recording

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
        self.update_menu_states()  # Update menu states when recording

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
        if messagebox.askyesno(
            "Reset Eye Recording",
            "Are you sure you want to reset the eye movement recording?",
        ):
            self.timeline.clear_eye_data()
            self.update_menu_states()
            self.status_var.set("Eye recording reset")

    def clear_mouth_track(self):
        if messagebox.askyesno(
            "Reset Mouth Recording",
            "Are you sure you want to reset the mouth movement recording?",
        ):
            self.timeline.clear_mouth_data()
            self.update_menu_states()
            self.status_var.set("Mouth recording reset")

    def clear_all_tracks(self):
        if messagebox.askyesno(
            "Reset All Recordings", "Are you sure you want to reset all recordings?"
        ):
            self.timeline.clear_eye_data()
            self.timeline.clear_mouth_data()
            self.update_menu_states()
            self.status_var.set("All recordings reset")

    def save_recording(self):
        """Save recorded eye and mouth movement data to a CSV file"""
        if not self.timeline.eye_data and not self.timeline.mouth_data:
            messagebox.showwarning("No Data", "No recording data available to save.")
            return

        # Get filename from user
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = filedialog.asksaveasfilename(
            initialfile=f"animation_recording_{timestamp}.csv",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )

        if not filename:
            return

        # Save using the protocol module
        if FileFormat.save_to_csv(
            filename, self.timeline.eye_data, self.timeline.mouth_data
        ):
            messagebox.showinfo("Success", f"Recording saved to {filename}")
            self.status_var.set(f"Recording saved to {filename}")
        else:
            messagebox.showerror("Error", "Failed to save recording")

    def load_recording(self):
        """Load a previously saved recording"""
        filename = filedialog.askopenfilename(
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Load Recording",
        )

        if not filename:
            return

        try:
            # Temporarily disable UI updates
            self.root.update_idletasks()

            # Clear existing recordings
            self.timeline.clear_eye_data()
            self.timeline.clear_mouth_data()

            # Load using the protocol module
            eye_frames, mouth_frames = FileFormat.load_from_csv(filename)

            # Convert to timeline format
            for frame in eye_frames:
                self.timeline.add_eye_data_point(
                    frame.time_ms,
                    frame.x,
                    frame.y,
                    frame.left_closed,
                    frame.right_closed,
                    frame.both_closed,
                )

            for frame in mouth_frames:
                self.timeline.add_mouth_data_point(frame.time_ms, frame.position)

            # Set timeline duration if needed
            max_time = max(
                (frame.time_ms for frame in eye_frames + mouth_frames), default=0
            )
            if max_time > self.timeline.duration_ms:
                self.timeline.set_audio_duration(max_time)

            # Force timeline to update its view
            self.timeline.update_time_marker(0)  # This will trigger a redraw

            # Update menu states
            self.update_menu_states()

            # Update status
            total_frames = len(eye_frames) + len(mouth_frames)
            self.status_var.set(
                f"Loaded {total_frames} frames ({max_time/1000:.1f} seconds) from {filename}"
            )

            # Re-enable UI updates
            self.root.update()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load recording: {str(e)}")
            print(f"Error details: {e}")

    def show_settings(self):
        """Show the settings dialog and update controllers if settings change"""
        # Store old settings for comparison
        old_settings = {
            "host": self.settings.get_setting("host"),
            "eye_port": self.settings.get_setting("eye_port"),
            "mouth_port": self.settings.get_setting("mouth_port"),
        }

        # Create and show settings dialog
        dialog = SettingsDialog(self.root, self.settings)
        self.root.wait_window(dialog.dialog)

        # Check if settings were changed
        if (
            old_settings["host"] != self.settings.get_setting("host")
            or old_settings["eye_port"] != self.settings.get_setting("eye_port")
            or old_settings["mouth_port"] != self.settings.get_setting("mouth_port")
        ):

            # Reinitialize controllers with new settings
            self.eye_controller.cleanup()
            self.mouth_controller.cleanup()

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

            messagebox.showinfo(
                "Settings Updated",
                "Controllers have been reinitialized with new settings.",
            )

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
