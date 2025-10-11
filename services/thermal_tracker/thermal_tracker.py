#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Thermal Eye Tracker for Pi_Eyes

Uses the Adafruit AMG8833 IR Thermal Camera to track heat sources 
and automatically direct eye gaze toward the hottest area.

This service reads thermal data, calculates a temperature-weighted centroid,
and sends eye position commands to the existing eyes UDP service.
"""

import socket
import struct
import time
import argparse
import threading
import signal
import sys
import json
from datetime import datetime

try:
    from amg8833_simple import AMG8833Simple
    AMG8833_AVAILABLE = True
except ImportError:
    AMG8833_AVAILABLE = False
    print("Warning: AMG8833 simple interface not available. Running in simulation mode.")


class ThermalTracker:
    def __init__(self, eye_host='127.0.0.1', eye_port=5005, thermal_port=5007,
                 update_rate=5.0, sensitivity=5.0, debug=False, position_threshold=0.05,
                 smoothing=0.7):
        """
        Initialize the thermal tracker.

        Args:
            eye_host: IP address of the eye controller
            eye_port: UDP port of the eye controller (default 5005)
            thermal_port: UDP port for thermal tracker status/config (default 5007)
            update_rate: Updates per second (default 5.0 Hz)
            sensitivity: Thermal sensitivity multiplier (default 5.0)
            debug: Enable debug output
            position_threshold: Minimum position change to trigger update (default 0.05)
            smoothing: Smoothing factor for position (0.0=no smoothing, 0.9=heavy smoothing, default 0.7)
        """
        self.eye_host = eye_host
        self.eye_port = eye_port
        self.thermal_port = thermal_port
        self.update_rate = update_rate
        self.sensitivity = sensitivity
        self.debug = debug
        self.position_threshold = position_threshold
        self.smoothing = smoothing

        # Thermal sensor
        self.sensor = None
        self.running = False

        # UDP sockets
        self.eye_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.status_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.status_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Tracking state
        self.current_x = 0.0
        self.current_y = 0.0
        self.smoothed_x = 0.0
        self.smoothed_y = 0.0
        self.last_sent_x = 0.0
        self.last_sent_y = 0.0
        self.magnitude = 0.0
        self.last_update = time.time()
        self.tracking_active = False

        # Threading
        self.sensor_thread = None
        self.status_thread = None
        
    def initialize_sensor(self):
        """Initialize the AMG8833 thermal sensor."""
        if not AMG8833_AVAILABLE:
            print("AMG8833 not available - running in simulation mode")
            return False
            
        try:
            # Initialize AMG8833 with simple interface
            self.sensor = AMG8833Simple()
            
            # Wait for sensor to stabilize
            time.sleep(1)
            
            print(f"AMG8833 thermal sensor initialized")
            return True
            
        except Exception as e:
            print(f"Error initializing AMG8833: {e}")
            return False
    
    def calculate_gaze_direction(self, pixels):
        """
        Calculate gaze direction from thermal pixels using temperature-weighted centroid.
        
        Based on the algorithm:
        - Weight each pixel position by its temperature
        - Calculate centroid of heat sources
        - Scale to -1.0 to 1.0 range for eye positioning
        
        Args:
            pixels: 64-element array of thermal pixel temperatures
            
        Returns:
            tuple: (x, y, magnitude) where x,y are -1.0 to 1.0, magnitude is heat intensity
        """
        if len(pixels) != 64:
            raise ValueError("Expected 64 thermal pixels")
        
        x, y, magnitude = 0.0, 0.0, 0.0
        min_val, max_val = 100.0, 0.0
        
        i = 0
        # AMG8833 is 8x8 grid, iterate through positions
        for y_pos in [3.5, 2.5, 1.5, 0.5, -0.5, -1.5, -2.5, -3.5]:  # 8 rows
            for x_pos in [3.5, 2.5, 1.5, 0.5, -0.5, -1.5, -2.5, -3.5]:  # 8 cols
                pixel_temp = pixels[i]
                
                # Weight position by temperature
                x += x_pos * pixel_temp
                y += y_pos * pixel_temp
                
                # Track temperature range
                min_val = min(min_val, pixel_temp)
                max_val = max(max_val, pixel_temp)
                
                i += 1
        
        # Scale output to desired ranges
        # Divide by total pixels (64) and sensitivity factor
        # Invert both axes to match expected eye movement direction
        x = x / 64.0 / self.sensitivity  # Remove the negative sign (was -x)
        y = -y / 64.0 / self.sensitivity  # Add negative sign (was y)
        
        # Clamp to valid eye movement range
        x = max(-1.0, min(1.0, x))
        y = max(-1.0, min(1.0, y))
        
        # Calculate magnitude (heat intensity above baseline)
        magnitude = max(0, min(50, max_val - 20))
        
        return x, y, magnitude
    
    def send_eye_position(self, x, y):
        """
        Send eye position command to the eye controller.
        
        Args:
            x, y: Eye position from -1.0 to 1.0
        """
        try:
            # Convert -1.0 to 1.0 range to 0-255 byte range
            x_byte = int((x + 1.0) * 127.5)  # Map -1.0:1.0 to 0:255
            y_byte = int((y + 1.0) * 127.5)
            
            # Clamp to byte range
            x_byte = max(0, min(255, x_byte))
            y_byte = max(0, min(255, y_byte))
            
            # Send eye position command (0x20 + x_byte + y_byte)
            message = b'\x20' + struct.pack('BB', x_byte, y_byte)
            self.eye_sock.sendto(message, (self.eye_host, self.eye_port))
            
            if self.debug:
                print(f"Sent eye position: x={x:.3f} ({x_byte}), y={y:.3f} ({y_byte})")
                
        except Exception as e:
            print(f"Error sending eye position: {e}")
    
    def connect_controller(self):
        """Tell Pi_Eyes that a controller (thermal tracker) is connected."""
        try:
            message = b'\x01'  # joystick_connected
            self.eye_sock.sendto(message, (self.eye_host, self.eye_port))
            if self.debug:
                print("Sent controller connected - disabling auto movement")
        except Exception as e:
            print(f"Error sending controller connected: {e}")
    
    def disconnect_controller(self):
        """Tell Pi_Eyes that the controller (thermal tracker) is disconnected."""
        try:
            message = b'\x00'  # joystick_disconnected
            self.eye_sock.sendto(message, (self.eye_host, self.eye_port))
            if self.debug:
                print("Sent controller disconnected - enabling auto movement")
        except Exception as e:
            print(f"Error sending controller disconnected: {e}")
    
    def get_thermal_pixels(self):
        """
        Read thermal pixel data from sensor or simulate data.
        
        Returns:
            list: 64 thermal pixel temperatures
        """
        if self.sensor:
            try:
                return self.sensor.pixels
            except Exception as e:
                print(f"Error reading thermal sensor: {e}")
                return None  # Return None to indicate sensor failure
        else:
            return self.simulate_thermal_data()
    
    def simulate_thermal_data(self):
        """Generate simulated thermal data for testing."""
        import math
        
        # Simulate a moving heat source
        t = time.time() * 0.5  # Slow movement
        center_x = 3 + 2 * math.sin(t)  # X position 1-5
        center_y = 3 + 2 * math.cos(t)  # Y position 1-5
        
        pixels = []
        for row in range(8):
            for col in range(8):
                # Distance from simulated heat source
                dist = math.sqrt((col - center_x)**2 + (row - center_y)**2)
                # Temperature falls off with distance
                temp = 25 + 10 * math.exp(-dist * 0.8)
                pixels.append(temp)
        
        return pixels
    
    def sensor_loop(self):
        """Main sensor reading and eye tracking loop."""
        print(f"Starting thermal tracking at {self.update_rate} Hz")
        
        sleep_time = 1.0 / self.update_rate
        
        while self.running:
            start_time = time.time()
            
            try:
                # Read thermal data
                pixels = self.get_thermal_pixels()
                
                # Only process if we have valid sensor data
                if pixels is not None:
                    # Calculate gaze direction
                    x, y, magnitude = self.calculate_gaze_direction(pixels)
                    
                    # Use thermal tracking if significant heat detected
                    if magnitude > 2.0:  # Threshold for person detection
                        # Apply exponential smoothing to reduce jitter
                        # smoothed = old * smoothing + new * (1 - smoothing)
                        if not hasattr(self, 'tracking_active') or not self.tracking_active:
                            # First tracking frame - initialize smoothed values
                            self.smoothed_x = x
                            self.smoothed_y = y
                            self.connect_controller()
                            self.tracking_active = True
                            # Force initial position update
                            self.last_sent_x = x
                            self.last_sent_y = y
                            self.send_eye_position(x, y)
                        else:
                            # Apply smoothing filter
                            self.smoothed_x = self.smoothed_x * self.smoothing + x * (1.0 - self.smoothing)
                            self.smoothed_y = self.smoothed_y * self.smoothing + y * (1.0 - self.smoothing)

                            # Only send update if smoothed position changed significantly
                            dx = abs(self.smoothed_x - self.last_sent_x)
                            dy = abs(self.smoothed_y - self.last_sent_y)
                            if dx >= self.position_threshold or dy >= self.position_threshold:
                                self.last_sent_x = self.smoothed_x
                                self.last_sent_y = self.smoothed_y
                                self.send_eye_position(self.smoothed_x, self.smoothed_y)
                                if self.debug:
                                    print(f"Position update: x={self.smoothed_x:.3f}, y={self.smoothed_y:.3f}, dx={dx:.3f}, dy={dy:.3f}")
                            elif self.debug and int(start_time) != int(self.last_update - 1):
                                print(f"Skipped update (small change): dx={dx:.3f}, dy={dy:.3f}")

                        # Update state with real tracking
                        self.current_x = x
                        self.current_y = y
                        self.magnitude = magnitude
                        self.last_update = time.time()

                        if self.debug and int(start_time) != int(self.last_update - 1):
                            print(f"Tracking: raw=({x:.3f},{y:.3f}) smoothed=({self.smoothed_x:.3f},{self.smoothed_y:.3f}) heat={magnitude:.1f}")
                    else:
                        # No significant heat detected, disconnect controller to enable auto movement
                        if hasattr(self, 'tracking_active') and self.tracking_active:
                            self.disconnect_controller()
                            self.tracking_active = False
                        
                        if self.debug and int(start_time) != int(self.last_update - 1):
                            print(f"No heat detected (magnitude={magnitude:.1f}), using auto movement")
                else:
                    # Sensor failed, disconnect controller to enable auto movement
                    if hasattr(self, 'tracking_active') and self.tracking_active:
                        self.disconnect_controller()
                        self.tracking_active = False
                    
                    if self.debug:
                        print("Sensor data unavailable, using auto movement")
                
            except Exception as e:
                print(f"Error in sensor loop: {e}")
            
            # Maintain update rate
            elapsed = time.time() - start_time
            if elapsed < sleep_time:
                time.sleep(sleep_time - elapsed)
    
    def handle_status_request(self, data, addr):
        """Handle status/configuration requests."""
        try:
            request = data.decode('utf-8').strip()
            
            if request == 'status':
                status = {
                    'running': self.running,
                    'sensor_available': self.sensor is not None,
                    'current_x': self.current_x,
                    'current_y': self.current_y,
                    'magnitude': self.magnitude,
                    'last_update': self.last_update,
                    'update_rate': self.update_rate,
                    'sensitivity': self.sensitivity
                }
                response = json.dumps(status).encode('utf-8')
                self.status_sock.sendto(response, addr)
                
            elif request.startswith('sensitivity='):
                try:
                    new_sensitivity = float(request.split('=')[1])
                    self.sensitivity = max(0.1, min(20.0, new_sensitivity))
                    response = f"Sensitivity set to {self.sensitivity}".encode('utf-8')
                    self.status_sock.sendto(response, addr)
                except ValueError:
                    response = b"Invalid sensitivity value"
                    self.status_sock.sendto(response, addr)
                    
        except Exception as e:
            print(f"Error handling status request: {e}")
    
    def status_server_loop(self):
        """UDP server for status and configuration."""
        try:
            self.status_sock.bind(('0.0.0.0', self.thermal_port))
            print(f"Status server listening on port {self.thermal_port}")
            
            while self.running:
                try:
                    self.status_sock.settimeout(1.0)  # 1 second timeout
                    data, addr = self.status_sock.recvfrom(1024)
                    self.handle_status_request(data, addr)
                except socket.timeout:
                    continue  # Check running flag
                except Exception as e:
                    print(f"Status server error: {e}")
                    
        except Exception as e:
            print(f"Failed to start status server: {e}")
    
    def start(self):
        """Start the thermal tracking service."""
        self.running = True
        
        # Initialize sensor
        sensor_ok = self.initialize_sensor()
        if not sensor_ok and not self.debug:
            print("Sensor initialization failed and not in debug mode. Exiting.")
            return False
        
        # Start threads
        self.sensor_thread = threading.Thread(target=self.sensor_loop, daemon=True)
        self.status_thread = threading.Thread(target=self.status_server_loop, daemon=True)
        
        self.sensor_thread.start()
        self.status_thread.start()
        
        print("Thermal tracking service started")
        return True
    
    def stop(self):
        """Stop the thermal tracking service."""
        print("Stopping thermal tracking service...")
        self.running = False
        
        # Ensure auto movement is restored
        if self.tracking_active:
            self.disconnect_controller()
            self.tracking_active = False
        
        if self.sensor_thread:
            self.sensor_thread.join(timeout=2.0)
        if self.status_thread:
            self.status_thread.join(timeout=2.0)
            
        self.eye_sock.close()
        self.status_sock.close()
        
        print("Thermal tracking service stopped")


def signal_handler(sig, frame):
    """Handle shutdown signals."""
    print(f"\nReceived signal {sig}, shutting down...")
    if 'tracker' in globals():
        tracker.stop()
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description='Thermal Eye Tracker for Pi_Eyes')
    parser.add_argument('--eye-host', default='127.0.0.1',
                        help='IP address of eye controller (default: 127.0.0.1)')
    parser.add_argument('--eye-port', type=int, default=5005,
                        help='UDP port of eye controller (default: 5005)')
    parser.add_argument('--thermal-port', type=int, default=5007,
                        help='UDP port for thermal tracker status (default: 5007)')
    parser.add_argument('--rate', type=float, default=5.0,
                        help='Update rate in Hz (default: 5.0)')
    parser.add_argument('--sensitivity', type=float, default=5.0,
                        help='Thermal sensitivity multiplier (default: 5.0)')
    parser.add_argument('--position-threshold', type=float, default=0.05,
                        help='Minimum position change to trigger update (default: 0.05)')
    parser.add_argument('--smoothing', type=float, default=0.7,
                        help='Smoothing factor 0.0-0.9, higher=smoother but slower (default: 0.7)')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug output and simulation mode')

    args = parser.parse_args()

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create and start tracker
    global tracker
    tracker = ThermalTracker(
        eye_host=args.eye_host,
        eye_port=args.eye_port,
        thermal_port=args.thermal_port,
        update_rate=args.rate,
        sensitivity=args.sensitivity,
        debug=args.debug,
        position_threshold=args.position_threshold,
        smoothing=args.smoothing
    )
    
    if tracker.start():
        try:
            # Keep main thread alive
            while tracker.running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            tracker.stop()
    else:
        print("Failed to start thermal tracking service")
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())