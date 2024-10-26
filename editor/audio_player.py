import pygame
import time
from pydub import AudioSegment


class AudioPlayer:
    def __init__(self):
        pygame.mixer.init()
        self.loaded = False
        self.duration = 0  # Duration in milliseconds
        self.start_time = None
        self.paused_time = 0  # Time elapsed before pausing
        self.current_file_path = None  # Add this to track the current file path

    def load_file(self, file_path):
        try:
            pygame.mixer.music.load(file_path)
            self.loaded = True
            # Use pydub to get accurate duration
            audio = AudioSegment.from_file(file_path)
            self.duration = len(audio)  # Duration in milliseconds
            self.current_file_path = file_path  # Store the file path
            return True
        except Exception as e:
            print(f"Error loading audio file: {e}")
            self.loaded = False
            self.current_file_path = None
            return False

    def play(self):
        if self.loaded:
            pygame.mixer.music.play()
            self.start_time = time.time() * 1000  # Record start time in milliseconds
            self.paused_time = 0

    def pause(self):
        if self.loaded:
            pygame.mixer.music.pause()
            if self.start_time:
                # Calculate time elapsed until pause
                self.paused_time += time.time() * 1000 - self.start_time
                self.start_time = None

    def unpause(self):
        if self.loaded:
            pygame.mixer.music.unpause()
            if not self.start_time:
                self.start_time = time.time() * 1000  # Record new start time

    def stop(self):
        if self.loaded:
            pygame.mixer.music.stop()
        self.start_time = None
        self.paused_time = 0

    def unload(self):
        """Unload the current audio file"""
        if self.loaded:
            pygame.mixer.music.unload()
            self.loaded = False
            self.duration = 0
            self.start_time = None
            self.paused_time = 0
            self.current_file_path = None

    def get_current_file(self):
        """Get the path of the currently loaded audio file"""
        return self.current_file_path

    def is_loaded(self):
        return self.loaded

    def is_playing(self):
        return pygame.mixer.music.get_busy()

    def get_position(self):
        if self.loaded:
            if self.start_time:
                # Calculate current position
                current_time = time.time() * 1000
                position = self.paused_time + (current_time - self.start_time)
                if position > self.duration:
                    return self.duration
                return position
            else:
                return self.paused_time
        else:
            return 0

    def get_duration(self):
        return self.duration
