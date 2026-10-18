"""Audit saved audio; make a portable checkpoint only at an idle boundary."""
import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else _digest(stream)


def _digest(stream):
    value = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        value.update(block)
    return value.hexdigest()


def inside(root, relative):
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    return path


def audit(root):
    chunks = json.loads((root / 'chunks.json').read_text(encoding='utf-8'))
    records = []
    for index, chunk in enumerate(chunks):
        if chunk['status'] != 'done':
            continue
        relative = chunk.get('audio_path')
        if not relative:
            raise ValueError(f'Done segment {index} has no audio path')
        path = inside(root, relative)
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Done segment {index} has missing/empty audio: {relative}')
        semantic = {key: chunk.get(key) for key in ('id', 'speaker', 'text', 'instruct', 'pause_after')}
        records.append(dict(index=index, path=relative, bytes=path.stat().st_size,
                            sha256=digest(path), content_sha256=hashlib.sha256(
                                json.dumps(semantic, sort_keys=True, ensure_ascii=False).encode()).hexdigest()))
    return chunks, records


def snapshot(root, destination):
    chunks, records = audit(root)
    if any(c['status'] == 'generating' for c in chunks):
        raise ValueError('Refusing snapshot while segments are generating; stop at a batch boundary')
    if any(root.glob('forty-batch-trial*/active.lock')):
        raise ValueError('Refusing snapshot while a trial lock exists')
    destination = destination.resolve()
    if destination == root.resolve() or root.resolve().is_relative_to(destination):
        raise ValueError('Snapshot destination must not contain the source project')
    destination.mkdir(parents=True, exist_ok=False)
    required = ['chunks.json', 'annotated_script.json', 'voice_config.json', 'recovery-manifest.json']
    for name in required:
        shutil.copy2(root / name, destination / name)
    for name in ('.gitignore', '.dockerignore'):
        if (root / name).is_file():
            shutil.copy2(root / name, destination / name)
    for path in root.iterdir():
        if path.is_file() and (path.suffix.lower() in {'.py', '.ps1', '.cmd', '.md', '.txt', '.yml', '.yaml'} or path.name == 'Dockerfile'):
            shutil.copy2(path, destination / path.name)
    for name in ('app', 'builtin_lora'):
        if (root / name).exists():
            shutil.copytree(root / name, destination / name,
                            ignore=shutil.ignore_patterns('env', '.venv', '__pycache__', '*.pyc', 'node_modules'))
    for record in records:
        target = inside(destination, record['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(inside(root, record['path']), target)
    history = destination / 'trial-history'
    for folder in root.glob('forty-batch-trial*'):
        if folder.is_dir():
            for name in ('plan.json', 'status.json', 'measurements.json', 'original-audio-sha256.json'):
                source = folder / name
                if source.exists():
                    target = history / folder.name / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    # Detect changes during the copy rather than silently checkpointing mixed state.
    for name in required + ['app/config.json']:
        if digest(root / name) != digest(destination / name):
            raise ValueError(f'State changed during snapshot: {name}; checkpoint is incomplete')
    files = {p.relative_to(destination).as_posix(): digest(p) for p in destination.rglob('*') if p.is_file()}
    manifest = dict(format_version=1, created_utc=datetime.now(timezone.utc).isoformat(),
                    total_segments=len(chunks), completed_segments=len(records),
                    pending_segments=sum(c['status'] != 'done' for c in chunks),
                    completed_audio=records, files=files,
                    note='Weights and Python environment excluded. Verify this checkpoint before resuming. No script regeneration required.')
    (destination / 'checkpoint-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    verify(destination)
    return manifest


def verify(root):
    manifest = json.loads((root / 'checkpoint-manifest.json').read_text(encoding='utf-8'))
    for relative, expected in manifest['files'].items():
        if digest(inside(root, relative)) != expected:
            raise ValueError(f'Checkpoint hash mismatch: {relative}')
    chunks, records = audit(root)
    if records != manifest['completed_audio'] or len(chunks) != manifest['total_segments']:
        raise ValueError('Checkpoint audio inventory or segment count changed')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--snapshot', type=Path)
    group.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        result = verify(args.root)
    elif args.snapshot:
        result = snapshot(args.root, args.snapshot)
    else:
        chunks, records = audit(args.root)
        result = dict(total_segments=len(chunks), completed_segments=len(records),
                      pending_segments=sum(c['status'] == 'pending' for c in chunks),
                      generating_segments=sum(c['status'] == 'generating' for c in chunks),
                      error_segments=sum(c['status'] == 'error' for c in chunks))
    print(json.dumps({k: v for k, v in result.items() if k not in ('files', 'completed_audio')}, indent=2))


if __name__ == '__main__':
    main()
