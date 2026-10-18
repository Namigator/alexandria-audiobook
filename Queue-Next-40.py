"""Wait for the current trial, checkpoint, run exactly one further 40-batch group."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
PRIOR = ROOT / 'forty-batch-trial'
NEXT = ROOT / 'forty-batch-trial-02'
QUEUE = ROOT / 'next-40-queue.json'
LOCK = ROOT / 'next-40-queue.lock'
STOP = ROOT / 'next-40-stop-requested'


def publish(phase, **details):
    state = dict(phase=phase, pid=os.getpid(), updated=time.time(), prior=str(PRIOR), next=str(NEXT), **details)
    temporary = QUEUE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2), encoding='utf-8')
    temporary.replace(QUEUE)
    print(json.dumps(state), flush=True)


def prior_ready():
    state = json.loads((PRIOR / 'status.json').read_text(encoding='utf-8'))
    if state['phase'] in ('Paused', 'Needs attention'):
        raise RuntimeError('First group stopped: ' + state.get('detail', state['phase']))
    return state['phase'] == 'Complete' and not (PRIOR / 'active.lock').exists()


def checkpoint(label):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = ROOT / 'checkpoints' / f'{stamp}-{label}'
    subprocess.run([sys.executable, str(ROOT / 'Checkpoint-Conversion.py'), '--snapshot', str(target)],
                   cwd=ROOT, check=True)
    return str(target)


def main():
    if '--check-only' in sys.argv:
        print(json.dumps(dict(prior_ready=prior_ready(), next_exists=NEXT.exists(), queue_exists=LOCK.exists())))
        return
    descriptor = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(descriptor, str(os.getpid()).encode())
    os.close(descriptor)
    try:
        if NEXT.exists():
            raise RuntimeError('Second group directory already exists; inspect rather than duplicate it')
        publish('Waiting for first 40')
        while not prior_ready():
            if STOP.exists() or (PRIOR / 'stop-requested').exists():
                publish('Paused', detail='Human stop request; second group not started')
                return
            time.sleep(10)
        if STOP.exists() or (PRIOR / 'stop-requested').exists():
            publish('Paused', detail='Human stop request at boundary')
            return
        active = requests.get('http://127.0.0.1:4200/api/status/audio', timeout=20)
        active.raise_for_status()
        if active.json()['running']:
            raise RuntimeError('Another audio job is running; second group not launched')
        before = checkpoint('after-first-40')
        if STOP.exists() or (PRIOR / 'stop-requested').exists():
            publish('Paused', checkpoint=before, detail='Human stop request while checkpointing')
            return
        publish('Starting second 40', checkpoint=before)
        environment = dict(os.environ, ALEXANDRIA_TRIAL_DIR=str(NEXT))
        logs = ROOT.parent / 'logs'
        logs.mkdir(exist_ok=True)
        with (logs / 'forty-batch-trial-02.out.log').open('w', encoding='utf-8') as out, (logs / 'forty-batch-trial-02.err.log').open('w', encoding='utf-8') as err:
            child = subprocess.Popen([sys.executable, '-u', str(ROOT / 'Run-40-Batches.py')],
                                     cwd=ROOT, env=environment, stdout=out, stderr=err)
            publish('Second 40 running', launcher_pid=child.pid, checkpoint=before)
            while child.poll() is None:
                if STOP.exists():
                    NEXT.mkdir(exist_ok=True)
                    (NEXT / 'stop-requested').touch()
                time.sleep(10)
        state = json.loads((NEXT / 'status.json').read_text(encoding='utf-8'))
        if child.returncode != 0 or state['phase'] != 'Complete':
            raise RuntimeError('Second group did not complete: ' + state.get('detail', str(child.returncode)))
        after = checkpoint('after-second-40')
        publish('Complete', checkpoint=after, detail='Both groups finished; no further rendering queued')
    except Exception as exc:
        publish('Needs attention', detail=str(exc))
        raise
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
