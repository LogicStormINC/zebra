"""Root-owned ERP-only quota allocator. No browser paths or commands are accepted."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import socketserver
import stat
import struct
import subprocess
import tempfile
import threading
import time
from uuid import UUID, uuid4

ROOT = Path('/var/lib/zebra/erpnext-private-workspaces')
STATE = Path('/var/lib/zebra/erpnext-private-volumes')
SIZE = 256 * 1024 * 1024
LIMIT = 32
FLOOR = 2 * 1024 * 1024 * 1024
MAX_BODY = 4096
BYTE_LIMIT = LIMIT * SIZE
REQUEST_SECONDS = 20
DEADLINE = ContextVar('allocator_deadline', default=None)


def remaining():
    deadline = DEADLINE.get()
    value = REQUEST_SECONDS if deadline is None else deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError('allocator deadline exceeded')
    return value


def require_fresh(expires_at):
    if type(expires_at) not in {int, float} or not math.isfinite(expires_at) or time.time() >= expires_at:
        raise ValueError('native fresh proof expired')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('noncanonical UUID')
    return value


def trusted(path, *, directory=True):
    """Root-controlled absolute ancestors, including the leaf; never follow symlinks."""
    if not path.is_absolute():
        raise ValueError('absolute trusted path required')
    for component in [*reversed(path.parents), path]:
        info = component.lstat()
        if (stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
                or (component != path or directory) and not stat.S_ISDIR(info.st_mode)
                or component == path and not directory and not stat.S_ISREG(info.st_mode)):
            raise ValueError('untrusted operator path')


def run(*args):
    return subprocess.check_output(args, text=True, timeout=remaining(), stderr=subprocess.DEVNULL).strip()


def mount_evidence(path):
    # findmnt -M is an exact mountpoint query, not the containing filesystem.
    report = json.loads(run('findmnt', '--json', '--mountpoint', str(path),
                            '--output', 'TARGET,SOURCE,FSTYPE,OPTIONS,UUID'))['filesystems']
    if len(report) != 1:
        raise ValueError('ambiguous mount')
    return report[0]


class NativeProof:
    def __init__(self, config):
        self.image = config['helper_image']
        if not isinstance(self.image, str) or re.fullmatch(r'(?:[a-zA-Z0-9./:_-]+@)?sha256:[0-9a-f]{64}', self.image) is None:
            raise ValueError('immutable native helper image digest required')
        generation = config.get('generation', 'native105')
        profiles = {'native105': ('erpnext-private-proof', 'zebra_agent_worker.erp_private_workspace_proof'),
                    'cloud114': ('erpnext-full-proof', 'full_workspace_proof'),
                    'cloud114-qa': ('erpnext-full-qa-proof', 'full_workspace_proof')}
        if generation not in profiles:
            raise ValueError('unknown runtime generation')
        self.network, self.module = profiles[generation]
        self.qa = generation == 'cloud114-qa'
        if config['helper_network'] != self.network:
            raise ValueError('dedicated proof network required')
        self.hostname = config.get('helper_hostname')
        if (not isinstance(self.hostname, str) or len(self.hostname) > 253
                or re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', self.hostname) is None
                or self.hostname.rsplit('.', 1)[-1].isdecimal()
                or 'localhost' in self.hostname.split('.')):
            raise ValueError('single canonical helper FQDN required')
        try:
            socket.getaddrinfo(self.hostname, None, flags=socket.AI_NUMERICHOST)
        except socket.gaierror:
            pass
        else:
            raise ValueError('numeric helper hostname forbidden')
        self.failed_cleanup = False
        self.credentials = dict(readonly_dsn=config['readonly_dsn'], shared_secret=config['host_tool_shared_secret'], ca_pem=None)
        if config.get('host_ca_file'):
            ca = Path(config['host_ca_file']); trusted(ca, directory=False)
            self.credentials['ca_pem'] = ca.read_text()

    def require_clean(self):
        names = subprocess.check_output(['docker', 'ps', '--all', '--filter', 'name=erp-private-proof-',
            '--format', '{{.Names}}'], text=True, timeout=3, stderr=subprocess.DEVNULL)
        if any(name.startswith('erp-private-proof-') for name in names.splitlines()):
            raise ValueError('orphan proof helper requires operator cleanup')

    def __call__(self, session_id, workspace_id):
        if self.failed_cleanup:
            raise ValueError('proof helper cleanup requires operator review')
        nonce = str(uuid4()); name = 'erp-private-proof-' + nonce
        packet = canonical(dict(self.credentials, session_id=session_id, workspace_id=workspace_id, nonce=nonce))
        if len(packet) > 16384:
            raise ValueError('bounded proof credentials required')
        argv = ['docker', 'run', '--pull=never', '--interactive', '--name', name,
                '--network', self.network,
                '--env', 'ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES=' + self.hostname,
                '--env', 'ZEBRA_FULL_QA=' + str(self.qa).lower(),
                '--user', '65532:65532', '--read-only',
                '--cap-drop=ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '32',
                '--memory', '256m', '--cpus', '1', '--entrypoint', '/app/.venv/bin/python',
                self.image, '-m', self.module]
        available = remaining()
        # ponytail: reserve 5s inside the 20s deadline; observed die-to-destroy was 3.798s.
        if available <= 5:
            raise TimeoutError('insufficient helper cleanup budget')
        try:
            output = subprocess.check_output(argv, input=packet, timeout=min(7, available - 5), stderr=subprocess.DEVNULL)
            if len(output) > 4096: raise ValueError('bounded proof response required')
            proof = json.loads(output)
            if (set(proof) != {'session_id', 'workspace_id', 'nonce', 'identity', 'state', 'expires_at'}
                    or proof['session_id'] != session_id or proof['workspace_id'] != workspace_id
                    or proof['nonce'] != nonce or proof['state'] not in {'pending', 'ready', 'sealed'}
                    or not isinstance(proof['identity'], str) or re.fullmatch('[0-9a-f]{64}', proof['identity']) is None):
                raise ValueError('native independent proof disagrees')
            require_fresh(proof['expires_at'])
            return proof['identity'], proof['state'], proof['expires_at']
        finally:
            # Killing docker's client does not kill its container. Bounded forced cleanup
            # has a unique fixed prefix and never touches Worker or business containers.
            try:
                result = subprocess.run(['docker', 'rm', '--force', name], timeout=min(5, remaining()),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                if result.returncode != 0:
                    raise ValueError('proof helper cleanup failed')
            except (OSError, subprocess.TimeoutExpired, TimeoutError, ValueError) as error:
                self.failed_cleanup = True
                raise ValueError('proof helper cleanup requires operator review') from error


class Allocator:
    def __init__(self, proof, *, root=ROOT, state=STATE, worker_uid=65532, floor=FLOOR):
        self.root, self.state, self.proof = root, state, proof
        self.worker_uid, self.floor = worker_uid, floor
        trusted(root); trusted(state)
        self.lock_path = state / 'allocation.lock'
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(descriptor)
        trusted(self.lock_path, directory=False)
        self.thread_lock = threading.Lock()

    @contextmanager
    def locked(self):
        if not self.thread_lock.acquire(timeout=remaining()):
            raise TimeoutError('allocator lock deadline exceeded')
        try:
            with self.lock_path.open('r+') as stream:
                while True:
                    try:
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        time.sleep(min(.02, remaining()))
                try: yield
                finally: fcntl.flock(stream, fcntl.LOCK_UN)
        finally:
            self.thread_lock.release()

    def read(self):
        path = self.state / 'manifest.json'
        if not path.exists():
            return {'version': 1, 'volumes': {}, 'nonces': {}}
        trusted(path, directory=False)
        result = json.loads(path.read_text())
        if set(result) != {'version', 'volumes', 'nonces'} or result['version'] != 1:
            raise ValueError('unknown manifest version')
        return result

    def save(self, value):
        # Unique temp names make a crash-left file harmless; never delete unknown bytes.
        fd, name = tempfile.mkstemp(prefix='manifest.', suffix='.tmp', dir=self.state)
        path = Path(name)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
            os.replace(path, self.state / 'manifest.json')
            descriptor = os.open(self.state, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(descriptor)
            finally: os.close(descriptor)
        finally:
            path.unlink(missing_ok=True)

    def authenticate(self, request, key, peer_uid):
        if peer_uid != self.worker_uid or not isinstance(request, dict) or set(request) != {'body', 'mac'}:
            raise ValueError('unauthenticated request')
        body = request['body']
        if not isinstance(body, dict) or set(body) != {'session_id', 'workspace_id', 'request_id', 'nonce', 'timestamp', 'operation'}:
            raise ValueError('invalid request shape')
        for field in ('session_id', 'workspace_id', 'request_id', 'nonce'): uuid(body[field])
        if (body['operation'] not in {'ensure', 'verify'} or type(body['timestamp']) is not int
                or abs(time.time() - body['timestamp']) > 60
                or not isinstance(request['mac'], str)
                or not hmac.compare_digest(hmac.new(key, canonical(body), hashlib.sha256).hexdigest(), request['mac'])):
            raise ValueError('invalid request authentication')
        with self.locked():
            manifest = self.read()
            now = int(time.time())
            manifest['nonces'] = {k: v for k, v in manifest['nonces'].items() if v > now - 120}
            if body['nonce'] in manifest['nonces'] or len(manifest['nonces']) >= 4096:
                raise ValueError('replayed request or nonce capacity exceeded')
            manifest['nonces'][body['nonce']] = now
            self.save(manifest)
        return body

    def verify(self, workspace_id, record):
        path, image = self.root / uuid(workspace_id), self.state / (workspace_id + '.ext4')
        trusted(image, directory=False)
        if image.stat().st_size != SIZE or image.stat().st_nlink != 1 or record['size'] != SIZE or record['phase'] != 'ready':
            raise ValueError('volume is not safely formatted')
        target_info = path.lstat()
        if stat.S_ISLNK(target_info.st_mode) or not stat.S_ISDIR(target_info.st_mode):
            raise ValueError('unsafe mountpoint')
        if target_info.st_uid != self.worker_uid or stat.S_IMODE(target_info.st_mode) != 0o700:
            raise ValueError('private workspace ownership or mode drift')
        evidence = mount_evidence(path)
        source = evidence['source']
        if (evidence['target'] != str(path) or evidence['fstype'] != 'ext4'
                or not {'nosuid', 'nodev', 'rw'} <= set(evidence['options'].split(','))
                or evidence['uuid'] != record['filesystem_uuid'] or not source.startswith('/dev/loop')):
            raise ValueError('mount identity drift')
        loop = json.loads(run('losetup', '--json', '--list', '--output', 'NAME,BACK-FILE', source))['loopdevices']
        if len(loop) != 1 or loop[0]['name'] != source or loop[0]['back-file'] != str(image):
            raise ValueError('loop backing identity drift')
        if run('blkid', '-p', '-s', 'UUID', '-o', 'value', str(image)) != record['filesystem_uuid']:
            raise ValueError('backing filesystem UUID drift')
        stats = os.statvfs(path)
        capacity = stats.f_blocks * stats.f_frsize
        if stats.f_fsid != record['filesystem_id']:
            raise ValueError('persistent filesystem identity drift')
        if not 0 < capacity <= SIZE:
            raise ValueError('physical quota drift')
        return dict(workspace_id=workspace_id, path=str(path), filesystem_uuid=record['filesystem_uuid'],
                    filesystem_id=record['filesystem_id'],
                    device=path.stat().st_dev, capacity_bytes=capacity, maximum_bytes=SIZE,
                    identity=record['identity'])

    def capacity(self, volumes):
        images = {p.stem: p for p in self.state.glob('*.ext4')}
        if len(set(volumes) | set(images)) >= LIMIT:
            raise ValueError('workspace allocation capacity exhausted')
        total = debt = 0
        for wid in set(volumes) | set(images):
            uuid(wid)
            if wid in volumes and (type(volumes[wid]['size']) is not int or volumes[wid]['size'] != SIZE):
                raise ValueError('invalid volume reservation')
            size, allocated = SIZE, 0
            if wid in images:
                trusted(images[wid], directory=False)
                info = images[wid].lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError('unsafe orphan or backing image')
                allocated = info.st_blocks * 512
                size = max(size, info.st_size, allocated)
            total += size
            debt += max(0, size - allocated)
        if total + SIZE > BYTE_LIMIT:
            raise ValueError('workspace physical byte budget exhausted')
        stats = os.statvfs(self.state)
        if stats.f_bavail * stats.f_frsize < SIZE + debt + self.floor:
            raise ValueError('operator disk free-space floor')

    def publish_identity(self, wid, record):
        # Sibling of Worker-owned mountpoints, with a root-only replace boundary.
        directory = self.root / '.identities'
        if not directory.exists():
            directory.mkdir(mode=0o755); directory.chmod(0o755)
        trusted(directory)
        if stat.S_IMODE(directory.stat().st_mode) != 0o755:
            raise ValueError('persistent identity directory mode drift')
        path = directory / (wid + '.json')
        value = canonical(dict(workspace_id=wid, filesystem_uuid=record['filesystem_uuid'],
                               filesystem_id=record['filesystem_id']))
        if path.exists() or path.is_symlink():
            trusted(path, directory=False)
            info = path.stat()
            if info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o644 or path.read_bytes() != value:
                raise ValueError('persistent identity metadata drift')
            return
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(value); stream.flush(); os.fsync(stream.fileno())
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)

    def ensure(self, request):
        # The native reader independently checks Task/segment/projection/binding/source.
        identity, state, expires_at = self.proof(request['session_id'], request['workspace_id'])
        with self.locked():
            require_fresh(expires_at)
            manifest = self.read(); volumes = manifest['volumes']; wid = request['workspace_id']
            record = volumes.get(wid)
            if record is not None:
                if record['identity'] != identity:
                    raise ValueError('native ownership drift')
                receipt = self.verify(wid, record)
                require_fresh(expires_at)
                return receipt
            if request['operation'] != 'ensure' or state != 'pending':
                raise ValueError('only a fresh pending workspace can allocate')
            # Include orphan image reservations; never prune data to recover capacity.
            self.capacity(volumes)
            path, image = self.root / wid, self.state / (wid + '.ext4')
            if path.exists() or path.is_symlink() or image.exists() or image.is_symlink():
                raise ValueError('unowned allocation path exists')
            record = dict(phase='reserved', size=SIZE, identity=identity, request_id=request['request_id'])
            volumes[wid] = record; self.save(manifest)
            descriptor = os.open(image, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.close(descriptor)
            run('fallocate', '-l', str(SIZE), str(image))
            run('mkfs.ext4', '-q', '-F', '-m', '0', str(image))
            fs_uuid = run('blkid', '-p', '-s', 'UUID', '-o', 'value', str(image))
            uuid(fs_uuid)
            record.update(phase='formatted', filesystem_uuid=fs_uuid); self.save(manifest)
            require_fresh(expires_at)
            path.mkdir(mode=0o755)
            run('mount', '-o', 'loop,nosuid,nodev', str(image), str(path))
            require_fresh(expires_at)
            # Only the freshly formatted filesystem's empty recovery directory.
            (path / 'lost+found').rmdir()
            os.chown(path, self.worker_uid, self.worker_uid); os.chmod(path, 0o700)
            record.update(phase='ready', filesystem_id=os.statvfs(path).f_fsid)
            require_fresh(expires_at)
            self.publish_identity(wid, record)
            self.save(manifest)
            receipt = self.verify(wid, record)
            require_fresh(expires_at)
            return receipt

    def restore(self):
        with self.locked():
            for wid, record in self.read()['volumes'].items():
                uuid(wid)
                if record['phase'] != 'ready':
                    raise ValueError('incomplete allocation requires operator review; never reformat')
                image, path = self.state / (wid + '.ext4'), self.root / wid
                trusted(image, directory=False)
                if image.stat().st_size != SIZE or run('blkid', '-p', '-s', 'UUID', '-o', 'value', str(image)) != record['filesystem_uuid']:
                    raise ValueError('restore backing identity mismatch')
                if not path.exists(): path.mkdir(mode=0o755)
                if not os.path.ismount(path):
                    trusted(path)
                    if any(path.iterdir()): raise ValueError('refuse to cover unknown mountpoint bytes')
                    run('mount', '-o', 'loop,nosuid,nodev', str(image), str(path))
                self.publish_identity(wid, record)
                self.verify(wid, record)


def serve(allocator, socket_path, key):
    def expired(signum, frame):
        raise TimeoutError('allocator request deadline exceeded')

    # Serial main-thread UDS service: also interrupt synchronous filesystem calls,
    # not just socket I/O and each individual child process.
    signal.signal(signal.SIGALRM, expired)
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.request.settimeout(5)
            token = DEADLINE.set(time.monotonic() + REQUEST_SECONDS)
            signal.setitimer(signal.ITIMER_REAL, REQUEST_SECONDS)
            try:
                try:
                    peer = struct.unpack('3i', self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
                    data = self.rfile.readline(MAX_BODY + 1)
                    if len(data) > MAX_BODY or not data.endswith(b'\n'): raise ValueError('bounded JSON required')
                    request = allocator.authenticate(json.loads(data), key, peer)
                    receipt = allocator.ensure(request)
                    result = {'ok': True, 'receipt': receipt, 'nonce': request['nonce']}
                    result['mac'] = hmac.new(key, canonical(result), hashlib.sha256).hexdigest()
                except Exception:
                    result = {'ok': False, 'error': 'private_workspace_refused'}
                try:
                    self.request.settimeout(min(5, remaining()))
                    self.wfile.write(canonical(result) + b'\n')
                except (OSError, TimeoutError):
                    pass  # No new response budget after the absolute deadline.
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                DEADLINE.reset(token)
    # ponytail: one bounded serial service; raise throughput only after filesystem locks remain authoritative.
    trusted(socket_path.parent)
    if socket_path.exists():
        if not stat.S_ISSOCK(socket_path.lstat().st_mode): raise ValueError('foreign socket path')
        socket_path.unlink()
    with socketserver.UnixStreamServer(str(socket_path), Handler) as server:
        os.chown(socket_path, 0, allocator.worker_uid); os.chmod(socket_path, 0o660)
        server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('config', type=Path)
    options = parser.parse_args(); trusted(options.config, directory=False)
    if options.config.stat().st_mode & 0o077: raise ValueError('config must be private')
    config = json.loads(options.config.read_text())
    proof = NativeProof(config); proof.require_clean()
    generation = config.get('generation', 'native105')
    roots = {'native105': (ROOT, STATE),
             'cloud114': (Path('/var/lib/zebra/erpnext-full-workspaces'), Path('/var/lib/zebra/erpnext-full-volumes')),
             'cloud114-qa': (Path('/var/lib/zebra/erpnext-full-qa-workspaces'), Path('/var/lib/zebra/erpnext-full-qa-volumes'))}
    root, state = roots[generation]
    allocator = Allocator(proof, root=root, state=state, worker_uid=config['worker_host_uid'])
    key_path = Path(config['hmac_key_path']); trusted(key_path, directory=False)
    if key_path.stat().st_mode & 0o077: raise ValueError('key must be private')
    key = key_path.read_bytes()
    if len(key) < 32: raise ValueError('insufficient HMAC key')
    allocator.restore()
    serve(allocator, Path(config['socket_path']), key)
