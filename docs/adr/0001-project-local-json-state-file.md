# Project-Local JSON State File for Pipeline Persistence

Markdown skills lack resident memory between agent turns, risking context loss and state drift across multi-step clipping sessions. We decided to persist all pipeline state in a canonical project-local `.clipping_state.json` file managed by a Python CLI (`clipping_state.py`), ensuring deterministic state transitions that any skill or agent can verify from disk.

## Status

Accepted

## Considered Options

- **Ephemeral chat context**: Passing prior step outputs in chat prompts. Rejected due to token exhaustion and drift.
- **Global ~/.config SQLite database**: Storing all sessions globally. Rejected because multi-project clipping requires colocation with local video media.
- **Project-local JSON state file**: Chosen for transparency, versionability, and seamless inspection by scripts and editors.

## Consequences

- Every project directory maintains its own `.clipping_state.json`.
- Skills and scripts must read from and write to this file through the CLI state helper.
