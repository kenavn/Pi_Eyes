# Pi_Eyes Ansible Deployment Guide

## Prerequisites

**CRITICAL:** This role does NOT install the base Snake Eyes Bonnet drivers and software. You MUST complete the Adafruit installation first:

### Step 1: Install Base Snake Eyes Software

Follow the official guide to install drivers and dependencies:
**[Adafruit Snake Eyes Bonnet Software Installation](https://learn.adafruit.com/animated-snake-eyes-bonnet-for-raspberry-pi/software-installation)**

This includes:
- Correct Raspberry Pi OS version for your hardware
- Snake Eyes Bonnet drivers
- Graphics libraries (Pi3D)
- Display configuration
- Base dependencies

### Step 2: Use This Ansible Role

After completing the Adafruit installation, use this role to deploy the Pi_Eyes code with remote control capabilities.

## How It Works

This role follows the best practice of **keeping deployment logic with the code**. Here's the deployment flow:

### Architecture

```
Your Ansible Repo                    Target Raspberry Pi
================                     ===================

requirements.yml
    |
    v
ansible-galaxy install
    |
    v
Clones entire Pi_Eyes repo
to roles/pi_eyes/
    |
    v
Role contains:
  - ansible/roles/pi_eyes/    <-- Role definition
  - mouth.py, eyes.py, etc    <-- Application code
    |
    v
ansible-playbook runs
    |
    v
synchronize module           ------>  /boot/Pi_Eyes/
copies code from role                 (deployed code)
to target system
    |
    v
Services configured                  systemd services:
and started                          - mouth.service
                                     - backlight.service
                                     - mqtt.service
```

## Why This Approach?

1. **No Git Clone on Target**: The role doesn't need git to be installed on the Raspberry Pi
2. **Version Control**: Code and deployment are versioned together
3. **Atomic Updates**: Update code and role configuration in the same commit
4. **Offline Capable**: Once role is installed, can deploy to air-gapped systems

## Usage in Your Ansible Repository

### Step 1: Add to requirements.yml

```yaml
---
collections:
  - name: ansible.posix

roles:
  - name: pi_eyes
    src: https://github.com/kenavn/Pi_Eyes.git
    scm: git
    version: v1.0.0  # Pin to a specific version for production!
```

### Step 2: Install

```bash
# Install collections first
ansible-galaxy collection install -r requirements.yml

# Then install roles
ansible-galaxy install -r requirements.yml -p roles/
```

This will:
- Clone the Pi_Eyes repo to `roles/pi_eyes/`
- The role at `roles/pi_eyes/ansible/roles/pi_eyes/` becomes available
- All the application code is bundled with the role

### Step 3: Use in Playbook

```yaml
---
- hosts: animatronics
  become: yes
  roles:
    - role: pi_eyes
      vars:
        pi_eyes_install_mqtt: true
        pi_eyes_mqtt_host: mqtt.example.com
        pi_eyes_robot_name: head1
```

### Step 4: Deploy

```bash
ansible-playbook -i inventory site.yml
```

The role will:
1. Install system packages (pigpio, python3-pip, etc)
2. Copy Pi_Eyes code from the role to `/boot/Pi_Eyes/` on target
3. Deploy service files with your configuration
4. Start and enable services

## Version Pinning (Recommended)

Always pin to a specific version in production:

```yaml
roles:
  - name: pi_eyes
    src: https://github.com/kenavn/Pi_Eyes.git
    scm: git
    version: v1.2.3  # Use git tags
```

This ensures:
- Reproducible deployments
- No surprises from master branch changes
- Easy rollback if needed

## Updating the Deployment

```bash
# Update to latest version
ansible-galaxy install -r requirements.yml -p roles/ --force

# Re-run playbook
ansible-playbook -i inventory site.yml
```

## Files Excluded from Deployment

The following are NOT copied to the target system:
- `.git/` - Git metadata
- `ansible/` - The role itself (not needed on target)
- `editor/venv/` - Python virtual environment
- `__pycache__/`, `*.pyc` - Python bytecode

Only the application code is deployed.

## Dependencies

### Control Node
- rsync
- ansible.posix collection

### Target System
- **Base Snake Eyes installation** (see Prerequisites above)
- rsync
- python3
- All dependencies from the Adafruit installation (Pi3D, graphics libraries, etc.)

## Troubleshooting

### "Base Snake Eyes not installed"
If the role fails or services don't work properly, ensure you completed the Adafruit installation:
- Follow: https://learn.adafruit.com/animated-snake-eyes-bonnet-for-raspberry-pi/software-installation
- Verify the base eyes.py works before deploying this role
- Check that `/boot/Pi_Eyes` directory exists with Adafruit's installation

### "synchronize module not found"
Install the ansible.posix collection:
```bash
ansible-galaxy collection install ansible.posix
```

### "rsync not found"
Install rsync on both control and target:
```bash
# On Debian/Ubuntu
sudo apt install rsync
```

### Services not starting
Check service status on target:
```bash
sudo systemctl status mouth.service
sudo journalctl -u mouth.service -f
```

### Graphics/Display issues
These are usually related to the base Snake Eyes installation, not this role:
- Verify the Adafruit installation is working
- Check display configuration in `/boot/config.txt`
- See Adafruit troubleshooting guide
