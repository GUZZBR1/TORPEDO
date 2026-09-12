#!/usr/bin/env python3
"""Deterministic SQLite persistence for Scout missions.

The module intentionally uses only Python's standard library so it can run in
the Hermes base image without adding runtime dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


PHASES = {"CREATED", "RECON", "BLOCKED", "COMPLETE", "FAILED", "CANCELLED"}
TRANSITIONS = {
    "CREATED": {"RECON", "FAILED", "CANCELLED"},
    "RECON": {"BLOCKED", "COMPLETE", "FAILED", "CANCELLED"},
    "BLOCKED": {"RECON", "FAILED", "CANCELLED"},
    "COMPLETE": set(),
    "FAILED": set(),
    "CANCELLED": set(),
}
STEP_KINDS = {
    "PAGE", "AUTH", "FORM", "UPLOAD", "PAYMENT", "REVIEW",
    "VERIFICATION", "REDIRECT", "SUBMIT", "OTHER",
}
STEP_STATUSES = {"OBSERVED", "PARTIAL", "BLOCKED", "UNREACHABLE"}
SIDE_EFFECT_RISKS = {"NONE", "LOW", "CONSEQUENTIAL"}
REQUIREMENT_CATEGORIES = {
    "ACCOUNT", "IDENTITY", "DOCUMENT", "FILE", "VIDEO", "PAYMENT",
    "DATA", "APPROVAL", "OTHER",
}
REQUIREMENT_STATUSES = {"OBSERVED_REQUIRED", "INFERRED", "UNKNOWN"}
BLOCKER_TYPES = {
    "LOGIN", "CAPTCHA", "IDENTITY_VERIFICATION", "MISSING_DOCUMENT",
    "HUMAN_DECISION", "PAYMENT", "ACCESS_DENIED", "RATE_LIMIT",
    "SITE_FAILURE", "OTHER",
}
EVIDENCE_KINDS = {
    "SCREENSHOT", "PAGE_TEXT", "FORM_SCHEMA", "TABLE", "URL", "OBSERVATION",
}
SECRET_FIELD_NAMES = {
    "password", "passwd", "passphrase", "secret", "token", "access_token",
    "refresh_token", "api_key", "card_number", "cvv", "cvc", "totp",
    "one_time_password", "private_key",
}
SENSITIVE_URL_KEYS = SECRET_FIELD_NAMES | {
    "authorization", "auth", "code", "credential", "session", "session_id", "sid",
}


SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    raw_user_request TEXT NOT NULL,
    entrypoint TEXT,
    target_name TEXT,
    mode TEXT NOT NULL CHECK (mode = 'scout'),
    phase TEXT NOT NULL CHECK (phase IN ('CREATED','RECON','BLOCKED','COMPLETE','FAILED','CANCELLED')),
    last_checkpoint_at TEXT,
    last_completed_step_id TEXT,
    current_url TEXT,
    allow_authentication INTEGER NOT NULL DEFAULT 1,
    allow_navigation INTEGER NOT NULL DEFAULT 1,
    allow_file_lookup INTEGER NOT NULL DEFAULT 0,
    allow_form_draft INTEGER NOT NULL DEFAULT 0,
    forbid_final_submit INTEGER NOT NULL DEFAULT 1,
    forbid_purchase INTEGER NOT NULL DEFAULT 1,
    forbid_payment INTEGER NOT NULL DEFAULT 1,
    forbid_message_send INTEGER NOT NULL DEFAULT 1,
    forbid_delete INTEGER NOT NULL DEFAULT 1,
    forbid_cancel INTEGER NOT NULL DEFAULT 1,
    forbid_contract_acceptance INTEGER NOT NULL DEFAULT 1,
    total_steps INTEGER NOT NULL DEFAULT 0,
    requirements_count INTEGER NOT NULL DEFAULT 0,
    blockers_count INTEGER NOT NULL DEFAULT 0,
    external_domains INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    FOREIGN KEY (last_completed_step_id) REFERENCES steps(id)
);

CREATE TABLE IF NOT EXISTS steps (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    domain TEXT,
    status TEXT NOT NULL,
    sequence_hint INTEGER NOT NULL,
    reversible INTEGER NOT NULL,
    side_effect_risk TEXT NOT NULL,
    next_step_ids_json TEXT NOT NULL DEFAULT '[]',
    dedupe_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (mission_id, dedupe_key)
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    step_id TEXT REFERENCES steps(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    source_url TEXT,
    captured_at TEXT NOT NULL,
    summary TEXT NOT NULL,
    artifact_path TEXT,
    dedupe_key TEXT NOT NULL,
    UNIQUE (mission_id, dedupe_key)
);

CREATE TABLE IF NOT EXISTS requirements (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    step_id TEXT REFERENCES steps(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL,
    details TEXT,
    evidence_id TEXT REFERENCES evidence(id) ON DELETE SET NULL,
    dedupe_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (mission_id, dedupe_key)
);

CREATE TABLE IF NOT EXISTS blockers (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    step_id TEXT REFERENCES steps(id) ON DELETE SET NULL,
    type TEXT NOT NULL,
    description TEXT NOT NULL,
    recoverable INTEGER NOT NULL,
    owner_action TEXT,
    dedupe_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (mission_id, dedupe_key)
);

CREATE TABLE IF NOT EXISTS mission_events (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    timestamp TEXT NOT NULL,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_steps_mission_sequence
    ON steps(mission_id, sequence_hint, created_at);
CREATE INDEX IF NOT EXISTS idx_evidence_mission_step ON evidence(mission_id, step_id);
CREATE INDEX IF NOT EXISTS idx_events_mission_time ON mission_events(mission_id, timestamp);
"""


