#!/usr/bin/env python3
"""Local maintenance CLI using the same interruptible engine as the HTTP owner.

Do not run this while the prepared-head service owns the local UDP/audio outputs.
The authoring editor and .skelanim format are unchanged.
"""
import argparse
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nightweaver_head.bundle import inspect
from nightweaver_head.engine import BundlePlayer, PygamePorts
from nightweaver_head.ownership import OutputLock


def main():
    parser = argparse.ArgumentParser(description='Local maintenance animation playback (exclusive owner required)')
    parser.add_argument('filename')
    parser.add_argument('--sink-name', required=True, help='explicit configured PulseAudio sink')
    parser.add_argument('--eye-port', type=int, default=5005)
    parser.add_argument('--mouth-port', type=int, default=5006)
    parser.add_argument('--loop', action='store_true')
    parser.add_argument('--no-resume-auto', action='store_true')
    parser.add_argument('--start-delay', type=int, default=0, help='local motion delay in milliseconds')
    args = parser.parse_args()
    if not -5000 <= args.start_delay <= 5000:
        parser.error('motion delay must be within +/-5000ms')
    bundle = inspect(Path(args.filename).read_bytes())
    ownership = OutputLock()
    ports = PygamePorts(args.sink_name, args.eye_port, args.mouth_port)
    cancel = threading.Event()
    try:
        ports.initialize()
        if bundle.audio:
            ports.verify(bundle.audio)
        import signal
        signal.signal(signal.SIGINT, lambda *_: cancel.set())
        signal.signal(signal.SIGTERM, lambda *_: cancel.set())
        failure = BundlePlayer(ports).run(bundle, cancel, args.start_delay * 1000, not args.no_resume_auto, args.loop)
        if failure:
            raise SystemExit(failure)
    finally:
        ports.close()
        ownership.close()


if __name__ == '__main__':
    main()
