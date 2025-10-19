# Pi_Eyes Ansible Role

Ansible role for deploying and configuring the Pi_Eyes animatronics control system on Raspberry Pi.

## Description

This role automates the installation and configuration of:
- Snake Eyes animation system
- Servo-controlled mouth system with idle positioning and easing
- Backlight control (optional - disabled by default)
- MQTT-based animation daemon (optional)

## Requirements

### Control Node (Ansible Host)
- Ansible 2.9 or higher
- `ansible.posix` collection (install with `ansible-galaxy collection install ansible.posix`)
- `rsync` installed

### Target System (Raspberry Pi)

**IMPORTANT:** Before using this role, you MUST first install the base Snake Eyes software and drivers by following the official Adafruit installation guide:

**[Adafruit Snake Eyes Bonnet Software Installation](https://learn.adafruit.com/animated-snake-eyes-bonnet-for-raspberry-pi/software-installation)**

This Ansible role deploys the Pi_Eyes code on top of the Adafruit installation. It does NOT install the base drivers or dependencies required for the Snake Eyes Bonnet hardware.

**Additional Requirements:**
- Raspberry Pi running Raspberry Pi OS (32-bit recommended)
- Snake Eyes Bonnet or compatible hardware
- Servo motor for mouth control (optional)
- `rsync` installed on target system (`sudo apt install rsync`)

**Note:** For full hardware compatibility and OS version requirements, see the [Adafruit guide](https://learn.adafruit.com/animated-snake-eyes-bonnet-for-raspberry-pi/software-installation).

## Role Variables

### Installation Settings

```yaml
# Installation paths
pi_eyes_install_path: /boot/Pi_Eyes
pi_eyes_animations_dir: /etc/anim

# Service configuration - what to install
pi_eyes_install_eyes: true
pi_eyes_install_mouth: true
pi_eyes_install_backlight: false  # Set to true if backlight hardware is installed
pi_eyes_install_mqtt: false
```

### Mouth Servo Configuration

```yaml
pi_eyes_mouth_pin: 22
pi_eyes_mouth_port: 5006
pi_eyes_mouth_pwm_min: 102
pi_eyes_mouth_pwm_max: 180
pi_eyes_mouth_idle_position: 128
pi_eyes_mouth_idle_timeout: 2.0
pi_eyes_mouth_idle_ease_duration: 0.5
```

### Backlight Configuration (Optional)

**Note:** Backlight is disabled by default. Only enable if you have backlight hardware installed.

```yaml
pi_eyes_backlight_pin: 18
pi_eyes_backlight_port: 5007
pi_eyes_backlight_brightness: 255
pi_eyes_backlight_freq: 1000
```

To enable backlight:
```yaml
pi_eyes_install_backlight: true
```

### MQTT Configuration

```yaml
pi_eyes_mqtt_host: localhost
pi_eyes_mqtt_port: 1883
pi_eyes_mqtt_user: ""
pi_eyes_mqtt_pass: ""
pi_eyes_robot_name: head1
```

See `defaults/main.yml` for all available variables.

## Dependencies

None.

## Example Playbook

### Basic Installation

```yaml
- hosts: animatronics
  become: yes
  roles:
    - role: pi_eyes
```

### Custom Configuration

```yaml
- hosts: animatronics
  become: yes
  roles:
    - role: pi_eyes
      vars:
        pi_eyes_install_mqtt: true
        pi_eyes_mqtt_host: mqtt.example.com
        pi_eyes_mqtt_user: robot
        pi_eyes_mqtt_pass: secret
        pi_eyes_robot_name: head1
        pi_eyes_mouth_idle_position: 100
        pi_eyes_mouth_idle_timeout: 3.0
```

### Only Install Mouth Control

```yaml
- hosts: animatronics
  become: yes
  roles:
    - role: pi_eyes
      vars:
        pi_eyes_install_eyes: false
        pi_eyes_install_backlight: false
        pi_eyes_install_mqtt: false
        pi_eyes_install_mouth: true
```

## Installing the Role

### Prerequisites

Install required Ansible collections:

```bash
ansible-galaxy collection install ansible.posix
```

### From Git Repository (requirements.yml)

Create a `requirements.yml` file in your Ansible project:

```yaml
---
roles:
  - name: pi_eyes
    src: https://github.com/kenavn/Pi_Eyes.git
    scm: git
    version: master  # or specify a tag like v1.0.0
```

Install with:

```bash
ansible-galaxy install -r requirements.yml -p roles/
```

This will clone the entire Pi_Eyes repository and make the role available at `roles/pi_eyes`.

### From Local Clone

```bash
git clone https://github.com/kenavn/Pi_Eyes.git /tmp/pi_eyes
cp -r /tmp/pi_eyes/ansible/roles/pi_eyes roles/
```

## Usage in Playbook

```yaml
---
- name: Deploy Pi_Eyes to animatronics
  hosts: pi_eyes_hosts
  become: yes

  vars:
    pi_eyes_mqtt_host: mqtt.mydomain.com
    pi_eyes_robot_name: skeleton_head

  roles:
    - pi_eyes
```

## Services Managed

This role creates and manages the following systemd services:

- `mouth.service` - Servo-controlled mouth with idle easing
- `backlight.service` - Eye backlight control (if enabled)
- `mqtt.service` - MQTT animation daemon (if enabled)

Check service status:
```bash
sudo systemctl status mouth.service
sudo systemctl status backlight.service
sudo systemctl status mqtt.service
```

## Hardware Requirements

- Raspberry Pi (Pi 3, Pi 4, Pi 400, Pi Zero, or Compute Module 4)
- Snake Eyes Bonnet or compatible display bonnet
- Servo motor for mouth control (optional)
- GPIO connections as configured

## License

MIT

## Author Information

Created by Kenneth Avner for the Pi_Eyes animatronics project.
