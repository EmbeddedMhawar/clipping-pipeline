# 0010: Dedicated Pipeline Publishing Step and Step 7 Decoupling

In earlier pipeline iterations, Step 7 (`clipping-qc-packager`) coupled quality control auditing (loudness normalization, caption closers, duration bounds, Whop packaging) with channel portfolio queries and mobile device transfer dispatch. This bloated Step 7's operational scope, entangled video compliance verification with channel distribution, and prevented direct API publishing or multi-platform brand cluster orchestration from having an isolated lifecycle stage.

To enforce single responsibility and provide clean failure domains, Step 7 is decoupled into a pure audio/visual quality control and Whop packaging stage, while channel portfolio queries, brand clustering, device delivery, and video uploads are moved to a dedicated Step 8 (`clipping-publisher`) backed by `scripts/clipping_publisher.py`.

## Status

Accepted

## Considered Options

- **Overloading Step 7 (`clipping-qc-packager`)**: Retaining publishing, mobile device transfer, and YouTube API uploads directly inside Step 7. Rejected because media QC compliance is logically distinct from channel distribution; bundling them complicates retry semantics when publication fails after QC validation has succeeded.
- **Decoupled Step 8 (`clipping-publisher`)**: Expanding `PIPELINE_STEPS` in `scripts/clipping_state.py` from 7 to 8 sequential steps ending in `clipping-publisher`. Step 7 no longer requires `channels.json` or injects channel slices, and Step 8 enforces a strict pre-flight gate requiring Step 7 approval (`Exit 2` if unapproved, `Exit 0` when approved). Chosen for clear architectural boundaries, isolated execution contexts, and reliable auditability.

## Consequences

- `scripts/clipping_state.py` defines an 8-step pipeline sequence ending in `clipping-publisher`.
- `clipping-qc-packager` is decoupled from workspace `channels.json` and focuses purely on -14 LUFS loudness audits, caption closers, duration checks, and Whop packaging.
- `clipping-publisher` manages brand cluster matching, zero same-platform duplicate allocation, warmup gating, mobile device transfer with caption bundling, and YouTube Shorts publishing.
- Pre-flight transition checks block Step 8 until Step 7 (`clipping-qc-packager`) is approved.
- Publication receipts are recorded persistently in `.clipping_state.json` under `steps.clipping-publisher.params.publication_manifest`.
