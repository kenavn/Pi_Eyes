#!/bin/bash

# Define the source and destination paths
source_path="/home/kenneth/Source/Pi_Eyes/eyes.py"
destination_path1="kenneth@raspieyes:eyes.py"
destination_path2="kenneth@raspieyes2:eyes.py"


# Copy the file using scp
scp "$source_path" "$destination_path"
scp "$source_path" "$destination_path2"

# Connect via SSH and move the file using sudo
ssh kenneth@raspieyes "sudo mv /home/kenneth/eyes.py /boot/Pi_Eyes/eyes.py && sudo reboot now"
ssh kenneth@raspieyes2 "sudo mv /home/kenneth/eyes.py /boot/Pi_Eyes/eyes.py && sudo reboot now"
