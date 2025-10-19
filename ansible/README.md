# Pi_Eyes Ansible Role

This directory contains an Ansible role for deploying the Pi_Eyes animatronics system.

## Prerequisites

**IMPORTANT:** This role assumes you have already installed the base Snake Eyes Bonnet software following the Adafruit guide:

**[Adafruit Snake Eyes Bonnet Software Installation](https://learn.adafruit.com/animated-snake-eyes-bonnet-for-raspberry-pi/software-installation)**

This role deploys the Pi_Eyes application code on top of that base installation.

## Quick Start

### In Your Ansible Repository

1. **Create a `requirements.yml` file:**

```yaml
---
collections:
  - name: ansible.posix

roles:
  - name: pi_eyes
    src: https://github.com/kenavn/Pi_Eyes.git
    scm: git
    version: master  # or pin to a specific tag
```

2. **Install dependencies and the role:**

```bash
ansible-galaxy collection install -r requirements.yml
ansible-galaxy install -r requirements.yml -p roles/
```

3. **Use in your playbook:**

```yaml
---
- hosts: animatronics
  become: yes
  roles:
    - role: pi_eyes
      vars:
        pi_eyes_mqtt_host: mqtt.example.com
        pi_eyes_robot_name: head1
```

4. **Run the playbook:**

```bash
ansible-playbook -i inventory site.yml
```

## Example Files

- `requirements.yml` - Example requirements file for ansible-galaxy
- `example-playbook.yml` - Complete example playbook with all variables
- `roles/pi_eyes/` - The actual Ansible role

## Role Documentation

See [roles/pi_eyes/README.md](roles/pi_eyes/README.md) for complete documentation including:
- All available variables
- Configuration examples
- Service management
- Hardware requirements

## Testing Locally

You can test the role locally with:

```bash
# Install the role from this repo
ansible-galaxy install -r requirements.yml -p roles/

# Run against localhost (for testing)
ansible-playbook -i "localhost," -c local example-playbook.yml
```

## Customization

All configurable options are in `roles/pi_eyes/defaults/main.yml`. Override them in your playbook as needed:

```yaml
- hosts: animatronics
  roles:
    - role: pi_eyes
      vars:
        pi_eyes_mouth_pwm_min: 90
        pi_eyes_mouth_pwm_max: 200
        pi_eyes_mouth_idle_position: 100
        pi_eyes_install_mqtt: true
```

## Components Deployed

- **Mouth Control**: Servo-based mouth with idle positioning and smooth easing
- **Backlight Control**: PWM-based backlight control for eyes
- **MQTT Service**: Animation daemon for remote control (optional)
- **Eyes**: Snake Eyes animation system

All components run as systemd services and can be independently enabled/disabled.
