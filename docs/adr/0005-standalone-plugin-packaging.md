# Packaging as a Standalone Plugin with GitHub Publishing

The clipping pipeline needs to operate across multiple video editing workspaces without polluting individual projects or tangling with existing monolithic plugins. We decided to package the suite as an independent Antigravity plugin repository (`clipping-pipeline`) hosted at `https://github.com/EmbeddedMhawar/clipping-pipeline`, locally located at `~/Work/clipping-pipeline`, and symlinked into `~/.gemini/config/plugins/clipping-pipeline`.

## Status

Accepted

## Considered Options

- **Loose workspace skills in `.agents/skills`**: Project-specific copy-pasting. Rejected because updates cannot propagate to other video projects.
- **Monolithic integration into `filmcraft` plugin**: Embedding within FilmCraft. Rejected to keep the clipping state engine decoupled from specific NLE editors.
- **Dedicated plugin repository**: Standalone version control, shared global discovery, and portable execution across any directory.

## Consequences

- The plugin is version-controlled independently under the `EmbeddedMhawar` GitHub account.
- Any project can consume the skills and state scripts immediately via the Antigravity plugin symlink.
