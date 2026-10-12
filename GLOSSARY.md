# Clipping Pipeline

A modular, stateful short-form video clipping system that decomposes the video editing and campaign compliance workflow into discrete agent skills.

## Language

**Campaign Brief**:
A normalized configuration document (`campaign_brief.json`) declaring all hard rules, payout thresholds, platform tags, and compliance bounds for a video campaign.
_Avoid_: Guidelines doc, rule sheet, client prompt, campaign spec

**State File**:
The canonical project-local JSON document (`.clipping_state.json`) recording active pipeline progress, approved steps, and pre-digested step parameters.
_Avoid_: Cache, session store, pipeline memory

**Step Slice**:
A pre-digested parameter subset extracted from the campaign brief into the state file, tailored exclusively to a single downstream step skill.
_Avoid_: Sub-config, partial brief, step parameters

**Transition Gate**:
A strict pre-flight check in the state engine preventing downstream skills from executing until prior steps are approved.
_Avoid_: Checkpoint, blocker, step barrier

**Router Skill**:
The top-level orchestrator skill (`clipping-pipeline`) that inspects state and coordinates the 7-step sequence without performing editing tasks directly.
_Avoid_: Master agent, manager skill, pipeline runner

**Step Skill**:
An atomic, modular skill responsible for one vertical phase of the clipping pipeline (such as `clipping-guidelines` or `clipping-hook-hunter`).
_Avoid_: Sub-skill, worker skill, task script

**Tier-1 Safe Default**:
A baseline viral parameter (e.g. 25s–45s duration, 0–3s hook) automatically injected when a campaign brief is silent on a requirement.
_Avoid_: Fallback setting, system preset
