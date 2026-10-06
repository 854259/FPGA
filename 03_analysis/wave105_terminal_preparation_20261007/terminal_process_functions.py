def alive_group(pgid):
    found = []
    for p in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = p.read_text().rsplit(')', 1)[1].split()
            if int(fields[2]) == pgid:
                found.append(int(p.parent.name))
        except (OSError, ValueError, IndexError):
            pass
    return sorted(found)

def execute(label, argv, cap):
    assert sources() == manifest['source_hashes']
    assert sha(sys.executable) == manifest['python_sha256']
    folder = root / 'processes' / label
    folder.mkdir(parents=True, exist_ok=False)
    assert argv[:2] == [sys.executable, '-B'] and len(argv) >= 3
    assert Path(argv[2]) in (original / 'collect_evidence.py', original / 'audit.py')
    assert sha(argv[2]) == spec['source_hashes'][Path(argv[2]).name]
    attempt = dict(argv=argv, cwd=str(root), cap_s=cap, started_ns=time.time_ns())
    save(folder / 'attempt.json', attempt)
    timeout, error, proc, identity = (False, None, None, None)
    group_signals = []
    started = time.monotonic()
    with (folder / 'stdout.bin').open('xb') as out, (folder / 'stderr.bin').open('xb') as err:
        try:
            proc = subprocess.Popen(argv, cwd=root, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True)
            folder_proc = Path('/proc') / str(proc.pid)
            fields = (folder_proc / 'stat').read_text().rsplit(')', 1)[1].split()
            assert int(fields[2]) == int(fields[3]) == proc.pid
            assert fields[0] not in ('Z', 'X')
            identity = dict(pid=proc.pid, pgid=proc.pid, session=proc.pid, starttime=fields[19], command_sha256=sha(folder_proc / 'cmdline'))
            assert identity['command_sha256'] == hashlib.sha256(b'\x00'.join((str(x).encode('utf-8') for x in argv)) + b'\x00').hexdigest()
            save(folder / 'child_identity.json', identity)
            try:
                proc.wait(timeout=cap)
            except subprocess.TimeoutExpired:
                timeout = True
        except BaseException as exc:
            error = type(exc).__name__ + ': ' + str(exc)
        finally:
            if proc is not None and proc.returncode is None:
                try:
                    folder_proc = Path('/proc') / str(proc.pid)
                    fields = (folder_proc / 'stat').read_text().rsplit(')', 1)[1].split()
                    matches = identity is not None and fields[19] == identity['starttime'] and (int(fields[2]) == identity['pgid']) and (int(fields[3]) == identity['session']) and (fields[0] == 'Z' or sha(folder_proc / 'cmdline') == identity['command_sha256'])
                    if not matches:
                        raise RuntimeError('owned child identity unconfirmed; no signal sent')
                    os.killpg(identity['pgid'], signal.SIGKILL)
                    group_signals.append('SIGKILL_bound_unreaped_group')
                except ProcessLookupError:
                    pass
                except BaseException as exc:
                    error = (error + '; ' if error else '') + type(exc).__name__ + ': ' + str(exc)
                try:
                    proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    error = (error + '; ' if error else '') + 'unconfirmed_child_still_running'
    remaining = []
    if proc is not None:
        deadline = time.monotonic() + 6
        while True:
            try:
                while os.waitpid(-proc.pid, os.WNOHANG)[0]:
                    pass
            except ChildProcessError:
                pass
            remaining = alive_group(proc.pid)
            if not remaining or time.monotonic() >= deadline:
                break
            time.sleep(0.025)
    record = dict(attempt, returncode=proc.returncode if proc else None, timeout=timeout, error=error, remaining_group=remaining, elapsed_s=time.monotonic() - started, child_identity=identity, group_signals=group_signals, streams={n: dict(sha256=sha(folder / n), bytes=(folder / n).stat().st_size) for n in ['stdout.bin', 'stderr.bin']}, source_unchanged=sources() == manifest['source_hashes'])
    save(folder / 'process.json', record)
    return record
