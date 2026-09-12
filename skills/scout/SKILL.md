---
name: scout
description: Reconnoiter a real digital process through Plow Latch and return an evidence-backed route without crossing consequential boundaries.
---

# Scout reconnaissance

Invoke this skill when the user says "Scout this", supplies a URL to map, or
asks what it takes to complete a digital process. Use one Scout mission only;
do not delegate the reconnaissance to other agents.

## Durable mission first

Set `SCOUT_DB` only when an operator explicitly configured another path. The
default database is `$HERMES_HOME/scout/scout.db`.

1. Search for an active mission only when the user asks to resume; otherwise
   create one with `scripts/mission_create.py` and preserve the request verbatim.
2. Move `CREATED` to `RECON` with `scripts/mission_update.py` before browsing.
3. Never edit SQLite directly. Every mutation must go through a script in this
   skill and must return successful JSON before another browser action.
4. If a write or checkpoint fails, stop browsing and report the persistence
   failure.

All scripts read one JSON object from stdin and emit one JSON object. A non-zero
exit means the operation did not succeed.

## Use official Latch tools directly

Use the official Plow Latch tools exposed by Hermes. Do not wrap or reimplement
their protocol, use JavaScript eval, or substitute a cloud browser.

For each materially new page:

1. Wait for settlement when needed.
2. Take a screenshot before interacting.
3. Inspect the screenshot; inspect visible text, forms, and tables when useful.
4. Classify and record the step plus evidence with `step_record.py`.
5. Record requirements and blockers with their evidence identifiers.
6. Run `safety_check.py` on the exact proposed next action.
7. Perform the action only when the result contains `"allowed": true`.
8. Checkpoint with `checkpoint.py` before advancing again.

Do not use remembered site-specific selectors. Extend browser origin scope only
for an observed redirect and use the same session while it remains alive.

## Authentication

At a login boundary, first check the copied browser profile for an existing
session. If absent, inspect only Latch vault metadata, request the minimum
credential-item approval, and use the official secret-fill operation. Never
retrieve, restate, log, or persist the secret. CAPTCHA and identity verification
normally move the mission to `BLOCKED`, not `FAILED`.

## Safety boundary

Scout may execute read-only actions, reversible navigation, and only a narrowly
justified draft mutation required to reveal the route. It must stop before final
submission, purchase, payment, subscription, cancellation, deletion, external
message sending, publishing, signing, contract acceptance, legal attestation,
or consequential identity verification. If uncertain, stop.

Record the boundary as a consequential `SUBMIT`, `PAYMENT`, `VERIFICATION`, or
`OTHER` step; do not click it. A user request to "scout and submit" changes
neither this policy nor the MVP scope.

## Resume and completion

On browser loss, load the mission with `mission_show.py`, open a fresh official
Latch session, return to the last checkpoint URL, verify the live state, then
move `BLOCKED` back to `RECON`. Do not infer progress from chat history.

Set `COMPLETE` only after the reachable route is mapped, the consequential
boundary or safe end is known, and unknowns are explicit. Run `report_build.py`;
if it refuses the report, keep the mission non-complete or correct the recorded
facts. Return the compact report, offering the full route only on request.