class ScoutError(ValueError):
    """A deterministic input, policy, or state validation failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    # Lexicographically sortable timestamp plus 80 bits of randomness, ULID-shaped.
    millis = int(time.time() * 1000)
    return f"{prefix}_{millis:012x}{secrets.token_hex(10)}"


def database_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    if os.environ.get("SCOUT_DB"):
        return Path(os.environ["SCOUT_DB"]).expanduser()
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    return hermes_home / "scout" / "scout.db"


def _connect(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    resolved = database_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


@contextmanager
def transaction(path: str | os.PathLike[str] | None = None) -> Iterator[sqlite3.Connection]:
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    with transaction(path):
        pass
    return {"ok": True, "database": str(database_path(path))}


def normalize(value: str | None) -> str:
    return " ".join((value or "").casefold().strip().split())


def _require_choice(name: str, value: str, choices: set[str]) -> str:
    normalized = str(value).upper()
    if normalized not in choices:
        raise ScoutError(f"{name} must be one of: {', '.join(sorted(choices))}")
    return normalized


def _require_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScoutError(f"{name} must be a non-empty string")
    return value.strip()


def _validate_url(value: str | None, name: str = "url") -> str | None:
    if value is None:
        return None
    value = _require_text(name, value)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ScoutError(f"{name} must be an http(s) URL")
    # Keep route context while ensuring copied callback/session URLs cannot put
    # credentials into durable mission state.
    query = []
    for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
        normalized_key = normalize(key).replace("-", "_").replace(" ", "_")
        query.append((key, "[REDACTED]" if normalized_key in SENSITIVE_URL_KEYS else item_value))
    fragment = parsed.fragment
    if any(f"{key}=" in fragment.casefold() for key in SENSITIVE_URL_KEYS):
        fragment = "[REDACTED]"
    return urlunparse(parsed._replace(query=urlencode(query), fragment=fragment))


def _validate_no_secret_fields(value: Any, path: str = "input") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized_key = normalize(str(key)).replace("-", "_").replace(" ", "_")
            if normalized_key in SECRET_FIELD_NAMES:
                raise ScoutError(f"secret-bearing field is forbidden: {path}.{key}")
            _validate_no_secret_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_no_secret_fields(child, f"{path}[{index}]")


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _mission(conn: sqlite3.Connection, mission_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM missions WHERE id = ?", (mission_id,)).fetchone()
    if row is None:
        raise ScoutError(f"mission not found: {mission_id}")
    return row


def _event(conn: sqlite3.Connection, mission_id: str, event_type: str, payload: Mapping[str, Any]) -> str:
    event_id = new_id("evt")
    conn.execute(
        "INSERT INTO mission_events(id, mission_id, timestamp, type, payload_json) VALUES(?,?,?,?,?)",
        (event_id, mission_id, utc_now(), event_type, json.dumps(payload, sort_keys=True, separators=(",", ":"))),
    )
    return event_id


def _refresh_summary(conn: sqlite3.Connection, mission_id: str) -> None:
    mission = _mission(conn, mission_id)
    entry_domain = urlparse(mission["entrypoint"]).netloc.casefold() if mission["entrypoint"] else None
    domains = {
        row[0].casefold()
        for row in conn.execute("SELECT DISTINCT domain FROM steps WHERE mission_id = ? AND domain IS NOT NULL", (mission_id,))
        if row[0]
    }
    external_domains = len(domains - ({entry_domain} if entry_domain else set()))
    counts = {
        "total_steps": conn.execute("SELECT COUNT(*) FROM steps WHERE mission_id = ?", (mission_id,)).fetchone()[0],
        "requirements_count": conn.execute("SELECT COUNT(*) FROM requirements WHERE mission_id = ?", (mission_id,)).fetchone()[0],
        "blockers_count": conn.execute("SELECT COUNT(*) FROM blockers WHERE mission_id = ?", (mission_id,)).fetchone()[0],
        "external_domains": external_domains,
    }
    conn.execute(
        """UPDATE missions SET total_steps=?, requirements_count=?, blockers_count=?,
           external_domains=?, updated_at=? WHERE id=?""",
        (*counts.values(), utc_now(), mission_id),
    )


def create_mission(data: Mapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    _validate_no_secret_fields(data)
    raw_request = _require_text("raw_user_request", data.get("raw_user_request"))
    entrypoint = _validate_url(data.get("entrypoint"), "entrypoint")
    target_name = data.get("target_name")
    if target_name is not None:
        target_name = _require_text("target_name", target_name)
    mission_id = new_id("sc")
    now = utc_now()
    with transaction(path) as conn:
        conn.execute(
            """INSERT INTO missions(
                id, created_at, updated_at, raw_user_request, entrypoint, target_name,
                mode, phase, allow_authentication, allow_navigation, allow_file_lookup,
                allow_form_draft
            ) VALUES(?,?,?,?,?,?,'scout','CREATED',?,?,?,?)""",
            (
                mission_id, now, now, raw_request, entrypoint, target_name,
                int(bool(data.get("allow_authentication", True))),
                int(bool(data.get("allow_navigation", True))),
                int(bool(data.get("allow_file_lookup", False))),
                int(bool(data.get("allow_form_draft", False))),
            ),
        )
        _event(conn, mission_id, "MISSION_CREATED", {"entrypoint": entrypoint, "target_name": target_name})
        result = _row(_mission(conn, mission_id))
    return {"ok": True, "mission": result}


def update_mission(data: Mapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    _validate_no_secret_fields(data)
    mission_id = _require_text("mission_id", data.get("mission_id"))
    requested_phase = data.get("phase")
    with transaction(path) as conn:
        current = _mission(conn, mission_id)
        updates: dict[str, Any] = {}
        event_type = None
        if requested_phase is not None:
            next_phase = _require_choice("phase", requested_phase, PHASES)
            current_phase = current["phase"]
            if next_phase != current_phase and next_phase not in TRANSITIONS[current_phase]:
                raise ScoutError(f"invalid phase transition: {current_phase} -> {next_phase}")
            updates["phase"] = next_phase
            event_type = {
                "RECON": "MISSION_RESUMED" if current_phase == "BLOCKED" else "MISSION_STARTED",
                "BLOCKED": "MISSION_BLOCKED",
                "COMPLETE": "MISSION_COMPLETED",
                "FAILED": "MISSION_FAILED",
                "CANCELLED": "MISSION_CANCELLED",
            }.get(next_phase)
        for field in ("target_name", "current_url", "error_code", "error_message"):
            if field in data:
                value = data[field]
                if field == "current_url":
                    value = _validate_url(value, field)
                elif value is not None and not isinstance(value, str):
                    raise ScoutError(f"{field} must be a string or null")
                updates[field] = value
        if not updates:
            raise ScoutError("no mission fields supplied to update")
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{name} = ?" for name in updates)
        conn.execute(f"UPDATE missions SET {assignments} WHERE id = ?", (*updates.values(), mission_id))
        if event_type:
            _event(conn, mission_id, event_type, {"from": current["phase"], "to": updates["phase"]})
        result = _row(_mission(conn, mission_id))
    return {"ok": True, "mission": result}


def _fingerprint(*values: Any) -> str:
    canonical = "\x1f".join(normalize(str(value)) for value in values)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_evidence(
    conn: sqlite3.Connection,
    mission_id: str,
    step_id: str | None,
    data: Mapping[str, Any],
) -> tuple[str, bool]:
    _validate_no_secret_fields(data)
    kind = _require_choice("evidence.kind", data.get("kind"), EVIDENCE_KINDS)
    summary = _require_text("evidence.summary", data.get("summary"))
    source_url = _validate_url(data.get("source_url"), "evidence.source_url")
    artifact_path = data.get("artifact_path")
    if artifact_path is not None and not isinstance(artifact_path, str):
        raise ScoutError("evidence.artifact_path must be a string or null")
    dedupe_key = _fingerprint(step_id, kind, source_url, summary, artifact_path)
    existing = conn.execute(
        "SELECT id FROM evidence WHERE mission_id = ? AND dedupe_key = ?", (mission_id, dedupe_key)
    ).fetchone()
    if existing:
        return existing["id"], False
    evidence_id = new_id("ev")
    conn.execute(
        """INSERT INTO evidence(id,mission_id,step_id,kind,source_url,captured_at,summary,artifact_path,dedupe_key)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (evidence_id, mission_id, step_id, kind, source_url, data.get("captured_at") or utc_now(), summary, artifact_path, dedupe_key),
    )
    return evidence_id, True


