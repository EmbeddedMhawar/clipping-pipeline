# Agent Guidelines

## Agent skills

### Issue tracker

GitHub Issues via `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical roles matching label names (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context (`GLOSSARY.md` and `docs/adr/` at repo root). See `docs/agents/domain.md`.

### Step handoff

Post-step summary and multi-conversation prompt handoff. After each approved step in the clipping pipeline, summarize what was done, advise opening a new conversation, and provide the exact prompt: `Campaign: <Campaign Title> (<campaign-slug>) proceed with Step <N> (<step-name>)`. See `docs/agents/step-handoff.md`.

### Remotion & HyperFrames rendering contracts

Official upstream skills (`skills/remotion-best-practices/SKILL.md`, `skills/hyperframes/SKILL.md`, `skills/hyperframes-cli/SKILL.md`) and primary-source contract reference (`docs/research/remotion-hyperframes-official-skills.md`). Consult when authoring or modifying `.remotion.json`, `remotion/*.tsx` compositions, `@remotion/captions` tracks, or `.hyperframes.html` motion graphics overlays.
