# Scout external acceptance record

This file records the evidence needed to close Scout's external release gates.
Complete it only while operating a real Plow Chat line with an approved Mac and
Plow Latch connection.

## Evidence safety

Record only non-sensitive target names, UTC timestamps, Scout mission IDs,
redacted artifact references, and concise observations. Never record a
credential value, browser session handle, vault value, private screenshot,
cookie, token, one-time code, or token-bearing callback URL.

An artifact reference may be a filename or an operator-controlled evidence ID.
Keep the underlying artifact outside Git unless it has been reviewed and is
known to contain no personal or secret information.

## Environment

- Date/time (UTC):
- Operator:
- Registered `AGENT_ID` (identifier only, no token):
- Plow Chat line:
- Mac/Latch connected: [ ]
- Non-sensitive test account prepared, if required: [ ]

## External gates

### Plow Chat startup

- Status: [ ] PASS  [ ] FAIL
- Timestamp (UTC):
- Observation:
- Redacted artifact reference:

### Mac/Latch reconnaissance

- Status: [ ] PASS  [ ] FAIL
- Mission ID:
- Target name (no private URL parameters):
- Screenshot-first page observed: [ ]
- Durable checkpoint confirmed: [ ]
- Observation:
- Redacted artifact reference:

### Agent Index ingestion

- Status: [ ] PASS  [ ] FAIL
- Local client status successful: [ ]
- Remote official view confirmed: [ ]
- Timestamp visible in remote view (UTC):
- Observation:
- Redacted artifact reference:

## Live demos

### Public multi-step demo

- Status: [ ] PASS  [ ] FAIL
- Mission ID:
- Non-sensitive target name:
- Linked multi-step route confirmed: [ ]
- Non-obvious observed finding:
- Final submission not executed: [ ]
- Redacted artifact reference:

### Authenticated portal demo

- Status: [ ] PASS  [ ] FAIL
- Mission ID:
- Non-sensitive target name:
- Authentication used copied profile or approved vault item: [ ]
- Session-loss resume returned to the durable checkpoint: [ ]
- Secret absent from chat, logs, database, and evidence: [ ]
- Consequential account/legal mutation not executed: [ ]
- Redacted artifact reference:

### Irreversible-boundary demo

- Status: [ ] PASS  [ ] FAIL
- Mission ID:
- Non-sensitive target name:
- Consequential step recorded with evidence: [ ]
- Exact proposed action denied by the safety classifier: [ ]
- Control not activated and no external commitment created: [ ]
- Redacted artifact reference:

## Release sign-off

- All six sections above are `PASS`: [ ]
- Evidence reviewed for sensitive information: [ ]
- `docs/hackathon-build/checklist.md` external gates updated: [ ]
- Reviewer:
- Review timestamp (UTC):
- Remaining limitations or failures:
