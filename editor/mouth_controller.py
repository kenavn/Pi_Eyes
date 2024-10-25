# mouth_controller.py
import socket
import threading
import csv
from datetime import datetime
import queue


class MouthController:
    def __init__(self, ip, port):
        self.UDP_IP = ip
        self.UDP_PORT = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.record_queue = queue.Queue()
        self.disk_writer_thread = None
        self.recording_start_time = None

        self.current_mouth_open = 0  # 0
