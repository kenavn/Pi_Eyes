# Sound Files Directory

This directory contains audio files for the Pi_Eyes sound player service.

## Directory Structure

- **`sounds/`** - Place named sound files here that can be triggered by filename
- **`sounds/random/`** - Place sound files here for random selection

## Supported Formats

The sound player supports the following audio formats:
- MP3 (`.mp3`)
- WAV (`.wav`)
- OGG (`.ogg`)
- FLAC (`.flac`)

## Usage

### Play Specific Sound
Place your sound file in this directory, then trigger it by name:

```bash
# From development machine
python test_sound_player.py -i <pi_ip> --play mysound.mp3
```

### Play Random Sound
Place multiple sound files in the `random/` subdirectory. The service will randomly select one:

```bash
# From development machine
python test_sound_player.py -i <pi_ip> --random
```

## Notes

- Audio files are ignored by git (see `.gitignore`)
- Only the directory structure is tracked in version control
- Files can be added locally for testing or deployed to the Pi via scp/rsync
- The sound player service on the Pi will look for files in `/boot/Pi_Eyes/sounds/`
