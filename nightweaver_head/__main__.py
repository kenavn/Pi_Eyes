"""Installation-owned configuration only; never connects or actuates on import."""
import argparse
import asyncio
import hashlib
import os
from pathlib import Path
import signal
import stat
import subprocess
from .engine import PygamePorts
from .http import HTTPServer
from .service import Service
from .ownership import OutputLock
from .wire import decode


def private_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o027 or info.st_size > 65536:
            raise ValueError('configuration and credential require root ownership and private permissions')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            return stream.read(65537)
    finally:
        os.close(fd)


def load_config(path):
    value = decode(private_file(path))
    required = {'bind', 'port', 'interface', 'secret_file', 'content_root', 'local_library_root',
                'sink_name', 'source_revision'}
    if type(value) is not dict or set(value) != required:
        raise ValueError('invalid configuration fields')
    if value['bind'] not in ('192.168.2.119', '192.168.2.53') or value['port'] != 8082:
        raise ValueError('reserved Show Ethernet address and port8082 required')
    for field in ('secret_file', 'content_root', 'local_library_root'):
        if not Path(value[field]).is_absolute():
            raise ValueError('installation paths must be absolute')
    if any(type(value[field]) is not str or not value[field] or len(value[field]) > 256
           for field in ('interface', 'sink_name', 'source_revision')):
        raise ValueError('invalid installation label')
    return value


def check_route(config):
    # This is non-actuating; no generic site/bootstrap or network mutation.
    result = subprocess.run(['ip', '-4', 'route', 'get', '192.168.2.235', 'from', config['bind']],
                            check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2)
    words = result.stdout.decode('ascii').split()
    if ('dev' not in words or words[words.index('dev') + 1] != config['interface']
            or 'src' in words and words[words.index('src') + 1] != config['bind']):
        raise ValueError('Show Ethernet audio route unavailable')


def build_hash():
    digest = hashlib.sha256()
    root = Path(__file__).parent
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.suffix in ('.py', '.json'):
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


async def serve(config):
    check_route(config)
    ownership = OutputLock()
    secret = private_file(config['secret_file']).decode('utf-8').strip()
    os.environ['PULSE_SERVER'] = 'tcp:192.168.2.235:4713'
    os.environ['PULSE_SINK'] = config['sink_name']
    ports = PygamePorts(config['sink_name'], route_check=lambda: check_route(config))
    ports.initialize()
    service = Service(config['content_root'], ports, source_revision=config['source_revision'], build_sha256=build_hash())
    service.store.index_local(config['local_library_root'])
    server = HTTPServer(service, secret, config['bind'], config['port'])
    try:
        await server.start()
        stop = asyncio.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        await stop.wait()
    finally:
        settled = await server.close() if server.server else await service.shutdown()
        if not settled:
            # Keep process alive and service unavailable rather than allow a second owner.
            while not await service.shutdown():
                await asyncio.sleep(.1)
        ownership.close()


def main():
    parser = argparse.ArgumentParser(description='Prepared head HTTP service')
    parser.add_argument('--config', required=True, help='root-owned installation configuration file')
    args = parser.parse_args()
    try:
        asyncio.run(serve(load_config(args.config)))
    except (ValueError, OSError, subprocess.SubprocessError):
        raise SystemExit('Head service unavailable; verify private installation configuration and audio/route readiness') from None


if __name__ == '__main__':
    main()