def record_step(data: Mapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    _validate_no_secret_fields(data)
    mission_id = _require_text("mission_id", data.get("mission_id"))
    kind = _require_choice("kind", data.get("kind"), STEP_KINDS)
    title = _require_text("title", data.get("title"))
    url = _validate_url(data.get("url"))
    domain = urlparse(url).netloc.casefold() if url else data.get("domain")
    if domain is not None:
        domain = _require_text("domain", domain).casefold()
    status = _require_choice("status", data.get("status", "OBSERVED"), STEP_STATUSES)
    risk = _require_choice("side_effect_risk", data.get("side_effect_risk", "NONE"), SIDE_EFFECT_RISKS)
    sequence_hint = data.get("sequence_hint")
    if not isinstance(sequence_hint, int) or sequence_hint < 0:
        raise ScoutError("sequence_hint must be a non-negative integer")
    reversible = data.get("reversible", True)
    if not isinstance(reversible, bool):
        raise ScoutError("reversible must be a boolean")
    next_steps = data.get("next_step_ids", [])
    if not isinstance(next_steps, list) or not all(isinstance(item, str) for item in next_steps):
        raise ScoutError("next_step_ids must be a list of strings")
    evidence_inputs = data.get("evidence", [])
    if not isinstance(evidence_inputs, list):
        raise ScoutError("evidence must be a list")
    dedupe_key = data.get("dedupe_key") or _fingerprint(kind, title, url, sequence_hint)
    with transaction(path) as conn:
        mission = _mission(conn, mission_id)
        if mission["phase"] not in {"RECON", "BLOCKED"}:
            raise ScoutError(f"steps cannot be recorded while mission is {mission['phase']}")
        existing = conn.execute(
            "SELECT * FROM steps WHERE mission_id=? AND dedupe_key=?", (mission_id, dedupe_key)
        ).fetchone()
        created = existing is None
        if created:
            step_id = new_id("step")
            conn.execute(
                """INSERT INTO steps(id,mission_id,kind,title,url,domain,status,sequence_hint,reversible,
                   side_effect_risk,next_step_ids_json,dedupe_key,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (step_id, mission_id, kind, title, url, domain, status, sequence_hint, int(reversible), risk,
                 json.dumps(next_steps, separators=(",", ":")), dedupe_key, utc_now()),
            )
        else:
            step_id = existing["id"]
        evidence_ids: list[str] = []
        evidence_created = 0
        for evidence in evidence_inputs:
            if not isinstance(evidence, Mapping):
                raise ScoutError("each evidence item must be an object")
            evidence_id, was_created = record_evidence(conn, mission_id, step_id, evidence)
            evidence_ids.append(evidence_id)
            evidence_created += int(was_created)
        if created:
            _event(conn, mission_id, "STEP_OBSERVED", {"step_id": step_id, "evidence_ids": evidence_ids})
        _refresh_summary(conn, mission_id)
        step = _row(conn.execute("SELECT * FROM steps WHERE id=?", (step_id,)).fetchone())
    return {"ok": True, "created": created, "evidence_created": evidence_created, "step": step, "evidence_ids": evidence_ids}


def record_requirement(data: Mapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    _validate_no_secret_fields(data)
    mission_id = _require_text("mission_id", data.get("mission_id"))
    name = _require_text("name", data.get("name"))
    category = _require_choice("category", data.get("category"), REQUIREMENT_CATEGORIES)
    status = _require_choice("status", data.get("status"), REQUIREMENT_STATUSES)
    step_id = data.get("step_id")
    details = data.get("details")
    evidence_id = data.get("evidence_id")
    dedupe_key = _fingerprint(mission_id, category, name, step_id)
    with transaction(path) as conn:
        _mission(conn, mission_id)
        existing = conn.execute(
            "SELECT * FROM requirements WHERE mission_id=? AND dedupe_key=?", (mission_id, dedupe_key)
        ).fetchone()
        created = existing is None
        if created:
            requirement_id = new_id("req")
            conn.execute(
                """INSERT INTO requirements(id,mission_id,step_id,name,category,status,details,evidence_id,dedupe_key,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (requirement_id, mission_id, step_id, name, category, status, details, evidence_id, dedupe_key, utc_now()),
            )
            _event(conn, mission_id, "REQUIREMENT_FOUND", {"requirement_id": requirement_id})
        else:
            requirement_id = existing["id"]
        _refresh_summary(conn, mission_id)
        result = _row(conn.execute("SELECT * FROM requirements WHERE id=?", (requirement_id,)).fetchone())
    return {"ok": True, "created": created, "requirement": result}


def record_blocker(data: Mapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    _validate_no_secret_fields(data)
    mission_id = _require_text("mission_id", data.get("mission_id"))
    blocker_type = _require_choice("type", data.get("type"), BLOCKER_TYPES)
    description = _require_text("description", data.get("description"))
    step_id = data.get("step_id")
    recoverable = data.get("recoverable")
    if not isinstance(recoverable, bool):
        raise ScoutError("recoverable must be a boolean")
    owner_action = data.get("owner_action")
    dedupe_key = _fingerprint(mission_id, blocker_type, description, step_id)
    with transaction(path) as conn:
        _mission(conn, mission_id)
        existing = conn.execute(
            "SELECT * FROM blockers WHERE mission_id=? AND dedupe_key=?", (mission_id, dedupe_key)
        ).fetchone()
        created = existing is None
        if created:
            blocker_id = new_id("blk")
            conn.execute(
                """INSERT INTO blockers(id,mission_id,step_id,type,description,recoverable,owner_action,dedupe_key,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (blocker_id, mission_id, step_id, blocker_type, description, int(recoverable), owner_action, dedupe_key, utc_now()),
            )
            _event(conn, mission_id, "BLOCKER_FOUND", {"blocker_id": blocker_id})
        else:
            blocker_id = existing["id"]
        _refresh_summary(conn, mission_id)
        result = _row(conn.execute("SELECT * FROM blockers WHERE id=?", (blocker_id,)).fetchone())
    return {"ok": True, "created": created, "blocker": result}


def checkpoint(data: Mapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    _validate_no_secret_fields(data)
    mission_id = _require_text("mission_id", data.get("mission_id"))
    step_id = _require_text("last_completed_step_id", data.get("last_completed_step_id"))
    current_url = _validate_url(data.get("current_url"), "current_url")
    with transaction(path) as conn:
        mission = _mission(conn, mission_id)
        if mission["phase"] not in {"RECON", "BLOCKED"}:
            raise ScoutError(f"cannot checkpoint mission in {mission['phase']}")
        step = conn.execute("SELECT id FROM steps WHERE id=? AND mission_id=?", (step_id, mission_id)).fetchone()
        if step is None:
            raise ScoutError("checkpoint step does not belong to mission")
        now = utc_now()
        conn.execute(
            """UPDATE missions SET last_checkpoint_at=?, last_completed_step_id=?, current_url=?, updated_at=?
               WHERE id=?""",
            (now, step_id, current_url, now, mission_id),
        )
        _event(conn, mission_id, "CHECKPOINT", {"step_id": step_id, "current_url": current_url})
        result = _row(_mission(conn, mission_id))
    return {"ok": True, "mission": result}


def show_mission(data: Mapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    mission_id = _require_text("mission_id", data.get("mission_id"))
    with transaction(path) as conn:
        _refresh_summary(conn, mission_id)
        mission = _row(_mission(conn, mission_id))
        steps = [dict(row) for row in conn.execute("SELECT * FROM steps WHERE mission_id=? ORDER BY sequence_hint,created_at", (mission_id,))]
        evidence = [dict(row) for row in conn.execute("SELECT * FROM evidence WHERE mission_id=? ORDER BY captured_at", (mission_id,))]
        requirements = [dict(row) for row in conn.execute("SELECT * FROM requirements WHERE mission_id=? ORDER BY created_at", (mission_id,))]
        blockers = [dict(row) for row in conn.execute("SELECT * FROM blockers WHERE mission_id=? ORDER BY created_at", (mission_id,))]
        events = [dict(row) for row in conn.execute("SELECT * FROM mission_events WHERE mission_id=? ORDER BY timestamp", (mission_id,))]
    return {"ok": True, "mission": mission, "steps": steps, "evidence": evidence, "requirements": requirements, "blockers": blockers, "events": events}


def latest_active_mission(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    with transaction(path) as conn:
        row = conn.execute(
            "SELECT id FROM missions WHERE phase IN ('CREATED','RECON','BLOCKED') ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise ScoutError("no active mission found")
    return show_mission({"mission_id": row["id"]}, path)


def read_json_input(argv: Sequence[str] | None = None) -> tuple[dict[str, Any], str | None]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="json_value", help="JSON object; defaults to stdin")
    parser.add_argument("--db", help="override database path")
    args = parser.parse_args(argv)
    raw = args.json_value if args.json_value is not None else sys.stdin.read()
    if not raw.strip():
        raise ScoutError("expected a JSON object on stdin or --json")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ScoutError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ScoutError("input must be a JSON object")
    return value, args.db


def cli(handler: Callable[[Mapping[str, Any], str | None], Mapping[str, Any]]) -> None:
    try:
        data, path = read_json_input()
        result = handler(data, path)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    except (ScoutError, sqlite3.Error, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True, separators=(",", ":")))
        raise SystemExit(2) from exc


if __name__ == "__main__":
    try:
        _, db_override = read_json_input()
        print(json.dumps(init_db(db_override), sort_keys=True, separators=(",", ":")))
    except (ScoutError, sqlite3.Error, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True, separators=(",", ":")))
        raise SystemExit(2) from exc
