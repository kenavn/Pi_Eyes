# audio_player.py
from pygame import mixer
import threading
import time


class AudioPlayer:
    def __init__(self):
        self.audio_file = None
        self.playing = False
        self.paused = False
        self.current_position = 0
        self.duration = 0
        mixer.init()

    def load_file(self, file_path):
        try:
            mixer.music.load(file_path)
            self.audio_file = file_path
            # Get audio duration (this is approximate with pygame)
            sound = mixer.Sound(file_path)
            self.duration = sound.get_length() * 1000  # Convert to milliseconds
            del sound  # Clean up the Sound object
            return True
        except Exception as e:
            print(f"Error loading audio file: {e}")
            return False

    def play(self):
        if self.audio_file:
            if self.paused:
                mixer.music.unpause()
                self.paused = False
            else:
                mixer.music.play()
            self.playing = True

    def pause(self):
        if self.playing:
            mixer.music.pause()
            self.playing = False
            self.paused = True

    def stop(self):
        mixer.music.stop()
        self.playing = False
        self.paused = False
        self.current_position = 0

    def get_position(self):
        if self.playing:
            return mixer.music.get_pos()
        return self.current_position

    def get_duration(self):
        return self.duration

    def is_playing(self):
        return self.playing

    def is_loaded(self):
        return self.audio_file is not None
