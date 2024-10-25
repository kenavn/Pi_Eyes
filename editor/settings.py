# settings.py
import json
import os


class Settings:
    def __init__(self):
        self.config_file = "animation_control_settings.json"
        self.default_settings = {
            "host": "127.0.0.1",
            "eye_port": 5005,
            "mouth_port": 5006,
        }
        self.current_settings = {}
        self.load_settings()

    def load_settings(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r") as f:
                    self.current_settings = json.load(f)
            else:
                self.current_settings = self.default_settings.copy()
                self.save_settings()
        except Exception as e:
            print(f"Error loading settings: {e}")
            self.current_settings = self.default_settings.copy()

    def save_settings(self):
        try:
            with open(self.config_file, "w") as f:
                json.dump(self.current_settings, f, indent=4)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def get_setting(self, key):
        return self.current_settings.get(key, self.default_settings.get(key))

    def update_setting(self, key, value):
        self.current_settings[key] = value
        self.save_settings()
