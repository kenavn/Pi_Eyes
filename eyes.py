#!/usr/bin/python

# This script is heavily modified from the original eyes.py script
# It enables UDP communication to control the eyes, replacing the GPIO inputs (KAvner)

# This is a hasty port of the Teensy eyes code to Python...all kludgey with
# an embarrassing number of globals in the frame() function and stuff.
# Needed to get SOMETHING working, can focus on improvements next.
# Requires adafruit-blinka (CircuitPython APIs for Python on big hardware)

import socket
import struct
from queue import Queue, Empty
import platform
import os

import argparse
import math
import pi3d
import random
import threading
import time
from svg.path import Path, parse_path
from xml.dom.minidom import parse
from gfxutil import *


# Control variables (replace GPIO inputs)
auto_movement = True
auto_blink = True
auto_pupil = True
joystick_x = 0
joystick_y = 0
blink_left = False
blink_right = False
blink_left_active = False
blink_right_active = False
joystick_connected = False
prev_auto_movement = True
prev_auto_blink = True
prev_auto_pupil = True
left_eyelid_position = 0.0  # 0.0 is fully open, 1.0 is fully closed
right_eyelid_position = 0.0

# INPUT CONFIG for eye motion ----------------------------------------------
# ANALOG INPUTS REQUIRE SNAKE EYES BONNET (Which is disabled in this version - replaced with UDP)

JOYSTICK_X_IN = -1    # Analog input for eye horiz pos (-1 = auto)
JOYSTICK_Y_IN = -1    # Analog input for eye vert position (")
PUPIL_IN = -1    # Analog input for pupil control (-1 = auto)
JOYSTICK_X_FLIP = False  # If True, reverse stick X axis
JOYSTICK_Y_FLIP = False  # If True, reverse stick Y axis
PUPIL_IN_FLIP = False  # If True, reverse reading from PUPIL_IN
TRACKING = True  # If True, eyelid tracks pupil
PUPIL_SMOOTH = 16    # If > 0, filter input from PUPIL_IN
PUPIL_MIN = 0.0   # Lower analog range from PUPIL_IN
PUPIL_MAX = 1.0   # Upper "
WINK_L_PIN = None    # GPIO pin for LEFT eye wink button
BLINK_PIN = None    # GPIO pin for blink button (BOTH eyes)
WINK_R_PIN = None    # GPIO pin for RIGHT eye wink button
AUTOBLINK = True  # If True, eyes blink autonomously
CRAZY_EYES = False  # If True, each eye moves in different directions


# Load SVG file, extract paths & convert to point lists --------------------

dom = parse("graphics/eye.svg")
vb = get_view_box(dom)
pupilMinPts = get_points(dom, "pupilMin", 32, True, True)
pupilMaxPts = get_points(dom, "pupilMax", 32, True, True)
irisPts = get_points(dom, "iris", 32, True, True)
scleraFrontPts = get_points(dom, "scleraFront",  0, False, False)
scleraBackPts = get_points(dom, "scleraBack",  0, False, False)
upperLidClosedPts = get_points(dom, "upperLidClosed", 33, False, True)
upperLidOpenPts = get_points(dom, "upperLidOpen", 33, False, True)
upperLidEdgePts = get_points(dom, "upperLidEdge", 33, False, False)
lowerLidClosedPts = get_points(dom, "lowerLidClosed", 33, False, False)
lowerLidOpenPts = get_points(dom, "lowerLidOpen", 33, False, False)
lowerLidEdgePts = get_points(dom, "lowerLidEdge", 33, False, False)


# Set up display and initialize pi3d ---------------------------------------

def is_raspberry_pi():
    try:
        with open('/sys/firmware/devicetree/base/model', 'r') as m:
            if 'raspberry pi' in m.read().lower():
                return True
    except Exception:
        pass
    return platform.machine().startswith('arm') or platform.machine().startswith('aarch')

# This will initialize the display with fullscreen 4x antialiasing on a Raspberry Pi
# and windowed with no antialiasing on other platforms.
if is_raspberry_pi():
    DISPLAY = pi3d.Display.create(samples=4)
