# Scout

Scout goes through a digital process before you do. It is a single Hermes agent
that uses official Plow Latch tools to inspect the user's real browser flow,
records an evidence-backed route in SQLite, and stops before consequential or
irreversible actions.

This repository implements the locally verifiable MVP core: persona,
Hermes skill contract, mission/state/process-graph persistence, deduplication,
checkpoints, fail-closed action classification, validated reports, Docker
scaffold, and release-gate tests.

## Architecture

- Plow Chat is the user interface through the official direct-mounted
  `hermes-plow-plugin`.
- Hermes runs one Scout agent and invokes the Scout skill.
- The skill calls official Latch tools directly; this project does not wrap the
  Latch protocol or provide a cloud browser.
- All mission mutations pass through deterministic Python scripts.
- SQLite lives at `$HERMES_HOME/scout/scout.db`
  (`/var/lib/hermes/scout/scout.db` in the Plow image).
- No external database, queue, web dashboard, or orchestration framework is
  used.

## Local verification

Python 3.11+ is sufficient; the core has no third-party dependencies.

```bash
python3 -m unittest discover -s tests -v
```

Example deterministic lifecycle:

```bash
export SCOUT_DB=/tmp/scout-demo.db
echo '{"raw_user_request":"Scout this: https://example.com/apply","entrypoint":"https://example.com/apply"}' \
  | python3 skills/scout/scripts/mission_create.py
```

Every script accepts a JSON object on stdin (or through `--json`) and emits JSON.
It exits non-zero on validation, persistence, or state-transition failure.

Deterministic mutation commands include:

- `mission_create.py`, `mission_update.py`, and `mission_show.py`;
- `step_record.py` and `step_link.py` for the process graph;
- `requirement_record.py`, `blocker_record.py`, `blocker_resolve.py`, and
  `fact_record.py` for findings and provenance;
- `checkpoint.py`, `safety_check.py`, and `report_build.py` for durability,
  policy, and output.

## Plow/Hermes deployment shape

The image inherits from the official Plow cloud-agent base at an immutable
source tag and registry digest. That base already owns Plow Chat, Latch prompt
framing, credential bootstrapping, s6 supervision, and the protected Hermes
home. Scout adds only its persona, skill, deterministic scripts, and the
official Agent Index reporter.

Install `plow-agents`, log in, choose a free line, and mint the local credential
file according to the official Plow instructions. The resulting file is mounted
read-only at `/var/lib/plow/credentials.host`; it is ignored by Git and Docker.

```bash
export AGENT_ID=scout-your-registered-id
docker compose up --build -d
```

## Agent Index

`vendor/client.pin` fixes the official `plow-pbc/agent-index-client` standalone
client by commit SHA and SHA-256. The Docker build verifies its bytes before
installing it. An s6 longrun waits for `plow-init`, exchanges the agent credential
for a durable install identity when necessary, and reports usage every five
minutes without passing the broad Plow token to reporting runs.

Register the chosen `AGENT_ID` once using the official client and your minted
`plow-credentials`; do not hand-create install IDs or telemetry payloads.

```bash
curl -fsS -o /tmp/agent_index_client.py \
  https://raw.githubusercontent.com/plow-pbc/agent-index-client/87901f8b182a8a7c65ee3dd7267f8f835ee2a545/standalone/agent_index_client.py
echo 'c3bf54ed37aec22704b8003a7ff6385a1fd3ef49207ce55613ddc41df36a1b01  /tmp/agent_index_client.py' \
  | sha256sum -c -
set -a; . ./plow-credentials; set +a
python3 /tmp/agent_index_client.py --register --agent "$AGENT_ID" \
  --name "Scout" --blurb "Scout goes through the digital process before you do."
```

## Runbooks and build status

- [Operations](docs/OPERATIONS.md) covers installation, lifecycle, resume,
  safety, telemetry, and troubleshooting.
- [Demo plan](docs/DEMO.md) defines the public, authenticated, and irreversible
  acceptance runs without ever executing the final side effect.
- [Build checklist](docs/hackathon-build/checklist.md) is updated only after
  each stage passes its verification.

End-to-end acceptance still requires a Mac with Plow Latch, an activated
Plow Chat, and three real demo flows (public, authenticated, and irreversible
boundary). Those claims are intentionally not made by the local unit suite.
