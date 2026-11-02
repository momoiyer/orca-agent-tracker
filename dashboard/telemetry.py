#!/usr/bin/env python3
"""Small, fail-open local hook receiver. Never records tool inputs or transcripts."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

STATE = Path(os.environ.get('AGENT_DESK_STATE', str(Path.home()/'.local/state/agent-desk'))).expanduser()

def database():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(STATE/'events.sqlite', timeout=2)
    conn.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, provider TEXT, role TEXT, path TEXT, task TEXT, state TEXT, updated_at REAL, parent_id TEXT, pane_key TEXT)')
    os.chmod(STATE/'events.sqlite', 0o600)
    return conn

def record(provider, payload, now=None):
    now = time.time() if now is None else now
    parent = str(payload.get('session_id') or payload.get('thread_id') or '')[:160]
    if not parent:
        return
    event = payload.get('hook_event_name') or payload.get('event')
    child = str(payload.get('agent_id') or '')[:160]
    session = child if child else parent
    if event in ('SubagentStart','SubagentStop') and not child:
        return  # Never apply an unidentified child event to the parent's state.
    key = provider+':'+session
    status = {'SessionStart':'idle','UserPromptSubmit':'working','PreToolUse':'working',
              'PostToolUse':'working','PostToolUseFailure':'working','PermissionRequest':'waiting',
              'Stop':'idle','SessionEnd':'stopped','SubagentStart':'working','SubagentStop':'stopped'}.get(event)
    if not status:
        return
    role = str(payload.get('agent_type') or payload.get('agent_role') or ('general' if not child else 'unspecified'))[:80]
    # Store a short local task label. Tool inputs/results and transcript bodies are excluded.
    # Prompt labels may contain private text; they remain in the permission-restricted local DB.
    task = str(payload.get('prompt') or '')[:240] if event == 'UserPromptSubmit' else ''
    task = ' '.join(task.split())
    path = str(payload.get('cwd') or '')[:1000]
    pane = str(os.environ.get('ORCA_PANE_KEY',''))[:160]
    with closing(database()) as conn, conn:
        conn.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET role=CASE WHEN excluded.role IN (\'general\',\'unspecified\') THEN sessions.role ELSE excluded.role END,path=CASE WHEN excluded.path=\'\' THEN sessions.path ELSE excluded.path END,task=CASE WHEN excluded.task=\'\' THEN sessions.task ELSE excluded.task END,state=excluded.state,updated_at=excluded.updated_at,parent_id=CASE WHEN excluded.parent_id=\'\' THEN sessions.parent_id ELSE excluded.parent_id END,pane_key=CASE WHEN excluded.pane_key=\'\' THEN sessions.pane_key ELSE excluded.pane_key END',
                     (key,provider,role,path,task,status,now,provider+':'+parent if child else '',pane))
        conn.execute('DELETE FROM sessions WHERE updated_at < ?', (now-30*86400,))

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--provider',choices=['codex','claude'],required=True);args=parser.parse_args()
    try:
        record(args.provider,json.loads(sys.stdin.read(1024*1024)))
    except Exception:
        pass  # Observability must not block development or print private payloads.
