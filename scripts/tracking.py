#!/usr/bin/env python3
"""Preview/install local tracking hooks for Codex and Claude; Python 3.11+."""
import argparse
import copy
import json
from pathlib import Path
import shlex
import sys

import file_state

EVENTS = ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse',
          'PermissionRequest', 'Stop', 'SessionEnd', 'SubagentStart', 'SubagentStop')
MARKER = '# agent-desk-managed'


def command(provider):
    interpreter = str(Path(sys.executable).resolve())
    receiver = str((file_state.ROOT / 'dashboard/telemetry.py').resolve())
    return shlex.join([interpreter, receiver, '--provider', provider])+' >/dev/null 2>&1 || : '+MARKER


def managed(hook):
    return (isinstance(hook, dict) and hook.get('type') == 'command'
            and isinstance(hook.get('command'), str)
            and hook['command'].endswith(' '+MARKER))


def merge(original, provider):
    """Replace only this installer's marked hooks, preserving all other settings."""
    if provider not in ('codex', 'claude'):
        raise ValueError('Unknown tracking provider: '+provider)
    data = json.loads(original) if original is not None else {}
    if not isinstance(data, dict):
        raise ValueError('Hook/settings file must contain a JSON object.')
    data = copy.deepcopy(data)
    hooks = data.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('Existing hooks must be an object; review before changing it.')
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            raise ValueError(f'Hook groups for {event} must be an array.')
        preserved = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get('hooks'), list):
                raise ValueError(f'Invalid existing hook group for {event}; review before changing it.')
            remaining = [hook for hook in group['hooks'] if not managed(hook)]
            if remaining == group['hooks']:
                preserved.append(group)
            elif remaining:
                group['hooks'] = remaining
                preserved.append(group)
            # A group containing only our marked handlers is owned by this installer.
        hooks[event] = preserved
    for event in EVENTS:
        hooks.setdefault(event, []).append({'hooks': [
            {'type': 'command', 'command': command(provider), 'timeout': 5}
        ]})
    return (json.dumps(data, indent=2, ensure_ascii=False)+'\n').encode()


def plan():
    paths = {file_state.CODEx/'hooks.json': 'codex', file_state.CLAUDE/'settings.json': 'claude'}
    originals = {path: file_state.current(path) for path in paths}
    targets = {path: merge(originals[path], provider) for path, provider in paths.items()}
    changes = {path: content for path, content in targets.items() if content != originals[path]}
    return changes, originals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--apply', action='store_true')
    actions.add_argument('--check', action='store_true')
    actions.add_argument('--restore', metavar='BACKUP_DIRECTORY')
    args = parser.parse_args()
    if args.restore:
        file_state.restore(args.restore)
        return
    if not (file_state.ROOT/'dashboard/telemetry.py').is_file():
        raise ValueError('Tracking receiver is missing from this checkout.')
    changes, originals = plan()
    for path in changes:
        print('Would update tracking hooks:', path)
    if args.check:
        if changes:
            raise SystemExit('Tracking hook configuration differs from this checkout.')
        print('Both tracking hook configurations match; existing settings preserved.')
    elif args.apply and changes:
        file_state.apply(changes, originals)
        print('Installed tracking hooks. Start fresh sessions for both clients.')
        print('Codex may require reviewing and trusting new hook definitions; this installer does not bypass trust.')
    else:
        print(len(changes), 'files differ.', 'Use --apply to install.' if changes else 'No changes needed.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
