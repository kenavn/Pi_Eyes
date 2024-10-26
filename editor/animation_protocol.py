"""
Shared protocol definitions for animation control system.
Handles file formats and UDP message encoding/decoding.
"""

import struct
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional
import csv
from enum import Enum

import struct
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional, BinaryIO
import csv
import zipfile
import io
import json
import os
from datetime import datetime


class CommandType(Enum):
    # Eye commands
    JOYSTICK_CONNECTED = (b"\x01", None)
    JOYSTICK_DISCONNECTED = (b"\x00", None)
    AUTO_MOVEMENT_ON = (b"\x11", None)
    AUTO_MOVEMENT_OFF = (b"\x10", None)
    AUTO_BLINK_ON = (b"\x13", None)
    AUTO_BLINK_OFF = (b"\x12", None)
    AUTO_PUPIL_ON = (b"\x15", None)
    AUTO_PUPIL_OFF = (b"\x14", None)
    EYE_POSITION = (b"\x20", "BB")  # Two unsigned chars for x,y
    LEFT_EYELID = (b"\x30", "B")  # One unsigned char for position
    RIGHT_EYELID = (b"\x31", "B")  # One unsigned char for position
    BLINK_LEFT_START = (b"\x40", None)
    BLINK_LEFT_END = (b"\x41", None)
    BLINK_RIGHT_START = (b"\x42", None)
    BLINK_RIGHT_END = (b"\x43", None)
    BLINK_BOTH_START = (b"\x44", None)
    BLINK_BOTH_END = (b"\x45", None)

    # Mouth commands
    MOUTH_POSITION = (b"\x50", "B")  # One unsigned char for position

    def __init__(self, code: bytes, format_str: Optional[str]):
        self.code = code
        self.format_str = format_str


@dataclass
class AnimationBundle:
    """Represents a complete animation bundle with audio and movement data"""

    audio_file: str  # Original audio filename
    audio_data: bytes  # Raw audio file content
    eye_frames: List["EyeFrame"]
    mouth_frames: List["MouthFrame"]
    metadata: dict  # For storing additional info like duration, creation date, etc.


@dataclass
class EyeFrame:
    """Represents a single frame of eye animation data"""

    time_ms: int
    x: float
    y: float
    left_closed: bool
    right_closed: bool
    both_closed: bool


@dataclass
class MouthFrame:
    """Represents a single frame of mouth animation data"""

    time_ms: int
    position: int


