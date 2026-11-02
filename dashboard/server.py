#!/usr/bin/env python3
"""Local, read-only Orca Agent Tracker. Python 3.11+, no third-party dependencies."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading
import time
import tomllib
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
HOME=Path.home()
STATE=Path(os.environ.get('AGENT_DESK_STATE',str(HOME/'.local/state/agent-desk'))).expanduser()
CODEX=Path(os.environ.get('CODEX_HOME',str(HOME/'.codex'))).expanduser()
CLAUDE=Path(os.environ.get('CLAUDE_CONFIG_DIR',str(HOME/'.claude'))).expanduser()
INTERVAL=5

def command(argv):
    result=subprocess.run(argv,capture_output=True,text=True,timeout=8)
    if result.returncode:
        # CLI diagnostics only; do not expose arbitrary stderr or environment content.
        raise RuntimeError('CLI unavailable or returned an error; check its launcher and permissions.')
    return json.loads(result.stdout)

def rows(value, key):
    if isinstance(value, dict):
        if value.get('ok') is False:
            raise RuntimeError('CLI reported an unsuccessful response.')
        result=value.get('result',value)
        if isinstance(result,dict):
            if key not in result:
                raise RuntimeError(f'Unsupported CLI response: expected {key} collection.')
            if result.get('truncated') is True:
                raise RuntimeError('CLI response is truncated; full session coverage is unavailable.')
            value=result[key]
        else:
            value=result
    if not isinstance(value,list) or any(not isinstance(item,dict) for item in value):
        raise RuntimeError(f'Unsupported CLI response: expected {key} list of records.')
    return value

def state(value):
    text=str(value or '').lower()
    if text in ('working','running','busy','thinking','executing','active'):return 'working'
    if text in ('waiting','blocked','needs-input','waiting-for-user','waiting_for_input','permission'):return 'waiting'
    if text in ('idle','ready'):return 'idle'
    if text in ('stopped','exited','completed','done','terminated'):return 'stopped'
    return 'unknown'

def seconds(value, fallback=None):
    if isinstance(value,(int,float)) and value>0:
        return value/1000 if value>1e12 else value
    return fallback if fallback is not None else time.time()

def clean_agent(value, provider, source):
    path=str(value.get('cwd') or value.get('path') or value.get('worktreePath') or '')
    identity=value.get('sessionId') or value.get('session_id') or value.get('id') or value.get('paneKey')
    if not identity:
        raise RuntimeError('Session source returned a record without a stable identity.')
    return {'id':str(identity),'provider':provider,'role':str(value.get('role') or value.get('agentRole') or 'general'),
      'path':path,'project':Path(path).name if path else 'Unassigned',
      'task':str(value.get('task') or value.get('title') or value.get('name') or '')[:300],
      'state':state(value.get('state') or value.get('status')),'updated_at':seconds(value.get('updatedAt')),
      'parent_id':str(value.get('parentId') or ''),'pane_key':str(value.get('paneKey') or ''),
      'source':source,'confidence':'reported'}

def map_orca(worktrees, repos):
    agents=[];projects=[]
    for repo in repos:
        if not isinstance(repo.get('path'),str):
            raise RuntimeError('Unsupported Orca repository record.')
        projects.append({'name':str(repo.get('displayName') or Path(repo['path']).name),'path':repo['path'],'branch':''})
    for tree in worktrees:
        path=tree.get('path')
        if not isinstance(path,str) or not isinstance(tree.get('agents'),list):
            raise RuntimeError('Unsupported Orca workspace record.')
        project=str(tree.get('repo') or Path(path).name)
        projects.insert(0,{'name':project,'path':path,'branch':str(tree.get('branch') or '').removeprefix('refs/heads/')})
        for value in tree['agents']:
            if not isinstance(value,dict) or not value.get('paneKey') or not value.get('agentType'):
                raise RuntimeError('Unsupported Orca agent identity fields.')
            provider=str(value['agentType']).lower()
            item=clean_agent(dict(value,cwd=path,id=value['paneKey']),provider,'Orca live')
            item['project']=project
            item['task']=str(value.get('taskTitle') or value.get('conversationName') or value.get('prompt') or '')[:300]
            item['parent_id']=str(value.get('parentPaneKey') or '')
            # A finished turn in an attached CLI is idle, not a dead session.
            main=value.get('mainAgent') or {}
            reported=main.get('state') or value.get('state')
            item['state']=state(reported)
            if value.get('hasLivePty') is False:
                item['state']='unknown'
            elif item['state']=='stopped' and value.get('hasLivePty') is True:
                item['state']='idle'
            if value.get('hasLivePty') is True:
                item['confidence']='live process; reported activity'
            agents.append(item)
            children=value.get('subagents',[])
            if not isinstance(children,list):
                raise RuntimeError('Unsupported Orca child-agent list.')
            for child in children:
                if not isinstance(child,dict) or not child.get('id'):
                    raise RuntimeError('Unsupported Orca child-agent identity.')
                entry=clean_agent(dict(child,cwd=path),provider,'Orca child agent')
                entry.update(project=project,parent_id=item['id'],role=str(child.get('agentType') or 'unspecified'),
                             task=str(child.get('description') or '')[:300],updated_at=seconds(child.get('startedAt')),
                             confidence='live child observation' if value.get('subagentObservation')=='live' else 'unverified child observation')
                if value.get('subagentObservation')!='live':entry['state']='unknown'
                agents.append(entry)
    return agents,projects

def orca():
    executable=os.environ.get('AGENT_DESK_ORCA') or os.environ.get('ORCA_CLI_COMMAND') or shutil.which('orca')
    if not executable:raise RuntimeError('Orca CLI not found.')
    worktrees=rows(command([executable,'worktree','ps','--json']),'worktrees')
    repos=rows(command([executable,'repo','list','--json']),'repos')
    return map_orca(worktrees,repos)

def claude():
    executable=shutil.which('claude')
    if not executable:raise RuntimeError('Claude CLI not found.')
    return [clean_agent(x,'claude','Claude live') for x in rows(command([executable,'agents','--json']),'sessions')],[]

def telemetry():
    path=STATE/'events.sqlite'
    if not path.exists():raise RuntimeError('No lifecycle observations yet; start a new hooked session.')
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as conn:
        conn.row_factory=sqlite3.Row
        values=[dict(x) for x in conn.execute('SELECT * FROM sessions ORDER BY updated_at DESC LIMIT 200')]
    if not values:raise RuntimeError('No lifecycle observations yet; start a new hooked session.')
    now=time.time();agents=[]
    for value in values:
        item=dict(value);item['project']=Path(item['path']).name if item['path'] else 'Unassigned'
        item['source']='Local lifecycle hook';item['confidence']='observed'
        if now-item['updated_at']>120 and item['state']!='stopped':
            item['state']='unknown'  # No heartbeat: never assert a stale process is alive.
        agents.append(item)
    return agents,[]

def codex_history():
    paths=sorted(CODEX.glob('state_*.sqlite'))
    if not paths:return [],[]
    with closing(sqlite3.connect(paths[-1].resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as conn:
        conn.row_factory=sqlite3.Row
        columns={r[1] for r in conn.execute('PRAGMA table_info(threads)')}
        required={'id','cwd','title','updated_at','archived'}
        if not required<=columns:raise RuntimeError('Codex session schema changed; history adapter needs an update.')
        optional=[x for x in ('agent_role','attached_thread_parent_id') if x in columns]
        query='SELECT id,cwd,title,updated_at'+(' ,'+','.join(optional) if optional else '')+' FROM threads WHERE archived=0 ORDER BY updated_at DESC LIMIT 40'
        values=[dict(x) for x in conn.execute(query)]
    agents=[]
    for value in values:
        item=clean_agent(value,'codex','Codex recent history')
        item.update(state='recent',updated_at=value['updated_at'],confidence='historical',role=value.get('agent_role') or 'general',parent_id=value.get('attached_thread_parent_id') or '')
        agents.append(item)
    return agents,[]

def discover_projects():
    configured=os.environ.get('AGENT_DESK_PROJECT_ROOTS')
    roots=[Path(p).expanduser() for p in configured.split(os.pathsep)] if configured else [HOME/'orca/projects',HOME/'Projects',HOME/'Developer']
    found=[]
    for root in roots:
        if not root.is_dir():continue
        for candidate in sorted(root.iterdir()):
            if candidate.is_dir() and (candidate/'.git').exists():
                found.append({'name':candidate.name,'path':str(candidate),'branch':''})
    return found

def deduplicate(items):
    # Pane identity joins Orca roots with lifecycle sessions. Thread ids join children/history.
    result=[];aliases={}
    def identities(item):
        provider=item['provider'];identity=item['id'].removeprefix(provider+':')
        keys=[(provider,'id',identity)]
        if item.get('pane_key') and not item.get('parent_id'):
            keys.append((provider,'pane',item['pane_key']))
        return keys
    for item in items:
        keys=identities(item)
        index=next((aliases[key] for key in keys if key in aliases),None)
        if index is None:
            index=len(result);result.append(dict(item))
        else:
            target=result[index]
            # Earlier live sources own liveness. Later sources can enrich missing detail.
            for field in ('task','path','parent_id'):
                if not target.get(field) and item.get(field):target[field]=item[field]
            if target.get('role') in ('general','unspecified','default') and item.get('role') not in ('general','unspecified','default'):
                target['role']=item['role']
        for key in keys:aliases[key]=index
    return result

def canonicalize_paths(items):
    for item in items:
        path=item.get('path')
        if not path or not Path(path).exists():
            continue
        original=Path(path)
        canonical=original.resolve()
        item['path']=str(canonical)
        for field in ('name','project'):
            if item.get(field)==original.name:
                item[field]=canonical.name
    return items

def installed_configuration():
    """Read installed client metadata only; no dependency on another source checkout."""
    roles={}
    for path in sorted((CODEX/'agents').glob('*.toml')):
        try:
            data=tomllib.loads(path.read_text())
            name=str(data.get('name') or path.stem)
            roles[name]={'name':name,'description':str(data.get('description') or 'Installed Codex role.')}
        except (OSError,UnicodeError,tomllib.TOMLDecodeError):
            continue
    for path in sorted((CLAUDE/'agents').glob('*.md')):
        try:
            text=path.read_text();metadata={}
            if text.startswith('---\n'):
                for line in text.split('---',2)[1].splitlines():
                    key,separator,value=line.partition(':')
                    if separator and key.strip() in ('name','description'):
                        value=value.strip()
                        if value.startswith('"'):
                            try:value=json.loads(value)
                            except json.JSONDecodeError:continue
                        else:value=value.strip("'")
                        if value not in ('>','|','>-','|-'):metadata[key.strip()]=value
            name=str(metadata.get('name') or path.stem)
            roles.setdefault(name,{'name':name,'description':str(metadata.get('description') or 'Installed Claude role.')})
        except (OSError,UnicodeError):
            continue
    def read(path):
        try:return path.read_text().strip()
        except (OSError,UnicodeError):return ''
    codex=read(CODEX/'AGENTS.md');claude=read(CLAUDE/'CLAUDE.md')
    policy={'codex':bool(codex),'claude':bool(codex and codex in claude)}
    return sorted(roles.values(),key=lambda role:role['name']),policy

def snapshot():
    agents=[];projects=[];sources=[]
    collectors=[('Orca',orca),('Claude sessions',claude),('Lifecycle hooks',telemetry),('Codex history',codex_history)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        jobs=[(name,executor.submit(fn)) for name,fn in collectors]
        for name,job in jobs:
            try:
                items,places=job.result();agents.extend(items);projects.extend(places)
                sources.append({'name':name,'ok':True,'error':''})
            except Exception as error:
                sources.append({'name':name,'ok':False,'error':str(error)[:180]})
    agents=deduplicate(canonicalize_paths(agents))
    projects.extend(discover_projects())
    projects=canonicalize_paths(projects)
    for item in agents:
        if item['path']:projects.append({'name':item['project'],'path':item['path'],'branch':''})
    by_path={}
    for item in projects:
        if item['path'] and item['path'] not in by_path:by_path[item['path']]=item
    roles,policy=installed_configuration()
    return {'updated_at':time.time(),'stale':False,'interval':INTERVAL,'sources':sources,'agents':agents,
            'projects':sorted(by_path.values(),key=lambda x:x['name'].lower()),'roles':roles,
            'policy':policy}

CACHE={'stale':True,'updated_at':0,'interval':INTERVAL,'sources':[],'agents':[],'projects':[],'roles':[],'policy':{'codex':False,'claude':False}}
LOCK=threading.Lock()

def poll():
    global CACHE
    while True:
        try:
            value=snapshot()
            with LOCK:CACHE=value
        except Exception:
            with LOCK:
                CACHE=dict(CACHE,stale=True)
                CACHE['sources']=[x for x in CACHE.get('sources',[]) if x.get('name')!='Tracker']+[{'name':'Tracker','ok':False,'error':'Snapshot collection failed; displayed activity is stale.'}]
        time.sleep(INTERVAL)

def current_snapshot(value, now=None):
    now=time.time() if now is None else now
    stale=value.get('stale',False) or not value.get('updated_at') or now-value['updated_at']>max(20,INTERVAL*4)
    result=dict(value,stale=bool(stale))
    result['agents']=[dict(item,state='unknown',confidence='stale observation') if stale and item['state'] in ('working','waiting','idle') else dict(item) for item in value.get('agents',[])]
    return result

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        expected=f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') not in (expected,f'localhost:{self.server.server_port}'):
            self.send_error(403);return
        origin=self.headers.get('Origin')
        if origin and origin not in ('http://'+expected,f'http://localhost:{self.server.server_port}'):
            self.send_error(403);return
        path=urlsplit(self.path).path
        if path=='/api/status':
            with LOCK:data=json.dumps(current_snapshot(CACHE)).encode()
            mime='application/json'
        elif path in ('/','/index.html','/app.js','/style.css'):
            name='index.html' if path=='/' else path[1:]
            data=(ROOT/'dashboard'/name).read_bytes()
            mime={'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8'}[name.rsplit('.',1)[1]]
        else:
            self.send_error(404);return
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers();self.wfile.write(data)
    def log_message(self,*args):pass

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=4317);parser.add_argument('--once',action='store_true');args=parser.parse_args()
    if args.once:
        print(json.dumps(snapshot(),indent=2));raise SystemExit()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    threading.Thread(target=poll,daemon=True).start()
    print(f'Orca Agent Tracker: http://127.0.0.1:{args.port}',flush=True)
    server.serve_forever()
