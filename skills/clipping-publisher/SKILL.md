---
name: clipping-publisher
description: Short-form clipping publisher and multi-platform publishing engine. Publish clips across brand cluster channels with zero same-platform duplication, warmup gating, YouTube API and BrowserOS Neo fallback, mobile device delivery, and publication manifest receipts.
---

# Multi-Platform Publisher (clipping-publisher)

Step 8 distribution and publishing engine for the Antigravity Short-Form Clipping Pipeline. Governs multi-platform publishing across brand cluster channels, prevents duplicate same-platform allocation, enforces algorithmic warmup gating, delivers mobile packages with companion captions, executes direct YouTube Shorts uploads with BrowserOS Neo fallback, updates portfolio quotas, and generates verifiable publication manifests.

Context pointers:
- Domain terminology: [`GLOSSARY.md`](../../GLOSSARY.md)
- Workspace channel portfolio schema: [`references/CHANNEL_PORTFOLIO_SCHEMA.md`](../../references/CHANNEL_PORTFOLIO_SCHEMA.md)
- Publishing architecture decision: [`docs/adr/0010-dedicated-pipeline-publishing-step.md`](../../docs/adr/0010-dedicated-pipeline-publishing-step.md)
- Pipeline state engine: `scripts/clipping_state.py`
- Publisher engine: `scripts/clipping_publisher.py`

---

## Operating Protocol

Follow this 4-step sequence on every publishing run:

### 1. State & Pre-Flight Gate Inspection

Inspect pipeline readiness and enforce prerequisite Step 7 completion before executing publication:

```bash
python3 scripts/clipping_state.py validate --step clipping-publisher --dir <project-dir>
```

- **Exit Code `0`**: Gate cleared. Proceed to step 2.
- **Exit Code `2`**: Pre-flight gate blocked. Step 7 (`clipping-qc-packager`) is incomplete or unapproved. Halt publishing immediately.
- Extract isolated Step Slice:
  ```bash
  python3 scripts/clipping_state.py get-step-config --step clipping-publisher --dir <project-dir>
  ```

### 2. Brand Cluster Matching & Zero Duplicate Platform Allocation

Group target channels by Brand Cluster (`account_name`) and enforce zero same-platform duplicate allocation:

```bash
python3 scripts/clipping_publisher.py status --brand-cluster "<brand-cluster>" --channels <channels.json>
```

Allocation rules:
- **Brand Cluster Grouping**: Group channels by matching `account_name`. A single clip distributes across distinct platforms under one brand identity.
- **Zero Same-Platform Duplication**: At most 1 channel per platform per run. Allocating multiple channels on the same platform fails validation to protect against duplicate content penalties and algorithmic shadowbans.
- **Warmup Gating**:
  * TikTok and Instagram Reels: Prohibit posting for accounts in `Cold Lurker` or `Account Cooldown`. Require `daily_post_limit > 0` and `posts_today < daily_post_limit`.
  * YouTube Shorts: Eligible when status is `active` and daily post limit is not exceeded.
- Dry-run validation check:
  ```bash
  python3 scripts/clipping_publisher.py publish \
    --brand-cluster "<brand-cluster>" \
    --channels <channels.json> \
    --video <path/to/clip.mp4> \
    --project-dir <project-dir> \
    --dry-run
  ```

### 3. Multi-Platform Publication Execution

Execute multi-platform publishing for the approved video package:

```bash
python3 scripts/clipping_publisher.py publish \
  --brand-cluster "<brand-cluster>" \
  --channels <channels.json> \
  --video <path/to/clip.mp4> \
  --clip-id "<clip-id>" \
  --caption-hook "<headline-hook>" \
  --caption-closer "<approved-closer>" \
  --project-dir <project-dir> \
  --privacy-status public
```

Execution paths:
- **YouTube Shorts Publishing**:
  * Direct Data API v3 upload using OAuth tokens configured in `~/.config/clipping-pipeline/youtube/<channel_id>_token.json`.
  * Verify token status prior to publishing: `python3 scripts/clipping_publisher.py verify-tokens --channels <channels.json>`.
  * Defaults to `public` visibility; accepts `--privacy-status unlisted` or `private`.
  * **BrowserOS Neo Fallback**: Triggered automatically when OAuth tokens are missing, token refresh fails, or Google API quota (`quotaExceeded` / HTTP 403) is exhausted. Stages automation payload for YouTube Studio (`https://studio.youtube.com`) and logs fallback session.
- **TikTok & Instagram Reels Mobile Delivery**:
  * Enforces manual mobile upload requirement (per ADR 0009).
  * Bundles rendered MP4 with companion `caption.txt` containing hook, description, hashtags, and approved closer.
  * Transfers package via channel's configured protocol: `cloud_folder`, `adb_push`, `local_qr`, or `webhook`.
  * Increments `posts_today` in `channels.json` and records post log entry with status `staged_mobile`.

### 4. Publication Manifest Persistence & Step Approval

Persist execution receipt and complete pipeline step approval:

1. **Verify Publication Manifest Persistence**:
   The publisher CLI automatically records a structured receipt array in `.clipping_state.json` under `steps.clipping-publisher.params.publication_manifest`. Inspect state to confirm receipt:
   ```bash
   python3 scripts/clipping_state.py status --dir <project-dir> --json
   ```
   Each receipt entry contains: `clip_id`, `brand_cluster`, `timestamp`, `platform`, `channel_id`, `delivery_method`, `post_url`, and `status`.

2. **Approve Step 8**:
   ```bash
   python3 scripts/clipping_state.py approve --step clipping-publisher --dir <project-dir>
   ```
   - Succeeds (Exit Code `0`) when `publication_manifest` is present and non-empty.
   - Rejects approval (Exit Code `1`) if publication manifest is missing or empty.
   - Editorial override flag (`--force`) bypasses validation check if instructed.

3. **Confirm Pipeline Completion**:
   ```bash
   python3 scripts/clipping_state.py status --dir <project-dir>
   ```
   Confirm all 8 pipeline steps reflect completed and approved status.

---

## Completion Criteria

The clipping-publisher execution is complete ONLY when:
1. Pre-flight gate cleared (`scripts/clipping_state.py validate --step clipping-publisher` returned exit code 0).
2. Zero duplicate same-platform allocation enforced across candidate channels.
3. Warmup readiness confirmed for all target channels (zero Cold Lurker or Account Cooldown posts).
4. YouTube Shorts published via Data API v3 or staged via BrowserOS Neo fallback.
5. TikTok and Instagram Reels delivered to mobile device alongside companion `caption.txt`.
6. Daily posting quota incremented in `channels.json` for all allocated channels.
7. Structured `publication_manifest` recorded in `.clipping_state.json`.
8. Step approved via `scripts/clipping_state.py approve --step clipping-publisher` with exit code 0.
