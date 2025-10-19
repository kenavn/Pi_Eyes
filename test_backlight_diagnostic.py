#!/usr/bin/python3

import pigpio
import time

print("=== Backlight Diagnostic Test ===\n")

# Test pigpio connection
print("1. Testing pigpio connection...")
pi = pigpio.pi()
if not pi.connected:
    print("   ❌ ERROR: Cannot connect to pigpiod daemon")
    print("   Run: sudo pigpiod")
    exit(1)
else:
    print("   ✓ pigpiod is running")

# Test different GPIO pins that might be the backlight
test_pins = [18, 12, 13, 19]

print("\n2. Testing possible backlight pins...")
print("   Watch your displays - one should change brightness!\n")

for pin in test_pins:
    print(f"   Testing GPIO {pin}:")

    try:
        # Set up PWM
        pi.set_PWM_frequency(pin, 1000)
        pi.set_PWM_range(pin, 255)

        # Full brightness
        print(f"      - Full brightness (255)")
        pi.set_PWM_dutycycle(pin, 255)
        time.sleep(2)

        # Half brightness
        print(f"      - Half brightness (128)")
        pi.set_PWM_dutycycle(pin, 128)
        time.sleep(2)

        # Very dim
        print(f"      - Very dim (20)")
        pi.set_PWM_dutycycle(pin, 20)
        time.sleep(2)

        # Off
        print(f"      - Off (0)")
        pi.set_PWM_dutycycle(pin, 0)
        time.sleep(2)

        # Back to full
        print(f"      - Back to full (255)")
        pi.set_PWM_dutycycle(pin, 255)
        time.sleep(1)

        print(f"      Did GPIO {pin} control the backlight? (y/n)")
        response = input("      > ").strip().lower()
        if response == 'y':
            print(f"\n   ✓ Found backlight on GPIO {pin}!")
            pi.stop()
            exit(0)

    except Exception as e:
        print(f"      ❌ Error testing GPIO {pin}: {e}")

print("\n3. No backlight pin found. Checking hardware configuration...")
print("   Possible issues:")
print("   - LITE pin might not be connected to GPIO")
print("   - LITE pin might be hardwired to 3.3V")
print("   - Different GPIO pin is used")
print("\n   Please check:")
print("   - Adafruit Snake Eyes Bonnet documentation")
print("   - Physical LITE pin connection on the bonnet")
print("   - /boot/config.txt for any display-related settings")

pi.stop()
