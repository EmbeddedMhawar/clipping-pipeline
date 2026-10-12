# Strict Sequential Step Gating with Force Override

Agents frequently attempt to jump ahead in multi-step video pipelines (such as attempting vertical assembly before transcription and hook selection are confirmed). We decided to enforce hard pre-flight checks in the state CLI that reject downstream step execution unless prior prerequisite steps have status `"completed"` and `"approved": true`, while providing an explicit `--force` flag for intentional editor bypass.

## Status

Accepted

## Considered Options

- **Advisory step warnings**: Alerting the agent without exiting on non-approval. Rejected because agents routinely ignore advisory warnings and proceed with missing inputs.
- **Strict hard-block with `--force`**: The CLI exits with code 1 if prerequisites are missing, requiring deliberate intent (`--force`) to proceed out of sequence.

## Consequences

- Steps cannot run in an uncalibrated vacuum.
- Automated tests or human editors can still jump to arbitrary steps using `--force`.
