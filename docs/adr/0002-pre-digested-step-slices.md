# Pre-Digested Step Slices for Context Load Reduction

Loading an entire campaign brief into every downstream step skill floods the agent's context window with irrelevant rules and invites attention degradation. We decided to have the guidelines ingestion step pre-compile isolated configuration slices directly into `.clipping_state.json` under `steps[<step>].params` (e.g. hook duration for hook hunter, color hexes for captions, LUFS targets for QC).

## Status

Accepted

## Considered Options

- **Full brief re-parsing by every step**: Downstream skills read the raw brief every time. Rejected because it wastes tokens and allows step skills to reinterpret or hallucinate rules.
- **Pre-digested parameter slices in state**: Ingestion parses once and extracts exact parameter blocks for each downstream consumer.

## Consequences

- Enforces progressive disclosure: downstream skills only consume their specific slice.
- Changes to the brief require running re-ingestion to refresh all step slices.