else:
    DISPLAY = pi3d.Display.create(x=100, y=100, w=800, h=600)

DISPLAY.set_background(0, 0, 0, 1)  # r,g,b,alpha

# eyeRadius is the size, in pixels, at which the whole eye will be rendered
# onscreen.  eyePosition, also pixels, is the offset (left or right) from
# the center point of the screen to the center of each eye.  This geometry
# is explained more in-depth in fbx2.c.
eyePosition = DISPLAY.width / 4
eyeRadius = 128  # Default; use 240 for IPS screens

parser = argparse.ArgumentParser()
parser.add_argument("--radius", type=int)
args, _ = parser.parse_known_args()
if args.radius:
    eyeRadius = args.radius


# A 2D camera is used, mostly to allow for pixel-accurate eye placement,
# but also because perspective isn't really helpful or needed here, and
# also this allows eyelids to be handled somewhat easily as 2D planes.
# Line of sight is down Z axis, allowing conventional X/Y cartesion
# coords for 2D positions.
cam = pi3d.Camera(is_3d=False, at=(0, 0, 0), eye=(0, 0, -1000))
shader = pi3d.Shader("uv_light")
light = pi3d.Light(lightpos=(0, -500, -500), lightamb=(0.2, 0.2, 0.2))


# Load texture maps --------------------------------------------------------

irisMap = pi3d.Texture("graphics/iris.jpg", mipmap=False,
                       filter=pi3d.constants.GL_LINEAR)
scleraMap = pi3d.Texture("graphics/sclera.png", mipmap=False,
                         filter=pi3d.constants.GL_LINEAR, blend=True)
lidMap = pi3d.Texture("graphics/lid.png", mipmap=False,
                      filter=pi3d.constants.GL_LINEAR, blend=True)
# U/V map may be useful for debugging texture placement; not normally used
# uvMap     = pi3d.Texture("graphics/uv.png"    , mipmap=False,
#              filter=pi3d.constants.GL_LINEAR, blend=False, m_repeat=True)


# Initialize static geometry -----------------------------------------------

# Transform point lists to eye dimensions
scale_points(pupilMinPts, vb, eyeRadius)
scale_points(pupilMaxPts, vb, eyeRadius)
scale_points(irisPts, vb, eyeRadius)
scale_points(scleraFrontPts, vb, eyeRadius)
scale_points(scleraBackPts, vb, eyeRadius)
scale_points(upperLidClosedPts, vb, eyeRadius)
scale_points(upperLidOpenPts, vb, eyeRadius)
scale_points(upperLidEdgePts, vb, eyeRadius)
scale_points(lowerLidClosedPts, vb, eyeRadius)
scale_points(lowerLidOpenPts, vb, eyeRadius)
scale_points(lowerLidEdgePts, vb, eyeRadius)

# Regenerating flexible object geometry (such as eyelids during blinks, or
# iris during pupil dilation) is CPU intensive, can noticably slow things
# down, especially on single-core boards.  To reduce this load somewhat,
# determine a size change threshold below which regeneration will not occur;
# roughly equal to 1/4 pixel, since 4x4 area sampling is used.

# Determine change in pupil size to trigger iris geometry regen
irisRegenThreshold = 0.0
a = points_bounds(pupilMinPts)  # Bounds of pupil at min size (in pixels)
b = points_bounds(pupilMaxPts)  # " at max size
maxDist = max(abs(a[0] - b[0]), abs(a[1] - b[1]),  # Determine distance of max
              abs(a[2] - b[2]), abs(a[3] - b[3]))  # variance around each edge
# maxDist is motion range in pixels as pupil scales between 0.0 and 1.0.
# 1.0 / maxDist is one pixel's worth of scale range.  Need 1/4 that...
if maxDist > 0:
    irisRegenThreshold = 0.25 / maxDist

