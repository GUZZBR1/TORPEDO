# Scout operations

## 1. Prerequisites

- Docker with Compose.
- A Plow agent line and the `plow-credentials` file minted by the official `plow-agents` flow.
- A Mac connected through Plow Latch for live reconnaissance.
- An Agent Index agent identifier assigned by the official client.

Never commit `plow-credentials`, `.env`, SQLite files, browser handles, vault values, or copied callback URLs containing tokens. The repository ignores the common local forms of these files.

## 2. Verify and build

```bash
python3 -m compileall -q skills/scout/scripts tests
python3 -m unittest discover -s tests -v
docker compose config --quiet
docker build --pull -t scout:local .
```

The Docker build downloads the exact Agent Index client commit in `vendor/client.pin` and refuses a checksum mismatch.

## 3. Start the agent

Place the official credential file at `./plow-credentials`, then set the registered ID and start the service:

```bash
export AGENT_ID=scout-your-registered-id
docker compose up --build -d
docker compose logs -f agent
```

The persistent `agent-home` volume owns `$HERMES_HOME`, including `scout/scout.db` and the official Agent Index installation identity. Rebuilding the image must not delete this volume.

## 4. User flow in Plow Chat

Send either:

```text
Scout this: https://target.example/process
```

or:

```text
Scout what it takes to complete <goal>.
```

Scout creates a mission before browsing, reads the current Latch browsing skill, requests the minimum origin scope, then repeats screenshot → inspect → record → link → checkpoint → classify → navigate. A normal completion report is impossible without durable evidence and a checkpoint.

## 5. Authentication and human handoff

Scout checks the copied browser profile first. If no session exists, it lists vault metadata for the current site, asks approval for the minimum item, widens the browser session for that item, and fills with `fill_secret`. The value is never returned to the model or written to SQLite.

CAPTCHA, missing login, identity verification, denied scope, and required human decisions are `BLOCKED`, not generic failures. After the owner acts, Scout resolves the stored blocker, reloads the last checkpoint, verifies the live page with a screenshot, and resumes `RECON`.

## 6. Safety boundary

Scout may inspect dangerous controls but may not activate them. Every proposed browser action goes through `safety_check.py`. Final submission, purchase, payment, subscription, cancellation, deletion, publishing, external messages, signing, contract acceptance, legal attestation, and consequential identity verification stop the route.

Do not weaken a golden safety case to make a demo pass. Change the target or stop earlier.

## 7. Agent Index checks

The s6 longrun waits for `plow-init`, uses the official client to distinguish registered, unregistered, and unreadable local state, registers only when needed, and reports every five minutes. It never implements its own install ID or telemetry payload.

After the real container is running, inspect its logs and official status:

```bash
docker compose logs agent | grep agent-index
docker compose exec agent /opt/hermes/.venv/bin/python3 \
  /opt/plow/agent-index-client.py status
```

Confirmation in the remote Agent Index is an external acceptance gate; local logs alone are not proof of ingestion.

## 8. Troubleshooting

- Browser call blocked: report Latch's own diagnosis; do not work around the approval system.
- Unknown redirect: record it, classify scope extension, request only the observed origin.
- Browser disappeared: load the active mission and last checkpoint; never reconstruct state from chat.
- 401/403/429 in `failed_requests`: record evidence/blocker and avoid aggressive retries.
- SQLite write/checkpoint failed: stop all browser actions until persistence works.
- Agent Index state unreadable: do not re-register over it; preserve the home volume and inspect the client error.
