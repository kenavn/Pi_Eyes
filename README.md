# Pi_Eyes (Remote)

This is a fork of the original Pi Eyes from Adafruit.

I've modified it, removing the local joystick control and added support for:

- Remote control via UDP stream
- Controlling with a Sony PS4 controller from a PC
- Ability to record an animation with the PS4 controller
- Ability to playback recordings
- Ability to loop playback until aborted

The script is really not cleaned up much compared to the original, so it doesn't look like much. But it serves its purpose :)

_Creds to Adafruit and Paint Your Dragon for the original work._

### Install the eye controller

1. Install the original software through Adafruits [instructions](https://learn.adafruit.com/animated-snake-eyes-bonnet-for-raspberry-pi/software-installation).

2. Replace the `/boot/Pi_Eyes/eyes.py` with `eyes.py` from this repo.
3. Reboot the pi
4. (Optional) You may try to up the priority of the processes involved to reduce lag. Do this by modifying the startup script by doing the following: 1. `sudo nano /etc/rc.local` and go all the way down 2. change the commands on the bottom to: `nice -n -20 /boot/Pi_Eyes/fbx2 -i &
cd /boot/Pi_Eyes; nice -n -20 xinit /usr/bin/python3 eyes.py --radius 240 :0 &
exit 0`. Note that the radius parameter should read the same as the old command you replaced.

### Install the mouth controller (optional)

The mouth controller runs the mouth with a servo motor (mouth.py). It has a dependency installed on the raspi image, but
it needs to be enabled (pigpiod).

Run the following commands on the Raspberry Pi to enable the pigpiod service:
`sudo systemctl start pigpiod`
`sudo systemctl enable pigpiod`

After enabling this service, we also need to add the mouth.py program to the system boot:

1. Copy the `mouth.py` file into `/boot/Pi_Eyes/` folder on the Raspberry Pi
2. Copy the `mouth.service` file into `/etc/systemd/system/` folder as well (you will need sudo)
3. `sudo chmod +x /boot/Pi_Eyes/mouth.py`
4. `sudo systemctl daemon-reload`
5. `sudo systemctl enable mouth.service`
6. `sudo systemctl start mouth.service`

You can check the status of the new service by running:
`sudo systemctl status mouth.service`

### Install the remote control

1. Make sure you have Python installed on your remote machine
2. Get the eyeRemote.py from this repo.

### How to remote control and record

`python eyeRemote.py -i 192.168.1.2 -p 5005`
Press the SHARE button on controller to start/stop recording.

### How to playback

`python eyeRemote.py -i 192.168.1.2 -p 5005 -r recording.csv`

### HW Documentation from Adafruit

https://learn.adafruit.com/animated-snake-eyes-bonnet-for-raspberry-pi/
