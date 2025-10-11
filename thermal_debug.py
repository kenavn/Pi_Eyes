#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Thermal Debug and Calibration Utilities for Pi_Eyes Thermal Tracker

This utility provides debugging and calibration tools for the thermal tracking system:
- View live thermal data in ASCII format
- Test thermal sensor connectivity
- Calibrate sensitivity settings
- Monitor eye tracking commands
- Test UDP communication
"""

import socket
import struct
import time
import argparse
import json
import sys
import threading
from datetime import datetime

try:
    from amg8833_simple import AMG8833Simple
    AMG8833_AVAILABLE = True
except ImportError:
    AMG8833_AVAILABLE = False


class ThermalDebugger:
    def __init__(self, thermal_host='127.0.0.1', thermal_port=5007, 
                 eye_host='127.0.0.1', eye_port=5005):
        self.thermal_host = thermal_host
        self.thermal_port = thermal_port
        self.eye_host = eye_host
        self.eye_port = eye_port
        
        self.sensor = None
        self.running = False
    
    def initialize_sensor(self):
        """Initialize direct connection to AMG8833 sensor."""
        if not AMG8833_AVAILABLE:
            print("AMG8833 simple interface not available")
            return False
            
        try:
            self.sensor = AMG8833Simple()
            time.sleep(1)  # Stabilization time
            print("AMG8833 sensor initialized successfully")
            return True
        except Exception as e:
            print(f"Failed to initialize AMG8833: {e}")
            return False
    
    def test_thermal_service_connection(self):
        """Test connection to thermal tracker service."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5.0)
            
            # Send status request
            sock.sendto(b'status', (self.thermal_host, self.thermal_port))
            
            # Wait for response
            data, addr = sock.recvfrom(1024)
            status = json.loads(data.decode('utf-8'))
            
            print("Thermal service status:")
            for key, value in status.items():
                if key == 'last_update':
                    # Convert timestamp to readable time
                    dt = datetime.fromtimestamp(value)
                    print(f"  {key}: {dt.strftime('%Y-%m-%d %H:%M:%S')} ({value})")
                else:
                    print(f"  {key}: {value}")
            
            sock.close()
            return True
            
        except socket.timeout:
            print("Timeout: Thermal service not responding")
            return False
        except Exception as e:
            print(f"Failed to connect to thermal service: {e}")
            return False
    
    def set_thermal_sensitivity(self, sensitivity):
        """Set sensitivity of thermal tracker service."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5.0)
            
            command = f'sensitivity={sensitivity}'.encode('utf-8')
            sock.sendto(command, (self.thermal_host, self.thermal_port))
            
            data, addr = sock.recvfrom(1024)
            response = data.decode('utf-8')
            print(f"Sensitivity response: {response}")
            
            sock.close()
            return True
            
        except Exception as e:
            print(f"Failed to set sensitivity: {e}")
            return False
    
    def display_thermal_grid(self, pixels):
        """Display thermal data as ASCII art grid."""
        if len(pixels) != 64:
            print("Error: Expected 64 thermal pixels")
            return
        
        # Find temperature range for scaling
        min_temp = min(pixels)
        max_temp = max(pixels)
        temp_range = max_temp - min_temp if max_temp > min_temp else 1.0
        
        print(f"\nThermal Grid (Range: {min_temp:.1f}°C - {max_temp:.1f}°C)")
        print("┌" + "─" * 24 + "┐")
        
        # Display 8x8 grid
        for row in range(8):
            line = "│"
            for col in range(8):
                pixel_idx = row * 8 + col
                temp = pixels[pixel_idx]
                
                # Normalize temperature to 0-1
                normalized = (temp - min_temp) / temp_range
                
                # Convert to ASCII intensity
                if normalized < 0.1:
                    char = " "
                elif normalized < 0.3:
                    char = "."
                elif normalized < 0.5:
                    char = "o"
                elif normalized < 0.7:
                    char = "O"
                elif normalized < 0.9:
                    char = "@"
                else:
                    char = "#"
                
                line += char * 3  # 3 chars wide for better visibility
            
            line += "│"
            print(line)
        
        print("└" + "─" * 24 + "┘")
    
    def live_thermal_display(self):
        """Display live thermal data from sensor."""
        if not self.sensor:
            print("No sensor available - use --test-service to view tracker output")
            return
        
        print("Live Thermal Display (Press Ctrl+C to stop)")
        print("Sensor readings will update every second...")
        
        try:
            while True:
                pixels = self.sensor.pixels
                
                # Clear screen (basic)
                sys.stdout.write("\033[2J\033[H")  # ANSI clear screen
                print(f"Live Thermal Data - {datetime.now().strftime('%H:%M:%S')}")
                
                self.display_thermal_grid(pixels)
                
                # Calculate and display centroid (simplified version)
                x, y = self.calculate_centroid(pixels)
                print(f"\nCalculated centroid: X={x:.3f}, Y={y:.3f}")
                
                time.sleep(1.0)
                
        except KeyboardInterrupt:
            print("\nLive display stopped")
    
    def calculate_centroid(self, pixels):
        """Calculate centroid for debugging (simplified version)."""
        x, y = 0.0, 0.0
        i = 0
        
        for y_pos in [3.5, 2.5, 1.5, 0.5, -0.5, -1.5, -2.5, -3.5]:
            for x_pos in [3.5, 2.5, 1.5, 0.5, -0.5, -1.5, -2.5, -3.5]:
                pixel_temp = pixels[i]
                x += x_pos * pixel_temp
                y += y_pos * pixel_temp
                i += 1
        
        # Basic scaling
        x = -x / 64.0 / 5.0
        y = y / 64.0 / 5.0
        x = max(-1.0, min(1.0, x))
        y = max(-1.0, min(1.0, y))
        
        return x, y
    
    def test_eye_commands(self):
        """Send test eye position commands."""
        print("Testing eye position commands...")
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Test positions: center, corners, and sweep
        test_positions = [
            (0.0, 0.0),    # Center
            (-1.0, -1.0),  # Top-left
            (1.0, -1.0),   # Top-right
            (-1.0, 1.0),   # Bottom-left
            (1.0, 1.0),    # Bottom-right
        ]
        
        try:
            for x, y in test_positions:
                print(f"Sending eye position: x={x:.1f}, y={y:.1f}")
                
                # Convert to byte format
                x_byte = int((x + 1.0) * 127.5)
                y_byte = int((y + 1.0) * 127.5)
                x_byte = max(0, min(255, x_byte))
                y_byte = max(0, min(255, y_byte))
                
                message = b'\x20' + struct.pack('BB', x_byte, y_byte)
                sock.sendto(message, (self.eye_host, self.eye_port))
                
                time.sleep(2.0)  # Hold position
            
            # Return to center
            print("Returning to center")
            message = b'\x20' + struct.pack('BB', 127, 127)
            sock.sendto(message, (self.eye_host, self.eye_port))
            
        except Exception as e:
            print(f"Error sending eye commands: {e}")
        finally:
            sock.close()
    
    def monitor_thermal_service(self):
        """Monitor thermal service status continuously."""
        print("Monitoring thermal service (Press Ctrl+C to stop)")
        
        try:
            while True:
                success = self.test_thermal_service_connection()
                if not success:
                    print("Service not responding, retrying in 5 seconds...")
                
                time.sleep(5.0)
                
        except KeyboardInterrupt:
            print("\nMonitoring stopped")
    
    def run_interactive_calibration(self):
        """Interactive calibration mode."""
        print("\n=== Thermal Tracker Calibration ===")
        print("This will help you calibrate the thermal tracking system")
        
        # Test service connection
        print("\n1. Testing thermal service connection...")
        if not self.test_thermal_service_connection():
            print("Cannot proceed without thermal service. Start thermal_tracker.py first.")
            return
        
        # Sensitivity calibration
        print("\n2. Sensitivity Calibration")
        print("Current sensitivity will be displayed above.")
        
        while True:
            try:
                sensitivity_input = input("Enter new sensitivity (0.1-20.0) or 'skip': ")
                if sensitivity_input.lower() == 'skip':
                    break
                
                sensitivity = float(sensitivity_input)
                if 0.1 <= sensitivity <= 20.0:
                    if self.set_thermal_sensitivity(sensitivity):
                        print(f"Sensitivity set to {sensitivity}")
                        time.sleep(1)
                        # Show updated status
                        self.test_thermal_service_connection()
                    break
                else:
                    print("Sensitivity must be between 0.1 and 20.0")
                    
            except ValueError:
                print("Invalid input. Enter a number or 'skip'")
        
        # Eye movement test
        print("\n3. Eye Movement Test")
        test_input = input("Test eye movements? (y/n): ")
        if test_input.lower() == 'y':
            self.test_eye_commands()
        
        print("\nCalibration complete!")


def main():
    parser = argparse.ArgumentParser(description='Thermal Tracker Debug and Calibration')
    parser.add_argument('--thermal-host', default='127.0.0.1',
                        help='IP of thermal tracker service (default: 127.0.0.1)')
    parser.add_argument('--thermal-port', type=int, default=5007,
                        help='Port of thermal tracker service (default: 5007)')
    parser.add_argument('--eye-host', default='127.0.0.1',
                        help='IP of eye controller (default: 127.0.0.1)')
    parser.add_argument('--eye-port', type=int, default=5005,
                        help='Port of eye controller (default: 5005)')
    
    # Command modes
    parser.add_argument('--test-service', action='store_true',
                        help='Test connection to thermal tracker service')
    parser.add_argument('--test-sensor', action='store_true',
                        help='Test direct connection to thermal sensor')
    parser.add_argument('--test-eyes', action='store_true',
                        help='Send test commands to eye controller')
    parser.add_argument('--live-display', action='store_true',
                        help='Show live thermal data display')
    parser.add_argument('--monitor', action='store_true',
                        help='Monitor thermal service continuously')
    parser.add_argument('--calibrate', action='store_true',
                        help='Run interactive calibration')
    parser.add_argument('--sensitivity', type=float,
                        help='Set thermal tracker sensitivity')
    
    args = parser.parse_args()
    
    debugger = ThermalDebugger(
        thermal_host=args.thermal_host,
        thermal_port=args.thermal_port,
        eye_host=args.eye_host,
        eye_port=args.eye_port
    )
    
    # Execute requested operations
    if args.test_sensor:
        print("Testing thermal sensor connection...")
        debugger.initialize_sensor()
    
    if args.test_service:
        print("Testing thermal service connection...")
        debugger.test_thermal_service_connection()
    
    if args.test_eyes:
        debugger.test_eye_commands()
    
    if args.sensitivity is not None:
        debugger.set_thermal_sensitivity(args.sensitivity)
    
    if args.live_display:
        if debugger.initialize_sensor():
            debugger.live_thermal_display()
        else:
            print("Cannot start live display without sensor")
    
    if args.monitor:
        debugger.monitor_thermal_service()
    
    if args.calibrate:
        debugger.run_interactive_calibration()
    
    # If no specific command given, show help
    if not any([args.test_service, args.test_sensor, args.test_eyes, 
                args.live_display, args.monitor, args.calibrate, 
                args.sensitivity is not None]):
        parser.print_help()
        print("\nExample usage:")
        print("  python thermal_debug.py --test-service")
        print("  python thermal_debug.py --calibrate")
        print("  python thermal_debug.py --live-display")
        print("  python thermal_debug.py --sensitivity 7.5")


if __name__ == '__main__':
    main()