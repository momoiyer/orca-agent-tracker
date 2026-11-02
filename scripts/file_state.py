"""Private, reversible hook-file updates independent of any configuration repository."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

ROOT=Path(__file__).resolve().parents[1]
CODEx=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex'))).expanduser().resolve()
CLAUDE=Path(os.environ.get('CLAUDE_CONFIG_DIR',str(Path.home()/'.claude'))).expanduser().resolve()
STATE=Path(os.environ.get('AGENT_DESK_STATE',str(Path.home()/'.local/state/agent-desk'))).expanduser().resolve()

def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None

def current(path):
    if path.is_symlink():raise ValueError(f'Refusing to replace symlink: {path}')
    return path.read_bytes() if path.exists() else None

def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as stream:
        temp=Path(stream.name);stream.write(data)
    try:
        temp.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o600)
        temp.replace(path)
    finally:temp.unlink(missing_ok=True)

def allowed(path):
    return path in (CODEx/'hooks.json',CLAUDE/'settings.json')

def apply(changes,originals):
    entries=[]
    for path,data in changes.items():
        if not allowed(path):raise ValueError(f'Unexpected hook update path: {path}')
        old=originals[path]
        entries.append({'path':str(path),'before':base64.b64encode(old).decode() if old is not None else None,'before_hash':digest(old),'after_hash':digest(data)})
    STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    directory=STATE/'setup-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    write(directory/'manifest.json',(json.dumps(entries,indent=2)+'\n').encode())
    completed=[]
    try:
        for entry in entries:
            path=Path(entry['path'])
            if digest(current(path))!=entry['before_hash']:raise ValueError(f'File changed during installation: {path}')
            write(path,changes[path]);completed.append(entry)
    except Exception:
        for entry in reversed(completed):
            path=Path(entry['path'])
            if digest(current(path))!=entry['after_hash']:continue
            if entry['before'] is None:path.unlink()
            else:write(path,base64.b64decode(entry['before']))
        raise
    print('Backup:',directory)

def restore(directory):
    directory=Path(directory).expanduser().resolve()
    directory.relative_to(STATE/'setup-backups')
    entries=json.loads((directory/'manifest.json').read_text())
    for entry in entries:
        path=Path(entry['path'])
        if not allowed(path):raise ValueError(f'Unexpected restore path: {path}')
        if digest(current(path))!=entry['after_hash']:raise ValueError(f'Changed since installation; will not overwrite: {path}')
    for entry in reversed(entries):
        path=Path(entry['path'])
        if entry['before'] is None:path.unlink()
        else:write(path,base64.b64decode(entry['before']))
    print('Restored',len(entries),'files from',directory)
