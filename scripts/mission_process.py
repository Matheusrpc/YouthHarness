"""Own a process tree before releasing the diagnostic client. Stdlib only."""
import base64
import ctypes
import json
import os
from pathlib import Path
import platform
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid


def windows_api():
    from ctypes import wintypes as w
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    definitions = {
        'CreateJobObjectW': ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
        'OpenJobObjectW': ([w.DWORD, w.BOOL, w.LPCWSTR], w.HANDLE),
        'SetInformationJobObject': ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
        'QueryInformationJobObject': ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p], w.BOOL),
        'AssignProcessToJobObject': ([w.HANDLE, w.HANDLE], w.BOOL),
        'TerminateJobObject': ([w.HANDLE, w.UINT], w.BOOL),
        'CloseHandle': ([w.HANDLE], w.BOOL),
    }
    for name, (args, result) in definitions.items():
        getattr(api, name).argtypes, getattr(api, name).restype = args, result
    return api


def new_job(name):
    from ctypes import wintypes as w
    class Basic(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64), ('flags', w.DWORD),
                    ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t), ('active', w.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
    class Limits(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', ctypes.c_uint64 * 6),
                    ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                    ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
    api = windows_api()
    handle = api.CreateJobObjectW(None, name)
    limits = Limits()
    limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE; never permit breakaway.
    if not handle:
        raise ValueError('unsupported_containment')
    if not api.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        api.CloseHandle(handle)
        raise ValueError('unsupported_containment')
    return api, handle


def active_job(api, handle):
    class Accounting(ctypes.Structure):
        _fields_ = [('times', ctypes.c_int64 * 4), ('faults', ctypes.c_uint32),
                    ('total', ctypes.c_uint32), ('active', ctypes.c_uint32), ('terminated', ctypes.c_uint32)]
    info = Accounting()
    if not api.QueryInformationJobObject(handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
        return None
    return info.active


def linux_members(group):
    members = []
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = path.read_text().rsplit(')', 1)[1].split()
            if int(fields[2]) == group and fields[0] != 'Z':
                members.append(int(path.parent.name))
        except (OSError, ValueError, IndexError):
            continue
    return members


def owner_gone(owner):
    """Read-only evidence. Never kill an identity supplied by a caller."""
    if not isinstance(owner, dict) or set(owner) != {'kind', 'name', 'pid'}:
        return False
    try:
        uuid.UUID(owner['name'].removeprefix('Local\\YoungCrow-'))
    except (ValueError, TypeError, AttributeError):
        return False
    if owner['kind'] == 'windows-job' and os.name == 'nt':
        api = windows_api()
        handle = api.OpenJobObjectW(4, False, owner['name'])
        if not handle:
            return ctypes.get_last_error() == 2
        try:
            return active_job(api, handle) == 0
        finally:
            api.CloseHandle(handle)
    if owner['kind'] == 'linux-group' and sys.platform == 'linux' and type(owner['pid']) is int and owner['pid'] > 1:
        # Reuse can conservatively report a live group, never kill it. Inherited seccomp
        # keeps all owned descendants in the original group until they exit.
        return not linux_members(owner['pid'])
    return False


def process_missing(pid):
    """Conservative read-only test. A reused or inaccessible PID is still occupied."""
    if type(pid) is not int or pid <= 1:
        return False
    if os.name == 'nt':
        from ctypes import wintypes as w
        api = windows_api()
        api.OpenProcess.argtypes, api.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
        handle = api.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 87
        api.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        code = w.DWORD()
        try:
            return bool(api.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value != 259
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        pass
    return False


def linux_filter():
    """Inherit a seccomp filter preventing descendants from leaving this group.

    This contains process lifetime; it is not a filesystem/network sandbox.
    Only the tested x86-64 ABI is supported. Reject alternate syscall ABIs.
    """
    if platform.machine().lower() not in ('x86_64', 'amd64'):
        raise ValueError('unsupported_containment')
    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte), ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint32)]
    class Program(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ushort), ('filters', ctypes.POINTER(Filter))]
    instructions = [(0x20, 0, 0, 4), (0x15, 1, 0, 0xc000003e), (0x06, 0, 0, 0x80000000),
                    (0x20, 0, 0, 0), (0x35, 0, 1, 0x40000000), (0x06, 0, 0, 0x80000000)]
    for syscall in (109, 112, 272, 308):  # setpgid, setsid, unshare, setns
        instructions += [(0x15, 0, 1, syscall), (0x06, 0, 0, 0x50001)]
    # clone3 carries flags behind a pointer; ENOSYS permits libc's safe clone fallback.
    instructions += [(0x15, 0, 1, 435), (0x06, 0, 0, 0x50026),
                     (0x15, 0, 3, 56), (0x20, 0, 0, 16),
                     (0x45, 0, 1, 0x7e020000), (0x06, 0, 0, 0x50001), (0x06, 0, 0, 0x7fff0000)]
    array = (Filter * len(instructions))(*(Filter(*v) for v in instructions))
    program = Program(len(array), array)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) or libc.prctl(22, 2, ctypes.byref(program), 0, 0):
        raise ValueError('unsupported_containment')