# Determine change in eyelid values needed to trigger geometry regen.
# This is done a little differently than the pupils...instead of bounds,
# the distance between the middle points of the open and closed eyelid
# paths is evaluated, then similar 1/4 pixel threshold is determined.
upperLidRegenThreshold = 0.0
lowerLidRegenThreshold = 0.0
p1 = upperLidOpenPts[len(upperLidOpenPts) // 2]
p2 = upperLidClosedPts[len(upperLidClosedPts) // 2]
dx = p2[0] - p1[0]
dy = p2[1] - p1[1]
d = dx * dx + dy * dy
if d > 0:
    upperLidRegenThreshold = 0.25 / math.sqrt(d)
p1 = lowerLidOpenPts[len(lowerLidOpenPts) // 2]
p2 = lowerLidClosedPts[len(lowerLidClosedPts) // 2]
dx = p2[0] - p1[0]
dy = p2[1] - p1[1]
d = dx * dx + dy * dy
if d > 0:
    lowerLidRegenThreshold = 0.25 / math.sqrt(d)

# Generate initial iris meshes; vertex elements will get replaced on
# a per-frame basis in the main loop, this just sets up textures, etc.
rightIris = mesh_init((32, 4), (0, 0.5 / irisMap.iy), True, False)
rightIris.set_textures([irisMap])
rightIris.set_shader(shader)
# Left iris map U value is offset by 0.5; effectively a 180 degree
# rotation, so it's less obvious that the same texture is in use on both.
leftIris = mesh_init((32, 4), (0.5, 0.5 / irisMap.iy), True, False)
leftIris.set_textures([irisMap])
leftIris.set_shader(shader)
irisZ = zangle(irisPts, eyeRadius)[0] * 0.99  # Get iris Z depth, for later

# Eyelid meshes are likewise temporary; texture coordinates are
# assigned here but geometry is dynamically regenerated in main loop.
leftUpperEyelid = mesh_init((33, 5), (0, 0.5 / lidMap.iy), False, True)
leftUpperEyelid.set_textures([lidMap])
leftUpperEyelid.set_shader(shader)
leftLowerEyelid = mesh_init((33, 5), (0, 0.5 / lidMap.iy), False, True)
leftLowerEyelid.set_textures([lidMap])
leftLowerEyelid.set_shader(shader)

rightUpperEyelid = mesh_init((33, 5), (0, 0.5 / lidMap.iy), False, True)
rightUpperEyelid.set_textures([lidMap])
rightUpperEyelid.set_shader(shader)
rightLowerEyelid = mesh_init((33, 5), (0, 0.5 / lidMap.iy), False, True)
rightLowerEyelid.set_textures([lidMap])
rightLowerEyelid.set_shader(shader)

# Generate scleras for each eye...start with a 2D shape for lathing...
angle1 = zangle(scleraFrontPts, eyeRadius)[1]  # Sclera front angle
angle2 = zangle(scleraBackPts, eyeRadius)[1]  # " back angle
aRange = 180 - angle1 - angle2
pts = []

# ADD EXTRA INITIAL POINT because of some weird behavior with Pi3D and
# VideoCore VI with the Lathed shapes we make later. This adds a *tiny*
# ring of extra polygons that simply disappear on screen. It's not
# necessary on VC4, but not harmful either, so we just do it rather
# than try to be all clever.
ca, sa = pi3d.Utility.from_polar((90 - angle1) + aRange * 0.0001)
pts.append((ca * eyeRadius, sa * eyeRadius))

for i in range(24):
    ca, sa = pi3d.Utility.from_polar((90 - angle1) - aRange * i / 23)
    pts.append((ca * eyeRadius, sa * eyeRadius))

# Scleras are generated independently (object isn't re-used) so each
# may have a different image map (heterochromia, corneal scar, or the
# same image map can be offset on one so the repetition isn't obvious).
leftEye = pi3d.Lathe(path=pts, sides=64)
leftEye.set_textures([scleraMap])
leftEye.set_shader(shader)
re_axis(leftEye, 0)
rightEye = pi3d.Lathe(path=pts, sides=64)
rightEye.set_textures([scleraMap])
rightEye.set_shader(shader)
re_axis(rightEye, 0.5)  # Image map offset = 180 degree rotation


# UDP settings
UDP_IP = "0.0.0.0"  # Listen on all available interfaces
UDP_PORT = 5005  # Choose an appropriate port

# Create a UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.setblocking(0)  # Set socket to non-blocking mode

# Create a queue for message passing between threads
message_queue = Queue()


# Thread for handling UDP messages
def udp_thread():
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            message = decode_message(data)
            message_queue.put(message)
        except socket.error:
            time.sleep(0.01)  # Small sleep to prevent busy-waiting


# Start UDP thread
udp_thread = threading.Thread(target=udp_thread, daemon=True)
udp_thread.start()

# Unpack message data and return a string representation of the message


def decode_message(data):
    command_type = data[0]
    if command_type == 0x00:
        return "joystick_disconnected"
    elif command_type == 0x01:
        return "joystick_connected"
    elif command_type == 0x10:
        return "auto_movement_off"
    elif command_type == 0x11:
        return "auto_movement_on"
    elif command_type == 0x12:
        return "auto_blink_off"
    elif command_type == 0x13:
        return "auto_blink_on"
    elif command_type == 0x14:
        return "auto_pupil_off"
    elif command_type == 0x15:
        return "auto_pupil_on"
    elif command_type == 0x20:
        x, y = struct.unpack('BB', data[1:3])
        return f"joystick,{x/255:.2f},{y/255:.2f}"
    elif command_type == 0x30:
        position, = struct.unpack('B', data[1:2])
        return f"left_eyelid,{position/255:.2f}"
    elif command_type == 0x31:
        position, = struct.unpack('B', data[1:2])
        return f"right_eyelid,{position/255:.2f}"
    elif command_type == 0x40:
        return "blink_left_start"
    elif command_type == 0x41:
        return "blink_left_end"
    elif command_type == 0x42:
        return "blink_right_start"
    elif command_type == 0x43:
        return "blink_right_end"
    elif command_type == 0x44:
        return "blink_both_start"
    elif command_type == 0x45:
        return "blink_both_end"
    else:
        raise ValueError(f"Unknown command type: {command_type}")

# Function to process UDP messages


def process_udp_messages():
    global auto_movement, auto_blink, auto_pupil, joystick_x, joystick_y
    global joystick_connected, prev_auto_movement, prev_auto_blink, prev_auto_pupil
    global left_eyelid_position, right_eyelid_position
    global blink_left_active, blink_right_active
    try:
        while True:
            message = message_queue.get_nowait()
            if message == "joystick_connected":
                joystick_connected = True
                prev_auto_movement = auto_movement
                prev_auto_blink = auto_blink
                prev_auto_pupil = auto_pupil
                auto_movement = False
            elif message == "joystick_disconnected":
                joystick_connected = False
                auto_movement = prev_auto_movement
                auto_blink = prev_auto_blink
                auto_pupil = prev_auto_pupil
            elif message == "auto_movement_on":
                if not joystick_connected:
                    auto_movement = True
                prev_auto_movement = True
            elif message == "auto_movement_off":
                if not joystick_connected:
                    auto_movement = False
                prev_auto_movement = False
            elif message == "auto_blink_on":
                if not joystick_connected:
                    auto_blink = True
                prev_auto_blink = True
            elif message == "auto_blink_off":
                if not joystick_connected:
                    auto_blink = False
                prev_auto_blink = False
            elif message == "auto_pupil_on":
                if not joystick_connected:
                    auto_pupil = True
                prev_auto_pupil = True
            elif message == "auto_pupil_off":
                if not joystick_connected:
                    auto_pupil = False
                prev_auto_pupil = False
            elif message.startswith("left_eyelid"):
                _, position = message.split(',')
                left_eyelid_position = float(position)
            elif message.startswith("right_eyelid"):
                _, position = message.split(',')
                right_eyelid_position = float(position)
            elif message.startswith("joystick"):
                if joystick_connected:
                    _, x, y = message.split(',')
                    joystick_x = float(x)
                    joystick_y = float(y)
            elif message == "blink_left_start":
                blink_left_active = True
            elif message == "blink_left_end":
                blink_left_active = False
            elif message == "blink_right_start":
                blink_right_active = True
            elif message == "blink_right_end":
                blink_right_active = False
            elif message == "blink_both_start":
                blink_left_active = True
                blink_right_active = True
            elif message == "blink_both_end":
                blink_left_active = False
                blink_right_active = False
    except Empty:
        pass


# Init global stuff --------------------------------------------------------
mykeys = pi3d.Keyboard()  # For capturing key presses

startX = random.uniform(-30.0, 30.0)
n = math.sqrt(900.0 - startX * startX)
startY = random.uniform(-n, n)
destX = startX
destY = startY
curX = startX
curY = startY
moveDuration = random.uniform(0.075, 0.175)
holdDuration = random.uniform(0.1, 1.1)
startTime = 0.0
isMoving = False

startXR = random.uniform(-30.0, 30.0)
n = math.sqrt(900.0 - startX * startX)
startYR = random.uniform(-n, n)
destXR = startXR
destYR = startYR
curXR = startXR
curYR = startYR
moveDurationR = random.uniform(0.075, 0.175)
holdDurationR = random.uniform(0.1, 1.1)
startTimeR = 0.0
isMovingR = False

frames = 0
beginningTime = time.time()

rightEye.positionX(-eyePosition)
rightIris.positionX(-eyePosition)
rightUpperEyelid.positionX(-eyePosition)
rightUpperEyelid.positionZ(-eyeRadius - 42)
rightLowerEyelid.positionX(-eyePosition)
rightLowerEyelid.positionZ(-eyeRadius - 42)

leftEye.positionX(eyePosition)
leftIris.positionX(eyePosition)
leftUpperEyelid.positionX(eyePosition)
leftUpperEyelid.positionZ(-eyeRadius - 42)
leftLowerEyelid.positionX(eyePosition)
leftLowerEyelid.positionZ(-eyeRadius - 42)

currentPupilScale = 0.5
prevPupilScale = -1.0  # Force regen on first frame
prevLeftUpperLidWeight = 0.5
prevLeftLowerLidWeight = 0.5
prevRightUpperLidWeight = 0.5
prevRightLowerLidWeight = 0.5
prevLeftUpperLidPts = points_interp(upperLidOpenPts, upperLidClosedPts, 0.5)
prevLeftLowerLidPts = points_interp(lowerLidOpenPts, lowerLidClosedPts, 0.5)
prevRightUpperLidPts = points_interp(upperLidOpenPts, upperLidClosedPts, 0.5)
prevRightLowerLidPts = points_interp(lowerLidOpenPts, lowerLidClosedPts, 0.5)

luRegen = True
llRegen = True
ruRegen = True
rlRegen = True

timeOfLastBlink = 0.0
timeToNextBlink = 1.0
# These are per-eye (left, right) to allow winking:
blinkStateLeft = 0  # NOBLINK
blinkStateRight = 0
blinkDurationLeft = 0.1
blinkDurationRight = 0.1
blinkStartTimeLeft = 0
blinkStartTimeRight = 0

trackingPos = 0.3
trackingPosR = 0.3

# Generate one frame of imagery


def frame(p):
    global blink_left, blink_right
    global blink_left_active, blink_right_active
    global left_eyelid_position, right_eyelid_position
    global startX, startY, destX, destY, curX, curY
    global startXR, startYR, destXR, destYR, curXR, curYR
    global moveDuration, holdDuration, startTime, isMoving
    global moveDurationR, holdDurationR, startTimeR, isMovingR
    global frames
    global leftIris, rightIris
    global pupilMinPts, pupilMaxPts, irisPts, irisZ
    global leftEye, rightEye
    global leftUpperEyelid, leftLowerEyelid, rightUpperEyelid, rightLowerEyelid
    global upperLidOpenPts, upperLidClosedPts, lowerLidOpenPts, lowerLidClosedPts
    global upperLidEdgePts, lowerLidEdgePts
    global prevLeftUpperLidPts, prevLeftLowerLidPts, prevRightUpperLidPts, prevRightLowerLidPts
    global leftUpperEyelid, leftLowerEyelid, rightUpperEyelid, rightLowerEyelid
    global prevLeftUpperLidWeight, prevLeftLowerLidWeight, prevRightUpperLidWeight, prevRightLowerLidWeight
    global prevPupilScale
    global irisRegenThreshold, upperLidRegenThreshold, lowerLidRegenThreshold
    global luRegen, llRegen, ruRegen, rlRegen
    global timeOfLastBlink, timeToNextBlink
    global blinkStateLeft, blinkStateRight
    global blinkDurationLeft, blinkDurationRight
    global blinkStartTimeLeft, blinkStartTimeRight
    global trackingPos
    global trackingPosR

    # Process UDP messages
    process_udp_messages()

    DISPLAY.loop_running()

    now = time.time()
    dt = now - startTime
    dtR = now - startTimeR

    frames += 1

    # Function to start a blink
    def start_blink(eye):
        global blinkStateLeft, blinkStateRight, blinkStartTimeLeft, blinkStartTimeRight, blinkDurationLeft, blinkDurationRight
        nonlocal now
        duration = random.uniform(0.035, 0.06)
        if eye in ['left', 'both'] and blinkStateLeft == 0:
            blinkStateLeft = 1  # ENBLINK
            blinkStartTimeLeft = now
            blinkDurationLeft = duration
        if eye in ['right', 'both'] and blinkStateRight == 0:
            blinkStateRight = 1  # ENBLINK
            blinkStartTimeRight = now
            blinkDurationRight = duration

    if (not auto_movement) or joystick_connected:
        # Eye position from UDP input
        curX = -30.0 + joystick_x * 60.0
        curY = -30.0 + joystick_y * 60.0
    else:
        # Autonomous eye position
        if isMoving == True:
            if dt <= moveDuration:
                scale = (now - startTime) / moveDuration
                # Ease in/out curve: 3*t^2-2*t^3
                scale = 3.0 * scale * scale - 2.0 * scale * scale * scale
                curX = startX + (destX - startX) * scale
                curY = startY + (destY - startY) * scale
            else:
                startX = destX
                startY = destY
                curX = destX
                curY = destY
                holdDuration = random.uniform(0.1, 1.1)
                startTime = now
                isMoving = False
        else:
            if dt >= holdDuration:
                destX = random.uniform(-30.0, 30.0)
                n = math.sqrt(900.0 - destX * destX)
                destY = random.uniform(-n, n)
                moveDuration = random.uniform(0.075, 0.175)
                startTime = now
                isMoving = True

        # repeat for other eye if CRAZY_EYES
    if CRAZY_EYES:
        if isMovingR == True:
            if dtR <= moveDurationR:
                scale = (now - startTimeR) / moveDurationR
                # Ease in/out curve: 3*t^2-2*t^3
                scale = 3.0 * scale * scale - 2.0 * scale * scale * scale
                curXR = startXR + (destXR - startXR) * scale
                curYR = startYR + (destYR - startYR) * scale
            else:
                startXR = destXR
                startYR = destYR
                curXR = destXR
                curYR = destYR
                holdDurationR = random.uniform(0.1, 1.1)
                startTimeR = now
                isMovingR = False
        else:
            if dtR >= holdDurationR:
                destXR = random.uniform(-30.0, 30.0)
                n = math.sqrt(900.0 - destXR * destXR)
                destYR = random.uniform(-n, n)
                moveDurationR = random.uniform(0.075, 0.175)
                startTimeR = now
                isMovingR = True

    # Regenerate iris geometry only if size changed by >= 1/4 pixel
    if abs(p - prevPupilScale) >= irisRegenThreshold:
        # Interpolate points between min and max pupil sizes
        interPupil = points_interp(pupilMinPts, pupilMaxPts, p)
        # Generate mesh between interpolated pupil and iris bounds
        mesh = points_mesh((None, interPupil, irisPts), 4, -irisZ, True)
        # Assign to both eyes
        leftIris.re_init(pts=mesh)
        rightIris.re_init(pts=mesh)
        prevPupilScale = p

    # Eyelid WIP

    if blink_left_active:
        left_eyelid_position = 1.0
    else:
        left_eyelid_position = 0.0

    if blink_right_active:
        right_eyelid_position = 1.0
    else:
        right_eyelid_position = 0.0

    if BLINK_PIN is not None and BLINK_PIN.value == False:
        duration = random.uniform(0.035, 0.06)
        if blinkStateLeft == 0:
            blinkStateLeft = 1
            blinkStartTimeLeft = now
            blinkDurationLeft = duration
        if blinkStateRight == 0:
            blinkStateRight = 1
            blinkStartTimeRight = now
            blinkDurationRight = duration

    # Calculate eyelid positions
    if TRACKING:
        n = 0.4 - curY / 60.0
        n = max(0, min(1, n))
        trackingPos = (trackingPos * 3.0 + n) * 0.25
        if CRAZY_EYES:
            n = 0.4 - curYR / 60.0
            n = max(0, min(1, n))
            trackingPosR = (trackingPosR * 3.0 + n) * 0.25

    # Update eyelid positions based on blink state and tracking
    if blink_left_active:
        leftUpperLidWeight = 1.0
        leftLowerLidWeight = 1.0
    else:
        leftUpperLidWeight = trackingPos
        leftLowerLidWeight = 1.0 - trackingPos

    if blink_right_active:
        rightUpperLidWeight = 1.0
        rightLowerLidWeight = 1.0
    else:
        rightUpperLidWeight = trackingPos if not CRAZY_EYES else trackingPosR
        rightLowerLidWeight = 1.0 - \
            (trackingPos if not CRAZY_EYES else trackingPosR)

    # Use UDP-controlled eyelid positions if auto_blink is off and eyes are not actively blinking
    if not auto_blink and not (blink_left_active or blink_right_active):
        leftUpperLidWeight = left_eyelid_position
        leftLowerLidWeight = left_eyelid_position
        rightUpperLidWeight = right_eyelid_position
        rightLowerLidWeight = right_eyelid_position

    # Update eyelid meshes
    if (luRegen or (abs(leftUpperLidWeight - prevLeftUpperLidWeight) >=
                    upperLidRegenThreshold)):
        newLeftUpperLidPts = points_interp(upperLidOpenPts,
                                           upperLidClosedPts, leftUpperLidWeight)
        if leftUpperLidWeight > prevLeftUpperLidWeight:
            leftUpperEyelid.re_init(pts=points_mesh(
                (upperLidEdgePts, prevLeftUpperLidPts,
                 newLeftUpperLidPts), 5, 0, False))
        else:
            leftUpperEyelid.re_init(pts=points_mesh(
                (upperLidEdgePts, newLeftUpperLidPts,
                 prevLeftUpperLidPts), 5, 0, False))
        prevLeftUpperLidPts = newLeftUpperLidPts
        prevLeftUpperLidWeight = leftUpperLidWeight
        luRegen = True
    else:
        luRegen = False

    if (llRegen or (abs(leftLowerLidWeight - prevLeftLowerLidWeight) >=
                    lowerLidRegenThreshold)):
        newLeftLowerLidPts = points_interp(lowerLidOpenPts,
                                           lowerLidClosedPts, leftLowerLidWeight)
        if leftLowerLidWeight > prevLeftLowerLidWeight:
            leftLowerEyelid.re_init(pts=points_mesh(
                (lowerLidEdgePts, prevLeftLowerLidPts,
                 newLeftLowerLidPts), 5, 0, False))
        else:
            leftLowerEyelid.re_init(pts=points_mesh(
                (lowerLidEdgePts, newLeftLowerLidPts,
                 prevLeftLowerLidPts), 5, 0, False))
        prevLeftLowerLidWeight = leftLowerLidWeight
        prevLeftLowerLidPts = newLeftLowerLidPts
        llRegen = True
    else:
        llRegen = False

    if (ruRegen or (abs(rightUpperLidWeight - prevRightUpperLidWeight) >=
                    upperLidRegenThreshold)):
        newRightUpperLidPts = points_interp(upperLidOpenPts,
                                            upperLidClosedPts, rightUpperLidWeight)
        if rightUpperLidWeight > prevRightUpperLidWeight:
            rightUpperEyelid.re_init(pts=points_mesh(
                (upperLidEdgePts, prevRightUpperLidPts,
                 newRightUpperLidPts), 5, 0, True))
        else:
            rightUpperEyelid.re_init(pts=points_mesh(
                (upperLidEdgePts, newRightUpperLidPts,
                 prevRightUpperLidPts), 5, 0, True))
        prevRightUpperLidWeight = rightUpperLidWeight
        prevRightUpperLidPts = newRightUpperLidPts
        ruRegen = True
    else:
        ruRegen = False

    if (rlRegen or (abs(rightLowerLidWeight - prevRightLowerLidWeight) >=
                    lowerLidRegenThreshold)):
        newRightLowerLidPts = points_interp(lowerLidOpenPts,
                                            lowerLidClosedPts, rightLowerLidWeight)
        if rightLowerLidWeight > prevRightLowerLidWeight:
            rightLowerEyelid.re_init(pts=points_mesh(
                (lowerLidEdgePts, prevRightLowerLidPts,
                 newRightLowerLidPts), 5, 0, True))
        else:
            rightLowerEyelid.re_init(pts=points_mesh(
                (lowerLidEdgePts, newRightLowerLidPts,
                 prevRightLowerLidPts), 5, 0, True))
        prevRightLowerLidWeight = rightLowerLidWeight
        prevRightLowerLidPts = newRightLowerLidPts
        rlRegen = True
    else:
        rlRegen = False

    convergence = 2.0

    # Right eye (on screen left)
    if CRAZY_EYES:
        rightIris.rotateToX(curYR)
        rightIris.rotateToY(curXR - convergence)
        rightIris.draw()
        rightEye.rotateToX(curYR)
        rightEye.rotateToY(curXR - convergence)
    else:
        rightIris.rotateToX(curY)
        rightIris.rotateToY(curX - convergence)
        rightIris.draw()
        rightEye.rotateToX(curY)
        rightEye.rotateToY(curX - convergence)
    rightEye.draw()

    # Left eye (on screen right)

    leftIris.rotateToX(curY)
    leftIris.rotateToY(curX + convergence)
    leftIris.draw()
    leftEye.rotateToX(curY)
    leftEye.rotateToY(curX + convergence)
    leftEye.draw()

    leftUpperEyelid.draw()
    leftLowerEyelid.draw()
    rightUpperEyelid.draw()
    rightLowerEyelid.draw()

    k = mykeys.read()
    if k == 27:
        mykeys.close()
        DISPLAY.stop()
        exit(0)


def split(  # Recursive simulated pupil response when no analog sensor
        startValue,  # Pupil scale starting value (0.0 to 1.0)
        endValue,   # Pupil scale ending value (")
        duration,   # Start-to-end time, floating-point seconds
        range):     # +/- random pupil scale at midpoint
    startTime = time.time()
    if range >= 0.125:  # Limit subdvision count, because recursion
        duration *= 0.5  # Split time & range in half for subdivision,
        range *= 0.5  # then pick random center point within range:
        midValue = ((startValue + endValue - range) * 0.5 +
                    random.uniform(0.0, range))
        split(startValue, midValue, duration, range)
        split(midValue, endValue, duration, range)
    else:  # No more subdivisons, do iris motion...
        dv = endValue - startValue
        while True:
            dt = time.time() - startTime
            if dt >= duration:
                break
            v = startValue + dv * dt / duration
            if v < PUPIL_MIN:
                v = PUPIL_MIN
            elif v > PUPIL_MAX:
                v = PUPIL_MAX
            frame(v)  # Draw frame w/interim pupil scale value


# MAIN LOOP -- runs continuously -------------------------------------------

while True:
    if PUPIL_IN >= 0:
        # If you implement UDP control for pupil scale, modify this part
        v = 0.5  # Default value, replace with UDP-controlled value if implemented
        if PUPIL_SMOOTH > 0:
            v = ((currentPupilScale * (PUPIL_SMOOTH - 1) + v) / PUPIL_SMOOTH)
        frame(v)
    else:
        if auto_pupil:
            # Keep the fractal auto pupil scale as is
            v = random.random()
            split(currentPupilScale, v, 4.0, 1.0)
        else:
            # Use a fixed pupil size when auto_pupil is off
            v = 0.5  # You can adjust this value or make it controllable via UDP
        frame(v)
    currentPupilScale = v
