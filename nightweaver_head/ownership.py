"""Process exclusivity shared by service and the explicit maintenance CLI."""
import fcntl
import os


class OutputLock:
    def __init__(self, path='/run/pi-eyes-head/output.lock'):
        self.fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.fd)
            raise ValueError('local playback output already owned') from None

    def close(self):
        os.close(self.fd)
