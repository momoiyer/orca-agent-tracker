# Orca Agent Tracker

A local, read-only dashboard for Orca workspaces and Codex/Claude sessions. It shows providers, reported assignments, child agents, installed roles, project checkouts, waiting states, and source freshness. It is independent of `ai-config`: this repository observes installed clients and does not install their working rules or specialist roles.

## Requirements and installation

Use Python **3.11+**, Orca, and the Codex/Claude clients you want to observe. JavaScript assets need no build or runtime dependencies; Node is needed only for the syntax check. Adapters were validated with Codex CLI 0.166.0 and Claude Code 2.1.316. Source schemas can change with client releases.

Clone this repository into a permanent directory. From its root:

```sh
python3 scripts/tracking.py
python3 scripts/tracking.py --apply
python3 dashboard/server.py
```

Open **http://127.0.0.1:4317**. The hook installer previews by default, preserves existing settings and Orca hooks, and backs up files before changing them. Codex may require you to review and trust the new hooks before they run; the installer never bypasses that review. Start fresh client sessions after installing or relocating hooks.

For macOS login startup:

```sh
python3 scripts/desk_service.py --install
python3 scripts/desk_service.py --status
```

The service runs while your user is logged in and the laptop is awake. It is not a remote, always-online monitor. On other operating systems, run the foreground server or configure your own service manager. Keep the checkout and Python interpreter in place; reinstall hooks and the service after moving them.

If Orca's normal launcher fails, verify and explicitly select the installed app's launcher rather than silently switching builds. A standard macOS installation can use:

```sh
export AGENT_DESK_ORCA=/Applications/Orca.app/Contents/Resources/bin/orca
python3 scripts/desk_service.py --install
```

The service installer captures the configured overrides. `CODEX_HOME` and `CLAUDE_CONFIG_DIR` select client homes. `AGENT_DESK_STATE` overrides private state storage. `AGENT_DESK_PROJECT_ROOTS` supplies project parent directories separated by the OS path separator (`:` on macOS/Linux). Defaults check immediate Git directories under `~/orca/projects`, `~/Projects`, and `~/Developer`; no whole-disk scan runs.

## What the view establishes

The browser refreshes about every five seconds. Orca and Claude CLI adapters supply live reports; lifecycle hooks observe starts, tools, approval waits, stops, and subagents. Recent Codex history is explicitly historical. Unavailable sources, missing roles, stale observations, and unsupported schemas do not become invented activity. Sessions without a working integration may not be observable. A completed turn in an attached CLI is idle, not a terminated process.

Roles are read from installed Codex TOML and Claude Markdown definitions, without requiring any sibling configuration checkout. The shared-policy indicators mean a nonempty Codex personal policy exists and its text also appears in Claude's personal file. They are presence/comparison checks, not proof of policy quality, provenance, or model compliance. Claude role descriptions using complex YAML can fall back to a generic description.

The dashboard binds to loopback, rejects unexpected Host/Origin headers, and exposes no controls for starting, stopping, or messaging agents. Activity labels are the latest reported assignments, not a guaranteed account of internal reasoning or current file edits.

## Privacy, storage, and restore

Default private state is `~/.local/state/agent-desk/`. Lifecycle records live in `events.sqlite`; short task labels may contain prompt text (up to 240 characters). The receiver excludes tool inputs/results and transcript bodies. A 30-day retention window is enforced when new hook events arrive. Existing source titles can also appear locally. Activity, client credentials, logs, personal settings, and backups must never be added to Git.

New hook backups are stored under `setup-backups/` in the selected state directory. Each apply prints its exact backup path:

```sh
python3 scripts/tracking.py --restore BACKUP_DIRECTORY
```

Restore refuses to overwrite later edits and accepts only the selected clients' hook/settings files. Before this project was extracted, hook backups lived under the Codex home's `setup-backups/`; those historical snapshots remain untouched and can be restored with their original installer. New tracker backups are independent of the AI configuration repository.

To stop automatic startup:

```sh
python3 scripts/desk_service.py --remove
```

This retains activity and hook configuration. Restore the relevant tracking backup separately to remove those handlers; restore successive updates in reverse order. A foreground server stops with Ctrl-C.

The legacy service label `local.agent-desk`, hook marker `# agent-desk-managed`, and state directory are intentionally retained so extraction preserves existing activity and replaces old handlers rather than duplicating them.

## Development and continuation

```sh
python3 -m unittest discover -s scripts -p 'test_*.py'
node --check dashboard/app.js
python3 scripts/tracking.py --check
```

Tests use disposable synthetic data. See [HANDOFF.md](HANDOFF.md) for architecture, migration checks, and a focused starting point for the next chat. Work on personal rules, skills, and agent setup belongs in the separate `ai-config` repository. No changes here commit, push, or publish a GitHub repository automatically.
