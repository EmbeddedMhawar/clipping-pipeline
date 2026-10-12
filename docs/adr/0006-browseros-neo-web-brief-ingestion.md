# BrowserOS Neo for Authenticated Campaign Brief Ingestion

Creator campaign guidelines and reward programs frequently live behind authenticated creator portals (e.g., Whop, Notion, Discord, Google Docs) that enforce session logins and client-side JavaScript rendering. We decided that remote campaign brief extraction must be performed via the dedicated agent browser (`BrowserOS Neo`) rather than headless HTTP fetchers or browser automation embedded directly within pipeline scripts.

## Status

Accepted

## Considered Options

- **Headless HTTP fetching (`read_url_content` / `urllib`)**: Standard library or simple HTTP requests. Rejected because Whop and Notion require active login sessions and client-side rendering, resulting in authentication gates, CAPTCHAs, or blank shells.
- **Embedded browser automation in Python scripts (Playwright / Selenium)**: Installing browser drivers directly into `scripts/ingest_guidelines.py`. Rejected to preserve zero external runtime dependencies and avoid maintaining dual browser login stores.
- **Dedicated agent browser (`BrowserOS Neo`)**: Delegating web navigation, authentication, and markdown extraction to the user's persistent, authenticated agent browser profile via MCP. The agent captures the rendered brief as `<project-dir>/raw_guidelines.md` before invoking the zero-dependency CLI.

## Consequences

- Campaign ingestion succeeds seamlessly on login-protected creator dashboards without credential leakage or manual copying.
- Pipeline CLI scripts remain zero-dependency Python standard library utilities.
- Agents follow dedicated browser etiquette (`name_session`, task-owned tabs, no silent fallback).
