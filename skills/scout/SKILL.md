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

Before the first browser call, read the current `camoufox-browsing` instructions
with `plow_read_skill`. Determine the observed/expected origins, including apex
and wildcard hosts, then call `plow_browser_open`. Keep the returned `session`
private and pass that same handle to every `plow_browser` call. Leave the browser
hidden unless the owner explicitly asks for `headed:true`.

For each materially new page:

1. Use `plow_browser` action `wait` when settlement is needed.
2. Use action `screenshot` before interacting and inspect the returned image.
3. Use actions `text`, `forms`, `tables`, `links`, `url`, or `title` only as useful.
4. Record the step plus screenshot/structural evidence with `step_record.py`.
5. Record requirements, blockers and cost/deadline facts with their evidence IDs.
6. Link known route edges with `step_link.py`.
7. Checkpoint the observed page with `checkpoint.py` before moving past it.
8. Run `safety_check.py` on the exact proposed `goto`, `click`, `fill`,
   `fill_secret`, scope-extension, or other action.
9. Perform the action only when the result contains `"allowed": true`.

Do not use remembered site-specific selectors. Never use Latch action `eval` in
Scout MVP. Read `failed_requests` before retrying: a 401, 403, 429, or site error
is evidence, not permission to loop. Watch `page_count`; inspect `pages` and use
`use_page` for a popup. For an observed redirect outside scope, classify the
request, then call `plow_browser_request` with only the additional origin. Poll
deferred calls with `plow_get_result` when they return a pending handle.

## Authentication

At a login boundary, first inspect whether the browser profile copied by Latch
is already signed in. If absent, call `plow_vault` action `list` with the site as
the query, then `describe` only for the selected item. Ask for the minimum item,
call `plow_browser_request` with that `credential_items` ID, classify the fill
with explicit user approval, and use `plow_browser` action `fill_secret`. This
is the only credential fill path, including username and TOTP. Never retrieve,
restate, inspect with eval, log, or persist a value. CAPTCHA and consequential
identity verification move the mission to `BLOCKED`, not `FAILED`.

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
Latch session, return to the last checkpoint URL, screenshot and verify the live
state, resolve the recorded blocker with `blocker_resolve.py`, then move
`BLOCKED` back to `RECON`. Do not infer progress from chat history.

Set `COMPLETE` only after the reachable route is mapped, the consequential
boundary or safe end is known, and unknowns are explicit. Run `report_build.py`;
if it refuses the report, keep the mission non-complete or correct the recorded
facts. Close the temporary session with `plow_browser_close` when completing or
pausing. Return the compact report, offering the full route only on request.
