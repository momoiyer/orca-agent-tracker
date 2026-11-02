#!/usr/bin/env python3
"""Manage Orca Agent Tracker's macOS login service. Foreground dashboard works elsewhere."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
LABEL='local.agent-desk'
PLIST=Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
STATE=Path(os.environ.get('AGENT_DESK_STATE',str(Path.home()/'.local/state/agent-desk'))).expanduser()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--install',action='store_true');group.add_argument('--remove',action='store_true');group.add_argument('--status',action='store_true')
    args=parser.parse_args()
    if sys.platform!='darwin':raise SystemExit('Run python3 dashboard/server.py on this OS; login service currently supports macOS.')
    domain=f'gui/{os.getuid()}'
    if args.status:raise SystemExit(subprocess.run(['launchctl','print',f'{domain}/{LABEL}']).returncode)
    if PLIST.exists():
        old=plistlib.loads(PLIST.read_bytes())
        if old.get('Label')!=LABEL or not any('dashboard/server.py' in str(x) for x in old.get('ProgramArguments',[])):
            raise SystemExit('Unrelated service uses this label; refusing changes.')
    if args.remove:
        subprocess.run(['launchctl','bootout',domain,str(PLIST)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        PLIST.unlink(missing_ok=True);print('Login service removed; activity data retained.');return
    STATE.mkdir(parents=True,exist_ok=True,mode=0o700);PLIST.parent.mkdir(parents=True,exist_ok=True)
    paths=[str(Path(shutil.which(command)).parent) for command in ('claude','codex','orca') if shutil.which(command)]
    paths.extend(['/opt/homebrew/bin','/usr/local/bin','/usr/bin','/bin'])
    config={'Label':LABEL,'ProgramArguments':[sys.executable,str(ROOT/'dashboard/server.py')],
      'WorkingDirectory':str(ROOT),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':15,
      'StandardOutPath':str(STATE/'server.log'),'StandardErrorPath':str(STATE/'server-error.log'),
      'EnvironmentVariables':{'PATH':':'.join(dict.fromkeys(paths)),'HOME':str(Path.home())}}
    for name in ('CODEX_HOME','CLAUDE_CONFIG_DIR','AGENT_DESK_ORCA','AGENT_DESK_PROJECT_ROOTS','AGENT_DESK_STATE'):
        if os.environ.get(name):config['EnvironmentVariables'][name]=os.environ[name]
    if PLIST.exists():
        backup=STATE/'service-before-update.plist';backup.write_bytes(PLIST.read_bytes());backup.chmod(0o600)
        subprocess.run(['launchctl','bootout',domain,str(PLIST)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    PLIST.write_bytes(plistlib.dumps(config));PLIST.chmod(0o600)
    subprocess.run(['launchctl','bootstrap',domain,str(PLIST)],check=True)
    print('Orca Agent Tracker starts at login: http://127.0.0.1:4317')
    print('Keep the checkout in place; reinstall service after moving it.')

if __name__=='__main__':main()