def child_main():
    # Isolated Python (-I -S) starts no client until the parent assigns its job.
    request = json.loads(sys.stdin.buffer.readline(1024 * 1024))
    if sys.platform == 'linux':
        linux_filter()
        parent = request['parent_pid']
        if os.getppid() != parent:
            return 125

        def watch_parent():
            deadline = time.monotonic() + request['timeout_seconds']
            while os.getppid() == parent and time.monotonic() < deadline:
                time.sleep(.05)
            os.killpg(os.getpid(), signal.SIGKILL)

        threading.Thread(target=watch_parent, daemon=True).start()
    client = subprocess.Popen(request['argv'], stdin=subprocess.PIPE)
    client.communicate(base64.b64decode(request['stdin']))
    return client.returncode


def environment(plan):
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP', 'TMPDIR',
               'USERPROFILE', 'HOME', 'HOMEDRIVE', 'HOMEPATH', 'APPDATA', 'LOCALAPPDATA',
               'PROGRAMDATA', 'PROGRAMFILES', 'CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'LANG', 'LC_ALL'}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    if plan['connection'] == 'api':
        value = os.environ.get(plan['credential_env'])
        if not value:
            raise ValueError('missing_credential')
        env['OPENAI_API_KEY' if plan['client'] == 'codex' else 'ANTHROPIC_API_KEY'] = value
    return env


def supervise(plan: dict, *, on_started, stop_requested) -> dict:
    if os.name != 'nt' and not (sys.platform == 'linux' and platform.machine().lower() in ('x86_64', 'amd64')):
        raise ValueError('unsupported_containment')
    result = dict(reason='spawn_failed', exit_code=None, stdout=b'', tree_reaped=True,
                  effect_started=False, owner=None, elapsed_seconds=0)
    if not Path(plan['argv'][0]).is_file():
        return result
    env = environment(plan)
    process, job, api = None, None, None
    streams, threads, stopped = queue.Queue(maxsize=16), [], threading.Event()
    started, total, output = time.monotonic(), 0, bytearray()
    name = ('Local\\YoungCrow-' if os.name == 'nt' else '') + str(uuid.uuid4())

    def read(stream, label):
        try:
            while not stopped.is_set():
                chunk = stream.read1(4096)
                while not stopped.is_set():
                    try:
                        streams.put((label, chunk), timeout=.05)
                        break
                    except queue.Full:
                        continue
                if not chunk:
                    break
        except (ValueError, OSError):
            pass

    try:
        if os.name == 'nt':
            api, job = new_job(name)
        process = subprocess.Popen([sys.executable, '-I', '-S', str(Path(__file__).resolve()), '--child'],
                                   cwd=plan['cwd'], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=os.name != 'nt',
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if job and not api.AssignProcessToJobObject(job, int(process._handle)):
            raise ValueError('unsupported_containment')
        owner = dict(kind='windows-job' if job else 'linux-group', name=name, pid=process.pid)
        result['owner'] = owner
        on_started(owner)  # Persist ownership before giving the wrapper any executable.
        for stream, label in ((process.stdout, 'out'), (process.stderr, 'err')):
            thread = threading.Thread(target=read, args=(stream, label), daemon=True)
            thread.start()
            threads.append(thread)
        process.stdin.write(json.dumps(dict(argv=plan['argv'], stdin=base64.b64encode(plan['stdin']).decode(),
                                           parent_pid=os.getpid(), timeout_seconds=plan['timeout_seconds'])).encode() + b'\n')
        process.stdin.close()
        result.update(effect_started=True, reason='completed')
        done = 0
        while done < 2 or process.poll() is None:
            if stop_requested():
                result['reason'] = 'cancelled'
                break
            if time.monotonic() - started >= plan['timeout_seconds']:
                result['reason'] = 'timeout'
                break
            try:
                label, chunk = streams.get(timeout=.05)
            except queue.Empty:
                continue
            if not chunk:
                done += 1
                continue
            total += len(chunk)
            if label == 'out':
                output.extend(chunk[:max(0, plan['output_limit_bytes'] - len(output))])
            if total > plan['output_limit_bytes']:
                result['reason'] = 'output_limit'
                break
    finally:
        stopped.set()
        if process:
            result['exit_code'] = process.poll()
            if job:
                api.TerminateJobObject(job, 124)
            elif os.name != 'nt':
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.kill()  # The unassigned bootstrap never received a client request.
            process.wait(timeout=5)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                remaining = active_job(api, job) if job else len(linux_members(process.pid)) if os.name != 'nt' else 0
                if remaining == 0:
                    break
                time.sleep(.02)
            result['tree_reaped'] = remaining == 0
            for thread in threads:
                thread.join(timeout=1)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        if job:
            api.CloseHandle(job)
    result.update(stdout=bytes(output), elapsed_seconds=round(time.monotonic() - started, 6))
    return result


if __name__ == '__main__':
    try:
        sys.exit(child_main() if sys.argv[1:] == ['--child'] else 2)
    except Exception:
        sys.exit(125)
