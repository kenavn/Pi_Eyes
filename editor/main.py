# main.py
import tkinter as tk
from tkinter import ttk, filedialog
import pygame
import time
from audio_player import AudioPlayer
from eye_controller import EyeController
from mouth_controller import MouthController
import threading
from settings import Settings
from settings_dialog import SettingsDialog


class AnimationControlGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Animation Control Studio")

        # Load settings
        self.settings = Settings()

        # Initialize pygame mixer
        pygame.init()

        # Initialize controllers with settings
        self.audio_player = AudioPlayer()
        self.eye_controller = EyeController(
            self.settings.get_setting("host"), self.settings.get_setting("eye_port")
        )
        self.mouth_controller = MouthController(
            self.settings.get_setting("host"), self.settings.get_setting("mouth_port")
        )

        self.setup_gui()
        self.recording = False
        self.current_time = 0

    def setup_gui(self):
        # Add menu bar
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Settings", command=self.show_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_exit)

        # Main container with padding
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Audio control section
        audio_frame = ttk.LabelFrame(main_frame, text="Audio Control", padding="5")
        audio_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        ttk.Button(audio_frame, text="Load Audio", command=self.load_audio).grid(
            row=0, column=0, padx=5
        )
        self.audio_path_label = ttk.Label(audio_frame, text="No file selected")
        self.audio_path_label.grid(row=0, column=1, sticky=tk.W)

        # Timeline frame
        timeline_frame = ttk.Frame(main_frame)
        timeline_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        # Create timeline canvas
        self.timeline_canvas = tk.Canvas(timeline_frame, height=100, bg="white")
        self.timeline_canvas.grid(row=0, column=0, sticky=(tk.W, tk.E))
        timeline_frame.columnconfigure(0, weight=1)

        # Time marker
        self.time_marker = self.timeline_canvas.create_line(
            0, 0, 0, 100, fill="red", width=2
        )

        # Control buttons frame
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=2, column=0, columnspan=2, pady=5)

        ttk.Button(control_frame, text="▶", command=self.play).grid(
            row=0, column=0, padx=2
        )
        ttk.Button(control_frame, text="⏸", command=self.pause).grid(
            row=0, column=1, padx=2
        )
        ttk.Button(control_frame, text="⏹", command=self.stop).grid(
            row=0, column=2, padx=2
        )

        # Recording controls
        record_frame = ttk.Frame(main_frame)
        record_frame.grid(row=3, column=0, columnspan=2, pady=5)

        self.record_button = ttk.Button(
            record_frame, text="Record Eyes", command=self.toggle_eye_recording
        )
        self.record_button.grid(row=0, column=0, padx=5)

        self.record_mouth_button = ttk.Button(
            record_frame, text="Record Mouth", command=self.toggle_mouth_recording
        )
        self.record_mouth_button.grid(row=0, column=1, padx=5)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_label = ttk.Label(main_frame, textvariable=self.status_var)
        status_label.grid(row=4, column=0, columnspan=2, pady=5)

        # Recording controls
        record_frame = ttk.Frame(main_frame)
        record_frame.grid(row=3, column=0, columnspan=2, pady=5)

        self.record_button = ttk.Button(
            record_frame, text="Record", command=self.toggle_recording
        )
        self.record_button.grid(row=0, column=0, padx=5)

        self.save_button = ttk.Button(
            record_frame,
            text="Save Recording",
            command=self.save_recording,
            state="disabled",
        )
        self.save_button.grid(row=0, column=1, padx=5)

        self.clear_button = ttk.Button(
            record_frame,
            text="Clear Recording",
            command=self.clear_recording,
            state="disabled",
        )
        self.clear_button.grid(row=0, column=2, padx=5)

        # Configure main window to be resizable
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        # Start update loop
        self.update_timeline()

    def load_audio(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("Wave files", "*.wav"), ("All files", "*.*")]
        )
        if file_path:
            if self.audio_player.load_file(file_path):
                self.audio_path_label.config(text=file_path.split("/")[-1])
                self.status_var.set("Audio loaded")
            else:
                self.status_var.set("Error loading audio file")

    def play(self):
        if self.audio_player.is_loaded():
            self.audio_player.play()
            self.status_var.set("Playing")

    def pause(self):
        self.audio_player.pause()
        self.status_var.set("Paused")

    def stop(self):
        self.audio_player.stop()
        self.status_var.set("Stopped")

    def toggle_eye_recording(self):
        if not self.recording:
            self.eye_controller.start_recording()
            self.record_button.config(text="Stop Recording")
            self.recording = True
            self.status_var.set("Recording eye movements")
        else:
            self.eye_controller.stop_recording()
            self.record_button.config(text="Record Eyes")
            self.recording = False
            self.status_var.set("Eye recording stopped")

    def toggle_mouth_recording(self):
        # Will be implemented later
        pass

    def toggle_recording(self):
        if not self.recording:
            self.eye_controller.start_recording()
            self.record_button.config(text="Stop Recording")
            self.save_button.config(state="disabled")
            self.clear_button.config(state="disabled")
            self.recording = True
            self.status_var.set("Recording eye movements")
        else:
            self.eye_controller.stop_recording()
            self.record_button.config(text="Record")
            self.save_button.config(state="normal")
            self.clear_button.config(state="normal")
            self.recording = False
            self.status_var.set("Recording stopped")

    def save_recording(self):
        if not self.eye_controller.recorded_data:
            messagebox.showwarning("No Data", "No recording data to save")
            return

        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=f"eye_recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )

        if filename:
            if self.eye_controller.save_recording(filename):
                self.status_var.set(f"Recording saved to {filename}")
            else:
                messagebox.showerror("Save Error", "Failed to save recording")

    def clear_recording(self):
        if messagebox.askyesno(
            "Clear Recording", "Are you sure you want to clear the current recording?"
        ):
            self.eye_controller.clear_recording()
            self.save_button.config(state="disabled")
            self.clear_button.config(state="disabled")
            self.status_var.set("Recording cleared")

    def update_timeline(self):
        if self.audio_player.is_playing():
            current_time = self.audio_player.get_position()
            timeline_width = self.timeline_canvas.winfo_width()
            duration = self.audio_player.get_duration()
            if duration > 0:
                x_pos = (current_time / duration) * timeline_width
                self.timeline_canvas.coords(self.time_marker, x_pos, 0, x_pos, 100)

        self.root.after(
            33, self.update_timeline
        )  # Update approximately 30 times per second

    def cleanup(self):
        self.eye_controller.cleanup()
        pygame.quit()

    def show_settings(self):
        dialog = SettingsDialog(self.root, self.settings)
        self.root.wait_window(dialog.dialog)

        # Reconnect controllers with new settings
        self.reconnect_controllers()

    def reconnect_controllers(self):
        # Cleanup existing connections
        self.eye_controller.cleanup()

        # Reinitialize with new settings
        self.eye_controller = EyeController(
            self.settings.get_setting("host"), self.settings.get_setting("eye_port")
        )
        self.mouth_controller = MouthController(
            self.settings.get_setting("host"), self.settings.get_setting("mouth_port")
        )

    def on_exit(self):
        self.cleanup()
        self.root.quit()


def main():
    root = tk.Tk()
    app = AnimationControlGUI(root)
    root.protocol("WM_DELETE_WINDOW", lambda: app.on_exit())
    root.mainloop()


if __name__ == "__main__":
    main()
