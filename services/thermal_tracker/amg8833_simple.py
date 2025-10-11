#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Simple AMG8833 thermal camera interface for Python 3.7
Direct I2C communication without CircuitPython dependencies
"""

import struct
import time
try:
    import smbus
    SMBUS_AVAILABLE = True
except ImportError:
    SMBUS_AVAILABLE = False


class AMG8833Simple:
    """Simple AMG8833 thermal camera interface using smbus."""
    
    # AMG8833 I2C address and registers
    I2C_ADDRESS = 0x69
    THERMISTOR_REGISTER = 0x0E
    PIXEL_ARRAY_REGISTER = 0x80
    
    def __init__(self, i2c_bus=1):
        """Initialize AMG8833 sensor."""
        if not SMBUS_AVAILABLE:
            raise ImportError("smbus library not available. Install with: sudo apt install python3-smbus")
        
        self.bus = smbus.SMBus(i2c_bus)
        
        # Initialize sensor - set to normal mode
        try:
            self.bus.write_byte_data(self.I2C_ADDRESS, 0x00, 0x00)  # Normal mode
            self.bus.write_byte_data(self.I2C_ADDRESS, 0x02, 0x00)  # Reset register
            self.bus.write_byte_data(self.I2C_ADDRESS, 0x03, 0x00)  # Frame rate register
            time.sleep(0.1)  # Allow initialization
        except Exception as e:
            raise RuntimeError(f"Failed to initialize AMG8833: {e}")
    
    def _read_register_12bit(self, register):
        """Read a 12-bit value from two consecutive registers with retry."""
        for attempt in range(3):  # Retry up to 3 times
            try:
                low = self.bus.read_byte_data(self.I2C_ADDRESS, register)
                time.sleep(0.001)  # Small delay between reads
                high = self.bus.read_byte_data(self.I2C_ADDRESS, register + 1)
                
                # Combine bytes (little endian)
                value = (high << 8) | low
                
                # Convert to signed 12-bit value
                if value & 0x800:  # Sign bit set
                    value = value - 0x1000
                
                return value
            except Exception as e:
                if attempt < 2:  # Not the last attempt
                    time.sleep(0.01)  # Wait before retry
                    continue
                else:
                    raise RuntimeError(f"Failed to read register {register:02x} after 3 attempts: {e}")
    
    @property
    def thermistor_temperature(self):
        """Read thermistor temperature in Celsius."""
        raw = self._read_register_12bit(self.THERMISTOR_REGISTER)
        # Convert to Celsius: value * 0.0625
        return raw * 0.0625
    
    @property
    def pixels(self):
        """Read all 64 pixel temperatures as a flat list."""
        try:
            # Read all 128 bytes (64 pixels × 2 bytes each)
            pixel_data = []
            for i in range(64):
                register = self.PIXEL_ARRAY_REGISTER + (i * 2)
                raw_value = self._read_register_12bit(register)
                # Convert to Celsius: value * 0.25
                temperature = raw_value * 0.25
                pixel_data.append(temperature)
            
            return pixel_data
        except Exception as e:
            raise RuntimeError(f"Failed to read pixel data: {e}")
    
    def get_pixel_grid(self):
        """Get pixels as 8x8 grid (list of lists)."""
        pixels = self.pixels
        grid = []
        for row in range(8):
            row_data = []
            for col in range(8):
                index = row * 8 + col
                row_data.append(pixels[index])
            grid.append(row_data)
        return grid


def test_amg8833():
    """Test function for AMG8833 sensor."""
    try:
        sensor = AMG8833Simple()
        print(f"AMG8833 initialized successfully")
        print(f"Thermistor temperature: {sensor.thermistor_temperature:.2f}°C")
        
        pixels = sensor.pixels
        print(f"Read {len(pixels)} pixel values")
        print(f"Temperature range: {min(pixels):.1f}°C - {max(pixels):.1f}°C")
        
        return True
    except Exception as e:
        print(f"AMG8833 test failed: {e}")
        return False


if __name__ == "__main__":
    test_amg8833()