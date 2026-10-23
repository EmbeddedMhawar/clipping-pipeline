---
name: clipping-guidelines
description: Ingest and normalize clipping guidelines and campaign briefs (Whop rules, payout rules) into structured schema with Tier-1 defaults and approval gate.
---

# Clipping Guidelines Ingestion & Approval Gate

Step 1 of the Short-Form Clipping Pipeline. Ingests raw campaign briefs across diverse sources, normalizes them against the schema, injects Cole Corcoran Tier-1 viral defaults for omitted rules, pre-digests parameter slices into pipeline state, and gates progress behind human approval.

See [`references/CAMPAIGN_BRIEF_SCHEMA.md`](../../references/CAMPAIGN_BRIEF_SCHEMA.md) for the authoritative schema specification and default values. Step-specific parameters are extracted dynamically via `scripts/clipping_state.py get-step-config`.

---

## Operating Protocol

Follow these sequential steps on every invocation:

### 1. Ingest Raw Campaign Source
Identify the source format provided by the user:
- **Local Workspace File**: If the user points to a markdown file (e.g. `CAMPAIGN_GUIDELINES.md`), read it via `view_file`.
- **Pasted Text**: If guidelines or campaign requirements are provided directly in the prompt, pass the text string.
- **Remote Web Brief (Whop, Notion, Google Docs, Creator Dashboards)**: Mandate the dedicated agent browser (`BrowserOS Neo`) for all remote web campaign briefs. Do not use headless scrapers, curl, or in-app fetchers. Follow BrowserOS Neo etiquette:
  1. Call `name_session` early with a 2-3 word task label (e.g. `clipping/<project-slug>`), category `work`, and a concise summary.
  2. Open a dedicated tab via `tabs` with action `"new"`. Work only in task-owned tabs.
  3. Navigate to the campaign URL and extract the page markdown using `read` or `run`.
  4. Save the extracted markdown to `<project-dir>/raw_guidelines.md`.
  5. Pass `--file <project-dir>/raw_guidelines.md` to `scripts/ingest_guidelines.py`.
  6. **Disconnection Protocol**: If BrowserOS Neo reports session disconnected, prompt the user to start BrowserOS Neo and check the cockpit; DO NOT silently fall back to headless fetchers.

### 2. Normalize and Inject Tier-1 Defaults
Execute the ingestion normalizer:
```bash
python3 scripts/ingest_guidelines.py \
  --file <path-to-guidelines.md-or-raw_guidelines.md> \
  --dir <project-dir> \
  --output-brief <project-dir>/campaign_brief.json \
  --output-artifact <project-dir>/campaign_brief_review.md
```
Or for inline text:
```bash
python3 scripts/ingest_guidelines.py \
  --text "<raw-guidelines-text>" \
  --dir <project-dir> \
  --output-brief <project-dir>/campaign_brief.json \
  --output-artifact <project-dir>/campaign_brief_review.md
```

The script extracts explicit rules and injects Cole Corcoran Tier-1 defaults tagged `[Default Applied]` when criteria are omitted. For full schema definitions, consult [`references/CAMPAIGN_BRIEF_SCHEMA.md`](../../references/CAMPAIGN_BRIEF_SCHEMA.md). Pre-digested parameter slices for downstream steps are queried via `scripts/clipping_state.py get-step-config`.

### 3. Verify Pre-Digested State Slices
Ensure `.clipping_state.json` contains sliced configurations for downstream steps:
```bash
python3 scripts/clipping_state.py status --dir <project-dir>
```
Inspect step-specific parameter slices as needed:
```bash
python3 scripts/clipping_state.py get-step-config --step clipping-transcription --dir <project-dir>
```
Confirm that:
- `current_step` is `clipping-guidelines`
- `guidelines_approved` is `false`
- `steps["clipping-guidelines"].status` is `awaiting_approval`
- Downstream step parameter slices (`clipping-transcription` through `clipping-qc-packager`) are populated.

### 4. Present Interactive Review Artifact
Present the generated `campaign_brief_review.md` to the user as an artifact with `RequestFeedback: true`. The artifact must clearly exhibit:
1. **Campaign Summary & Economics** (rate, minimum payout floor, clip cap, eligible platforms)
2. **Strict Non-Negotiable Rules** (Tier-1 audience, engagement rate, watermark, closers)
3. **Platform Specific Overrides** (YouTube Shorts API allowed vs TikTok/IG manual mobile only)
4. **Tier-1 Viral Defaults Injected** (auditable list of all items tagged `[Default Applied]`)
5. **Action Required: Approval Gate Prompt** (explicit command to approve or override)

### 5. Enforce Human Approval Gate
Downstream editing steps (`clipping-transcription`, `clipping-hook-hunter`, etc.) remain **strictly blocked** by pre-flight validation gates until approval is recorded.

When the user confirms the brief (or specifies overrides):
```bash
python3 scripts/clipping_state.py approve \
  --step clipping-guidelines \
  --dir <project-dir> \
  [--override key=val ...] \
  [--notes "Human approval confirmed"]
```

Verify approval transition:
```bash
python3 scripts/clipping_state.py validate --step clipping-transcription --dir <project-dir>
```
Exit code `0` confirms the gate is unblocked.

### 6. Post-Step Summary & Conversation Handoff
Following approval:
1. Concisely summarize what was completed (ingested rules, applied Cole Corcoran defaults, initialized step configuration slices).
2. Instruct the user to open a new conversation to run Step 2 (`clipping-transcription`).
3. Provide the exact copy-paste prompt formatted as:
   ```text
   Campaign: <Campaign Title> (<campaign-slug>) proceed with Step 2 (clipping-transcription)
   ```

---

## Completion Criteria

This skill is complete ONLY when all four conditions are met:
1. `campaign_brief.json` exists and satisfies [`references/CAMPAIGN_BRIEF_SCHEMA.md`](../../references/CAMPAIGN_BRIEF_SCHEMA.md).
2. `.clipping_state.json` has step-specific parameter slices populated.
3. Review artifact `campaign_brief_review.md` has been presented with `RequestFeedback: true`.
4. State engine registers `guidelines_approved: true` following user confirmation via `clipping_state.py approve`.
