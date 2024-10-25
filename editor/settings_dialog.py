# settings_dialog.py
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox


class SettingsDialog:
    def __init__(self, parent, settings):
        self.settings = settings
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Settings")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # Make dialog modal
        self.dialog.protocol("WM_DELETE_WINDOW", self.on_cancel)

        self.create_widgets()

        # Center the dialog
        self.center_dialog()

    def create_widgets(self):
        # Create main frame with padding
        main_frame = ttk.Frame(self.dialog, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Host settings
        ttk.Label(main_frame, text="Remote Host:").grid(
            row=0, column=0, sticky=tk.W, pady=5
        )
        self.host_var = tk.StringVar(value=self.settings.get_setting("host"))
        self.host_entry = ttk.Entry(main_frame, textvariable=self.host_var, width=30)
        self.host_entry.grid(row=0, column=1, padx=5, pady=5)

        # Eye port settings
        ttk.Label(main_frame, text="Eye Port:").grid(
            row=1, column=0, sticky=tk.W, pady=5
        )
        self.eye_port_var = tk.StringVar(
            value=str(self.settings.get_setting("eye_port"))
        )
        self.eye_port_entry = ttk.Entry(
            main_frame, textvariable=self.eye_port_var, width=10
        )
        self.eye_port_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)

        # Mouth port settings
        ttk.Label(main_frame, text="Mouth Port:").grid(
            row=2, column=0, sticky=tk.W, pady=5
        )
        self.mouth_port_var = tk.StringVar(
            value=str(self.settings.get_setting("mouth_port"))
        )
        self.mouth_port_entry = ttk.Entry(
            main_frame, textvariable=self.mouth_port_var, width=10
        )
        self.mouth_port_entry.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=3, column=0, columnspan=2, pady=10)

        ttk.Button(button_frame, text="Save", command=self.on_save).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(button_frame, text="Cancel", command=self.on_cancel).pack(
            side=tk.LEFT, padx=5
        )

    def validate_settings(self):
        try:
            # Validate ports are integers
            eye_port = int(self.eye_port_var.get())
            mouth_port = int(self.mouth_port_var.get())

            # Validate port range
            if not (1024 <= eye_port <= 65535 and 1024 <= mouth_port <= 65535):
                raise ValueError("Ports must be between 1024 and 65535")

            # Validate host format (basic check)
            host = self.host_var.get().strip()
            if not host:
                raise ValueError("Host cannot be empty")

            return True
        except ValueError as e:
            messagebox.showerror("Validation Error", str(e))
            return False

    def on_save(self):
        if self.validate_settings():
            self.settings.update_setting("host", self.host_var.get().strip())
            self.settings.update_setting("eye_port", int(self.eye_port_var.get()))
            self.settings.update_setting("mouth_port", int(self.mouth_port_var.get()))
            self.dialog.destroy()

    def on_cancel(self):
        self.dialog.destroy()

    def center_dialog(self):
        self.dialog.update_idletasks()
        width = self.dialog.winfo_width()
        height = self.dialog.winfo_height()
        x = (self.dialog.winfo_screenwidth() // 2) - (width // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (height // 2)
        self.dialog.geometry(f"{width}x{height}+{x}+{y}")
