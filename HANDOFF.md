# Tracker continuation

This repository was extracted from ai-config so a separate chat can continue tracker development without changing personal AI setup. The two checkouts are independent; the tracker reads installed client metadata, not the other repository's source.

## Current architecture

- `dashboard/server.py`: read-only loopback HTTP server and cached snapshots; Orca workspace/repo CLI adapter, Claude session CLI adapter, lifecycle DB adapter, and explicitly historical Codex SQLite adapter.
- `dashboard/telemetry.py`: fail-open lifecycle receiver. Stable parent/child IDs and short prompt labels are stored locally; tool inputs and transcript bodies are excluded.
- `dashboard/index.html`, `app.js`, `style.css`: no-build UI with polling, filters, source errors, stale suppression, history separation, installed roles, and policy-presence indicators.
- `scripts/tracking.py`: merges only marked handlers into client settings; preserves unrelated settings and Orca integration.
- `scripts/file_state.py`: independent snapshot, atomic-write, backup, restore, and race protection for hook/settings files.
- `scripts/desk_service.py`: macOS login service. Foreground server works on other supported Python platforms; automatic startup there is not implemented.

## Migration invariants

Retain `local.agent-desk`, `# agent-desk-managed`, and `~/.local/state/agent-desk` so existing sessions/data survive. Reapply tracking hooks and reinstall the service from this checkout before calling migration complete. The parent chat handles those activation steps and Orca/GitHub project registration; do not infer they ran from these source files alone.

Useful confirmation commands:

```sh
python3 scripts/tracking.py --check
python3 scripts/desk_service.py --status
python3 -m unittest discover -s scripts -p 'test_*.py'
node --check dashboard/app.js
```

Visit http://127.0.0.1:4317 and check source health, provider/project filters, child identities, recent-history separation, and narrow-screen layout. New Codex hook definitions may need native trust approval. Never bypass it merely to make the health indicator green.

## Known limits and next work

Coverage depends on client/Orca integrations. Hook observations expire to unknown without fresh evidence; old session history does not prove activity. Role names or task assignments absent from a source remain unspecified. Codex's local session SQLite schema and CLI JSON formats may change; adapters intentionally report schema mismatches. Installed Claude role metadata supports simple frontmatter scalars, with a generic description for complex YAML. Policy matching establishes text presence only.

Keep further work scoped to user-requested tracker improvements. Add synthetic regression coverage for any new source shape, reproduce reported status bugs before changing joins, and preserve the local-only data boundary. Personal setup refinements continue in the ai-config chat.
