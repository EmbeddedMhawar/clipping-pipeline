# Two-Tier Rule Normalization: Global Rules with Platform Matrix

Social campaigns routinely enforce contradictory formatting rules across channels (such as YouTube Shorts allowing tagged creator handles `@mpj` while TikTok and Instagram Reels forbid clickable tags and require plain text). We decided to structure `campaign_brief.json` with a shared `global_rules` baseline paired with an explicit `platforms` matrix (`youtube_shorts`, `tiktok`, `instagram_reels`).

## Status

Accepted

## Considered Options

- **Single flat ruleset**: Forcing one rule across all platforms. Rejected because it causes non-compliance and payout disqualification on platforms with distinct rules.
- **Separate brief files per platform**: Creating `tiktok_brief.json`, `youtube_brief.json`, etc. Rejected due to configuration sprawl and duplicate maintenance.
- **Unified brief with platform matrix**: Single source of truth containing global invariants and targeted platform overrides.

## Consequences

- The guidelines skill normalizes all briefs into this uniform structure.
- Downstream packaging skills query platform-specific slices cleanly.