class FileFormat:
    """Enhanced file format handler supporting both CSV and bundled formats"""

    BUNDLE_EXTENSION = ".skelanim"
    MANIFEST_NAME = "manifest.json"
    ANIMATION_NAME = "animation.csv"
    AUDIO_NAME = "audio.dat"

    @staticmethod
    def save_bundle(
        filename: str, audio_path: str, eye_data: List[Tuple], mouth_data: List[Tuple]
    ) -> bool:
        """Save animation and audio as a single bundle file"""
        try:
            if not filename.endswith(FileFormat.BUNDLE_EXTENSION):
                filename += FileFormat.BUNDLE_EXTENSION

            with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as bundle:
                # Save audio file
                if audio_path and os.path.exists(audio_path):
                    with open(audio_path, "rb") as audio_file:
                        audio_data = audio_file.read()
                        bundle.writestr(FileFormat.AUDIO_NAME, audio_data)

                # Save animation data
                animation_data = io.StringIO()
                writer = csv.writer(animation_data)

                # Write header
                header = ["time_ms", "type"]
                if eye_data:
                    header.extend(
                        [
                            "eye_x",
                            "eye_y",
                            "left_eye_closed",
                            "right_eye_closed",
                            "both_eyes_closed",
                        ]
                    )
                if mouth_data:
                    header.append("mouth_position")
                writer.writerow(header)

                # Write data
                for time_ms, x, y, left_blink, right_blink, both_eyes in eye_data:
                    row = [time_ms, "eye", x, y, left_blink, right_blink, both_eyes]
                    if mouth_data:
                        row.append(None)
                    writer.writerow(row)

                for time_ms, position in mouth_data:
                    if eye_data:
                        row = [time_ms, "mouth", None, None, None, None, None, position]
                    else:
                        row = [time_ms, "mouth", position]
                    writer.writerow(row)

                bundle.writestr(FileFormat.ANIMATION_NAME, animation_data.getvalue())

                # Save manifest with metadata
                manifest = {
                    "version": "1.0",
                    "created": datetime.now().isoformat(),
                    "audio_file": os.path.basename(audio_path) if audio_path else None,
                    "audio_format": (
                        os.path.splitext(audio_path)[1][1:] if audio_path else None
                    ),
                    "frame_count": len(eye_data) + len(mouth_data),
                }
                bundle.writestr(
                    FileFormat.MANIFEST_NAME, json.dumps(manifest, indent=2)
                )

            return True

        except Exception as e:
            print(f"Error saving bundle: {e}")
            return False

    @staticmethod
    def load_bundle(filename: str) -> Optional[AnimationBundle]:
        """Load animation bundle file"""
        try:
            with zipfile.ZipFile(filename, "r") as bundle:
                # Load manifest
                manifest = json.loads(bundle.read(FileFormat.MANIFEST_NAME))

                # Load audio data
                audio_data = (
                    bundle.read(FileFormat.AUDIO_NAME)
                    if FileFormat.AUDIO_NAME in bundle.namelist()
                    else None
                )

                # Load animation data
                animation_csv = io.StringIO(
                    bundle.read(FileFormat.ANIMATION_NAME).decode("utf-8")
                )
                reader = csv.DictReader(animation_csv)

                eye_frames = []
                mouth_frames = []

                for row in reader:
                    # Convert time_ms to int, handling float values
                    time_ms = int(float(row["time_ms"]))
                    if row["type"] == "eye":
                        eye_frames.append(
                            EyeFrame(
                                time_ms=time_ms,
                                x=(
                                    float(row["eye_x"])
                                    if row["eye_x"] != "None"
                                    else 0.5
                                ),
                                y=(
                                    float(row["eye_y"])
                                    if row["eye_y"] != "None"
                                    else 0.5
                                ),
                                left_closed=row["left_eye_closed"].lower() == "true",
                                right_closed=row["right_eye_closed"].lower() == "true",
                                both_closed=row["both_eyes_closed"].lower() == "true",
                            )
                        )
                    elif row["type"] == "mouth":
                        mouth_frames.append(
                            MouthFrame(
                                time_ms=time_ms,
                                position=(
                                    int(float(row["mouth_position"]))
                                    if row["mouth_position"] != "None"
                                    else 128
                                ),
                            )
                        )

                return AnimationBundle(
                    audio_file=manifest.get("audio_file"),
                    audio_data=audio_data,
                    eye_frames=eye_frames,
                    mouth_frames=mouth_frames,
                    metadata=manifest,
                )

        except Exception as e:
            print(f"Error loading bundle: {e}")
            raise  # Re-raise the exception to be caught by the caller

    @staticmethod
    def save_to_csv(
        filename: str, eye_data: List[Tuple], mouth_data: List[Tuple]
    ) -> bool:
        """Save eye and mouth animation data to CSV file"""
        try:
            with open(filename, "w", newline="") as csvfile:
                writer = csv.writer(csvfile)

                # Write header
                header = ["time_ms", "type"]
                if eye_data:
                    header.extend(
                        [
                            "eye_x",
                            "eye_y",
                            "left_eye_closed",
                            "right_eye_closed",
                            "both_eyes_closed",
                        ]
                    )
                if mouth_data:
                    header.append("mouth_position")
                writer.writerow(header)

                # Combine and sort all data
                all_data = []

                # Add eye data
                for time_ms, x, y, left_blink, right_blink, both_eyes in eye_data:
                    row = [time_ms, "eye", x, y, left_blink, right_blink, both_eyes]
                    if mouth_data:
                        row.append(None)  # Placeholder for mouth position
                    all_data.append(row)

                # Add mouth data
                for time_ms, position in mouth_data:
                    if eye_data:
                        row = [time_ms, "mouth", None, None, None, None, None, position]
                    else:
                        row = [time_ms, "mouth", position]
                    all_data.append(row)

                # Sort by timestamp and write
                all_data.sort(key=lambda x: x[0])
                writer.writerows(all_data)

            return True

        except Exception as e:
            print(f"Error saving file: {e}")
            return False

    @staticmethod
    def load_from_csv(filename: str) -> Tuple[List[EyeFrame], List[MouthFrame]]:
        """Load eye and mouth animation data from CSV file"""
        eye_frames = []
        mouth_frames = []

        with open(filename, "r", newline="") as csvfile:
            reader = csv.DictReader(csvfile)

            # Validate header
            required_fields = {"time_ms", "type"}
            if not required_fields.issubset(set(reader.fieldnames)):
                raise ValueError("Invalid file format: missing required fields")

            # Process each row
            for row in reader:
                time_ms = int(row["time_ms"])
                frame_type = row["type"]

                if frame_type == "eye":
                    eye_frames.append(
                        EyeFrame(
                            time_ms=time_ms,
                            x=float(row["eye_x"]) if row["eye_x"] != "None" else 0.5,
                            y=float(row["eye_y"]) if row["eye_y"] != "None" else 0.5,
                            left_closed=row["left_eye_closed"].lower() == "true",
                            right_closed=row["right_eye_closed"].lower() == "true",
                            both_closed=row["both_eyes_closed"].lower() == "true",
                        )
                    )
                elif frame_type == "mouth":
                    mouth_frames.append(
                        MouthFrame(
                            time_ms=time_ms,
                            position=(
                                int(float(row["mouth_position"]))
                                if row["mouth_position"] != "None"
                                else 128
                            ),
                        )
                    )

        return eye_frames, mouth_frames


class UDPProtocol:
    """Handles encoding and decoding of UDP messages"""

    @staticmethod
    def encode_eye_message(command_type: CommandType, *args) -> bytes:
        """Encode a message for the eye controller"""
        if command_type.format_str is None:
            return command_type.code
        return command_type.code + struct.pack(command_type.format_str, *args)

    @staticmethod
    def encode_mouth_message(position: int) -> bytes:
        """Encode a message for the mouth controller"""
        return CommandType.MOUTH_POSITION.code + struct.pack("B", position)

    @staticmethod
    def encode_eye_position(x: float, y: float) -> bytes:
        """Encode eye position (convenience method)"""
        x_byte = int(float(x) * 255)
        y_byte = int(float(y) * 255)
        return UDPProtocol.encode_eye_message(CommandType.EYE_POSITION, x_byte, y_byte)

    @staticmethod
    def encode_mouth_position(position: int) -> bytes:
        """Encode mouth position (convenience method)"""
        return UDPProtocol.encode_mouth_message(position)


# Network defaults
DEFAULT_HOST = "127.0.0.1"
DEFAULT_EYE_PORT = 5005
DEFAULT_MOUTH_PORT = 5006
