# Scout

[View Scout on the Agent Index](https://aiworthusing.com/agent-index/scout)

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

Python 3.11+ is sufficient; the core has no third-party dependencies. Run the
full release-gate suite on Linux (or WSL on Windows), because packaging checks
validate POSIX `sh` scripts used by the container image.

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

### Install Scout

```bash
git clone https://github.com/GUZZBR1/TORPEDO.git scout
git clone https://github.com/plow-pbc/plow-agents.git plow-agents
export PATH="$PWD/plow-agents/bin:$PATH"
cd scout
plow-agents login
plow-agents lines
plow-agents mint ln_xxx  # replace ln_xxx with a free line from the previous command
docker compose up --build -d
docker compose logs -f agent
```

Wait until `plow-init` reports that the line is configured, then text that line
to use Scout. The Compose file reports usage under the public Agent Index ID
`scout`; each persistent `agent-home` volume keeps its own installation identity.

```bash
docker compose up --build -d
```

## Agent Index

`vendor/client.pin` fixes the official `plow-pbc/agent-index-client` standalone
client by commit SHA and SHA-256. The Docker build verifies its bytes before
installing it. An s6 longrun waits for `plow-init`, exchanges the agent credential
for a durable install identity when necessary, and reports usage every five
minutes without passing the broad Plow token to reporting runs.

Scout is registered under the public ID `scout`. Regular installers do not
register a new agent ID: the supervised reporter registers their persistent
installation under `scout` on first start. Do not hand-create install IDs or
telemetry payloads. Maintainers can verify the exact pinned client independently:

```bash
curl -fsS -o /tmp/agent_index_client.py \
  https://raw.githubusercontent.com/plow-pbc/agent-index-client/f900ff144076f0a766584b6ec4d0993600779b16/standalone/agent_index_client.py
echo '633ad3bc24a51d6b7dcfaae319983ab174d9853a525237d99cac64878452560c  /tmp/agent_index_client.py' \
  | sha256sum -c -
python3 /tmp/agent_index_client.py --self-check
```

## Runbooks and build status

- [Operations](docs/OPERATIONS.md) covers installation, lifecycle, resume,
  safety, telemetry, and troubleshooting.
- [Demo plan](docs/DEMO.md) defines the public, authenticated, and irreversible
  acceptance runs without ever executing the final side effect.
- [Acceptance record](docs/ACCEPTANCE_RECORD.md) is the operator-safe template
  for recording those live runs without storing credentials or private data.
- [Build checklist](docs/hackathon-build/checklist.md) is updated only after
  each stage passes its verification.

End-to-end acceptance still requires a Mac with Plow Latch, an activated
Plow Chat, and three real demo flows (public, authenticated, and irreversible
boundary). Those claims are intentionally not made by the local unit suite.

Scout is released under the [MIT License](LICENSE), as required for Agent Index
hackathon ranking.
