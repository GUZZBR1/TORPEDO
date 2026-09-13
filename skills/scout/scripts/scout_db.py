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
import re
import secrets
import sqlite3
import sys
import time
from contextlib import closing, contextmanager
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
FACT_TYPES = {"COST", "DEADLINE", "OTHER"}
FACT_STATUSES = {"OBSERVED", "INFERRED", "UNKNOWN"}
SECRET_FIELD_NAMES = {
    "password", "passwd", "passphrase", "secret", "token", "access_token",
    "refresh_token", "api_key", "card_number", "cvv", "cvc", "totp",
    "one_time_password", "otp", "pin", "security_code", "private_key",
}
SENSITIVE_URL_KEYS = SECRET_FIELD_NAMES | {
    "authorization", "auth", "code", "credential", "session", "session_id", "sid",
    "key", "sig", "signature", "jwt", "id_token", "state",
}

SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|passphrase|secret|token|access[_ -]?token|refresh[_ -]?token|"
    r"api[_ -]?key|authorization|bearer|otp|pin|cvv|cvc)\b(\s*(?:is|[:=])\s*)([^\n,;]+)"
)
URL_USERINFO_RE = re.compile(r"(?i)(https?://)([^/\s@]+)@")
URL_SECRET_PARAM_RE = re.compile(
    r"(?i)([?&#](?:password|passwd|passphrase|secret|token|access_token|refresh_token|"
    r"api_key|authorization|auth|code|credential|session|session_id|sid|key|sig|signature|"
    r"jwt|id_token|state)=)([^&#\s]+)"
)
BEARER_TOKEN_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----.*?-----END \1-----", re.DOTALL
)
PRIVATE_KEY_HEADER_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")


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
    safe_end_confirmed INTEGER NOT NULL DEFAULT 0,
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
    resolved_at TEXT,
    dedupe_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (mission_id, dedupe_key)
);

CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    step_id TEXT REFERENCES steps(id) ON DELETE SET NULL,
    type TEXT NOT NULL CHECK (type IN ('COST','DEADLINE','OTHER')),
    name TEXT NOT NULL,
    value TEXT,
    status TEXT NOT NULL CHECK (status IN ('OBSERVED','INFERRED','UNKNOWN')),
    details TEXT,
    evidence_id TEXT REFERENCES evidence(id) ON DELETE SET NULL,
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
CREATE INDEX IF NOT EXISTS idx_facts_mission_step ON facts(mission_id, step_id);
CREATE INDEX IF NOT EXISTS idx_events_mission_time ON mission_events(mission_id, timestamp);
"""


class ScoutError(ValueError):
    """A deterministic input, policy, or state validation failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    # ULID: 48-bit millisecond timestamp + 80 random bits, Crockford base32.
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    encoded = ""
    for _ in range(26):
        encoded = alphabet[value & 31] + encoded
        value >>= 5
    return f"{prefix}_{encoded}"


def database_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    if os.environ.get("SCOUT_DB"):
        return Path(os.environ["SCOUT_DB"]).expanduser()
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    return hermes_home / "scout" / "scout.db"


def _connect(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    resolved = database_path(path)
    parent_existed = resolved.parent.exists()
    resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not parent_existed or resolved.parent.name == "scout":
        os.chmod(resolved.parent, 0o700)
    conn = sqlite3.connect(resolved, timeout=10)
    os.chmod(resolved, 0o600)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    for sidecar in (Path(f"{resolved}-wal"), Path(f"{resolved}-shm")):
        if sidecar.exists():
            os.chmod(sidecar, 0o600)
    conn.execute("PRAGMA busy_timeout = 10000")
    # sqlite3.executescript() commits an open transaction. Initialize/migrate
    # the schema before BEGIN so every handler body remains one atomic unit.
    conn.executescript(SCHEMA)
    blocker_columns = {row[1] for row in conn.execute("PRAGMA table_info(blockers)")}
    if "resolved_at" not in blocker_columns:
        conn.execute("ALTER TABLE blockers ADD COLUMN resolved_at TEXT")
    mission_columns = {row[1] for row in conn.execute("PRAGMA table_info(missions)")}
    if "safe_end_confirmed" not in mission_columns:
        conn.execute(
            "ALTER TABLE missions ADD COLUMN safe_end_confirmed INTEGER NOT NULL DEFAULT 0"
        )
    conn.commit()
    return conn


@contextmanager
def transaction(path: str | os.PathLike[str] | None = None) -> Iterator[sqlite3.Connection]:
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
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


def _require_verbatim_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScoutError(f"{name} must be a non-empty string")
    return value


def _optional_text(name: str, value: Any) -> str | None:
    if value is None:
        return None
    return _require_text(name, value)


def _require_bool(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ScoutError(f"{name} must be a boolean")
    return value


def _assert_fields(data: Mapping[str, Any], allowed: set[str], context: str = "input") -> None:
    unknown = sorted(str(key) for key in data if key not in allowed)
    if unknown:
        raise ScoutError(f"unknown {context} field(s): {', '.join(unknown)}")


def _validate_url(value: str | None, name: str = "url") -> str | None:
    if value is None:
        return None
    value = _require_text(name, value)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ScoutError(f"{name} must be an http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ScoutError(f"{name} must not contain URL userinfo credentials")
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


def _redact_sensitive_text(value: str) -> str:
    value = PRIVATE_KEY_BLOCK_RE.sub("[REDACTED PRIVATE KEY]", value)
    if PRIVATE_KEY_HEADER_RE.search(value):
        raise ScoutError("raw_user_request contains an incomplete private key")
    value = BEARER_TOKEN_RE.sub("Bearer [REDACTED]", value)
    value = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value)
    value = URL_SECRET_PARAM_RE.sub(r"\1[REDACTED]", value)
    value = URL_USERINFO_RE.sub(r"\1[REDACTED]@", value)
    return value


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
    elif isinstance(value, str):
        if (
            SECRET_ASSIGNMENT_RE.search(value)
            or URL_USERINFO_RE.search(value)
            or BEARER_TOKEN_RE.search(value)
            or PRIVATE_KEY_HEADER_RE.search(value)
        ):
            raise ScoutError(f"secret-bearing value is forbidden: {path}")


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _mission(conn: sqlite3.Connection, mission_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM missions WHERE id = ?", (mission_id,)).fetchone()
    if row is None:
        raise ScoutError(f"mission not found: {mission_id}")
    return row


def _owned_step(conn: sqlite3.Connection, mission_id: str, step_id: str | None) -> sqlite3.Row | None:
    if step_id is None:
        return None
    step_id = _require_text("step_id", step_id)
    row = conn.execute(
        "SELECT * FROM steps WHERE id = ? AND mission_id = ?", (step_id, mission_id)
    ).fetchone()
    if row is None:
        raise ScoutError("step_id does not belong to mission")
    return row


def _owned_evidence(
    conn: sqlite3.Connection, mission_id: str, evidence_id: str | None
) -> sqlite3.Row | None:
    if evidence_id is None:
        return None
    evidence_id = _require_text("evidence_id", evidence_id)
    row = conn.execute(
        "SELECT * FROM evidence WHERE id = ? AND mission_id = ?", (evidence_id, mission_id)
    ).fetchone()
    if row is None:
        raise ScoutError("evidence_id does not belong to mission")
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
    _assert_fields(data, {
        "raw_user_request", "entrypoint", "target_name", "allow_authentication",
        "allow_navigation", "allow_file_lookup", "allow_form_draft",
    })
    raw_request = _redact_sensitive_text(
        _require_verbatim_text("raw_user_request", data.get("raw_user_request"))
    )
    entrypoint = _validate_url(data.get("entrypoint"), "entrypoint")
    sanitized_input = dict(data)
    sanitized_input.pop("raw_user_request", None)
    sanitized_input.pop("entrypoint", None)
    _validate_no_secret_fields(sanitized_input)
    target_name = _optional_text("target_name", data.get("target_name"))
    policies = {
        name: _require_bool(name, data.get(name, default))
        for name, default in (
            ("allow_authentication", True), ("allow_navigation", True),
            ("allow_file_lookup", False), ("allow_form_draft", False),
        )
    }
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
                int(policies["allow_authentication"]), int(policies["allow_navigation"]),
                int(policies["allow_file_lookup"]), int(policies["allow_form_draft"]),
            ),
        )
        _event(conn, mission_id, "MISSION_CREATED", {"entrypoint": entrypoint, "target_name": target_name})
        result = _row(_mission(conn, mission_id))
    return {"ok": True, "mission": result}


def update_mission(data: Mapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    _assert_fields(data, {
        "mission_id", "phase", "target_name", "current_url", "error_code", "error_message",
        "safe_end_confirmed",
    })
    _validate_no_secret_fields(data)
    mission_id = _require_text("mission_id", data.get("mission_id"))
    requested_phase = data.get("phase")
    safe_end_confirmed = data.get("safe_end_confirmed", False)
    _require_bool("safe_end_confirmed", safe_end_confirmed)
    if "safe_end_confirmed" in data and requested_phase != "COMPLETE":
        raise ScoutError("safe_end_confirmed is valid only when requesting COMPLETE")
    with transaction(path) as conn:
        current = _mission(conn, mission_id)
        updates: dict[str, Any] = {}
        event_type = None
        if requested_phase is not None:
            next_phase = _require_choice("phase", requested_phase, PHASES)
            current_phase = current["phase"]
            if next_phase != current_phase and next_phase not in TRANSITIONS[current_phase]:
                raise ScoutError(f"invalid phase transition: {current_phase} -> {next_phase}")
            if next_phase == "BLOCKED" and next_phase != current_phase:
                open_blockers = conn.execute(
                    "SELECT COUNT(*) FROM blockers WHERE mission_id=? AND resolved_at IS NULL",
                    (mission_id,),
                ).fetchone()[0]
                if not open_blockers:
                    raise ScoutError("BLOCKED requires an unresolved blocker")
            if current_phase == "BLOCKED" and next_phase == "RECON":
                if not current["last_checkpoint_at"] and current["total_steps"]:
                    raise ScoutError("resuming from BLOCKED requires a durable checkpoint")
                open_blockers = conn.execute(
                    "SELECT COUNT(*) FROM blockers WHERE mission_id=? AND resolved_at IS NULL",
                    (mission_id,),
                ).fetchone()[0]
                if open_blockers:
                    raise ScoutError("resuming from BLOCKED requires blockers to be resolved")
            if next_phase == "COMPLETE" and next_phase != current_phase:
                _validate_completion(conn, current, safe_end_confirmed)
                updates["safe_end_confirmed"] = int(safe_end_confirmed)
            if next_phase == "FAILED" and next_phase != current_phase:
                error_code = data.get("error_code") or current["error_code"]
                error_message = data.get("error_message") or current["error_message"]
                if not error_code or not error_message:
                    raise ScoutError("FAILED requires error_code and error_message")
            if next_phase != current_phase:
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
                else:
                    value = _optional_text(field, value)
                updates[field] = value
        if not updates:
            raise ScoutError("no mission fields supplied to update")
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{name} = ?" for name in updates)
        conn.execute(f"UPDATE missions SET {assignments} WHERE id = ?", (*updates.values(), mission_id))
        if event_type:
            payload = {"from": current["phase"], "to": updates["phase"]}
            if updates["phase"] == "COMPLETE":
                payload["safe_end_confirmed"] = safe_end_confirmed
            _event(conn, mission_id, event_type, payload)
        result = _row(_mission(conn, mission_id))
    return {"ok": True, "mission": result}


def _validate_completion(
    conn: sqlite3.Connection, mission: sqlite3.Row, safe_end_confirmed: bool
) -> None:
    mission_id = mission["id"]
    if not mission["last_checkpoint_at"] or not mission["last_completed_step_id"]:
        raise ScoutError("COMPLETE requires a durable checkpoint")
    observed_with_screenshot = conn.execute(
        """SELECT COUNT(*) FROM steps s
           WHERE s.mission_id=? AND s.status='OBSERVED'
             AND EXISTS (SELECT 1 FROM evidence e
                         WHERE e.step_id=s.id AND e.mission_id=s.mission_id
                           AND e.kind='SCREENSHOT')""",
        (mission_id,),
    ).fetchone()[0]
    observed_steps = conn.execute(
        "SELECT COUNT(*) FROM steps WHERE mission_id=? AND status='OBSERVED'", (mission_id,)
    ).fetchone()[0]
    if not observed_with_screenshot:
        raise ScoutError("COMPLETE requires an observed step with screenshot evidence")
    if observed_with_screenshot != observed_steps:
        raise ScoutError("COMPLETE requires screenshot evidence for every observed step")
    unresolved = conn.execute(
        "SELECT COUNT(*) FROM blockers WHERE mission_id=? AND resolved_at IS NULL", (mission_id,)
    ).fetchone()[0]
    if unresolved:
        raise ScoutError("COMPLETE cannot contain unresolved blockers")
    boundary = conn.execute(
        """SELECT COUNT(*) FROM steps s
           WHERE s.mission_id=? AND s.status='OBSERVED'
             AND s.side_effect_risk='CONSEQUENTIAL' AND s.reversible=0
             AND EXISTS (SELECT 1 FROM evidence e
                         WHERE e.step_id=s.id AND e.mission_id=s.mission_id
                           AND e.kind='SCREENSHOT')""",
        (mission_id,),
    ).fetchone()[0]
    if not boundary and not safe_end_confirmed:
        raise ScoutError("COMPLETE requires a consequential boundary or safe_end_confirmed=true")
    requirement_findings = conn.execute(
        "SELECT status FROM requirements WHERE mission_id=?", (mission_id,)
    ).fetchall()
    fact_findings = conn.execute(
        "SELECT status FROM facts WHERE mission_id=?", (mission_id,)
    ).fetchall()
    findings = [row["status"] for row in requirement_findings] + [row["status"] for row in fact_findings]
    if findings and not any(status in {"OBSERVED_REQUIRED", "OBSERVED"} for status in findings):
        raise ScoutError("COMPLETE requires at least one observed finding when findings exist")
    unproven_requirements = conn.execute(
        """SELECT COUNT(*) FROM requirements
           WHERE mission_id=? AND status='OBSERVED_REQUIRED' AND evidence_id IS NULL""",
        (mission_id,),
    ).fetchone()[0]
    if unproven_requirements:
        raise ScoutError("COMPLETE requires evidence for every observed requirement")
    rows = conn.execute(
        "SELECT id,next_step_ids_json FROM steps WHERE mission_id=?", (mission_id,)
    ).fetchall()
    if rows:
        step_ids = {row["id"] for row in rows}
        incoming = {step_id: 0 for step_id in step_ids}
        adjacency: dict[str, list[str]] = {}
        for row in rows:
            targets = json.loads(row["next_step_ids_json"])
            adjacency[row["id"]] = targets
            for target in targets:
                if target in incoming:
                    incoming[target] += 1
        roots = [step_id for step_id, count in incoming.items() if count == 0]
        if len(roots) != 1:
            raise ScoutError("COMPLETE requires one connected route root")
        reached: set[str] = set()
        pending = [roots[0]]
        while pending:
            step_id = pending.pop()
            if step_id in reached:
                continue
            reached.add(step_id)
            pending.extend(adjacency.get(step_id, []))
        if reached != step_ids:
            raise ScoutError("COMPLETE requires every step to be reachable from the route root")
        remaining_incoming = dict(incoming)
        ready = [step_id for step_id, count in remaining_incoming.items() if count == 0]
        ordered = 0
        while ready:
            step_id = ready.pop()
            ordered += 1
            for target in adjacency.get(step_id, []):
                remaining_incoming[target] -= 1
                if remaining_incoming[target] == 0:
                    ready.append(target)
        if ordered != len(step_ids):
            raise ScoutError("COMPLETE requires an acyclic route graph")
    checkpoint_step = _owned_step(conn, mission_id, mission["last_completed_step_id"])
    if json.loads(checkpoint_step["next_step_ids_json"]):
        raise ScoutError("COMPLETE requires the durable checkpoint to be a terminal route step")
    if not safe_end_confirmed and not (
        checkpoint_step["status"] == "OBSERVED"
        and checkpoint_step["side_effect_risk"] == "CONSEQUENTIAL"
        and not checkpoint_step["reversible"]
    ):
        raise ScoutError("COMPLETE requires the checkpoint at the observed consequential boundary")


def _fingerprint(*values: Any) -> str:
    canonical = "\x1f".join(normalize(str(value)) for value in values)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _reject_conflict(
    existing: sqlite3.Row, expected: Mapping[str, Any], entity: str
) -> None:
    conflicts = [field for field, value in expected.items() if existing[field] != value]
    if conflicts:
        raise ScoutError(f"conflicting duplicate {entity}: {', '.join(conflicts)}")


def _step_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["next_step_ids"] = json.loads(result.pop("next_step_ids_json"))
    result["evidence_ids"] = [
        item[0] for item in conn.execute(
            "SELECT id FROM evidence WHERE mission_id=? AND step_id=? ORDER BY captured_at,id",
            (row["mission_id"], row["id"]),
        )
    ]
    return result


def record_evidence(
    conn: sqlite3.Connection,
    mission_id: str,
    step_id: str | None,
    data: Mapping[str, Any],
) -> tuple[str, bool]:
    _assert_fields(data, {"kind", "source_url", "captured_at", "summary", "artifact_path"}, "evidence")
    _validate_no_secret_fields(data)
    kind = _require_choice("evidence.kind", data.get("kind"), EVIDENCE_KINDS)
    summary = _require_text("evidence.summary", data.get("summary"))
    source_url = _validate_url(data.get("source_url"), "evidence.source_url")
    artifact_path = _optional_text("evidence.artifact_path", data.get("artifact_path"))
    captured_at = _optional_text("evidence.captured_at", data.get("captured_at")) or utc_now()
    try:
        parsed_captured_at = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScoutError("evidence.captured_at must be an ISO-8601 timestamp") from exc
    if parsed_captured_at.tzinfo is None:
        raise ScoutError("evidence.captured_at must include a timezone")
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
        (evidence_id, mission_id, step_id, kind, source_url, captured_at, summary, artifact_path, dedupe_key),
    )
    return evidence_id, True


def record_step(data: Mapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    _assert_fields(data, {
        "mission_id", "kind", "title", "url", "domain", "status", "sequence_hint",
        "reversible", "side_effect_risk", "next_step_ids", "evidence", "dedupe_key",
    })
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
    if isinstance(sequence_hint, bool) or not isinstance(sequence_hint, int) or sequence_hint < 0:
        raise ScoutError("sequence_hint must be a non-negative integer")
    reversible = _require_bool("reversible", data.get("reversible", True))
    next_steps = data.get("next_step_ids", [])
    if not isinstance(next_steps, list) or not all(isinstance(item, str) for item in next_steps):
        raise ScoutError("next_step_ids must be a list of strings")
    evidence_inputs = data.get("evidence", [])
    if not isinstance(evidence_inputs, list):
        raise ScoutError("evidence must be a list")
    custom_dedupe = data.get("dedupe_key")
    if custom_dedupe is not None:
        custom_dedupe = _require_text("dedupe_key", custom_dedupe)
    legacy_dedupe_key = _fingerprint(kind, title, url)
    dedupe_key = custom_dedupe or _fingerprint(kind, title, url, sequence_hint)
    with transaction(path) as conn:
        mission = _mission(conn, mission_id)
        if mission["phase"] not in {"RECON", "BLOCKED"}:
            raise ScoutError(f"steps cannot be recorded while mission is {mission['phase']}")
        for next_step_id in next_steps:
            _owned_step(conn, mission_id, next_step_id)
        existing = conn.execute(
            "SELECT * FROM steps WHERE mission_id=? AND dedupe_key=?", (mission_id, dedupe_key)
        ).fetchone()
        if existing is None and custom_dedupe is None:
            existing = conn.execute(
                """SELECT * FROM steps
                   WHERE mission_id=? AND dedupe_key=? AND sequence_hint=?""",
                (mission_id, legacy_dedupe_key, sequence_hint),
            ).fetchone()
            if existing is not None:
                conn.execute("UPDATE steps SET dedupe_key=? WHERE id=?", (dedupe_key, existing["id"]))
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
            _reject_conflict(existing, {
                "kind": kind, "title": title, "url": url, "domain": domain,
            }, "step")
            status_changed = existing["status"] != status
            if status_changed and status != "OBSERVED":
                raise ScoutError("step status may only advance to OBSERVED")
            risk_rank = {"NONE": 0, "LOW": 1, "CONSEQUENTIAL": 2}
            if risk_rank[risk] < risk_rank[existing["side_effect_risk"]]:
                raise ScoutError("step side_effect_risk cannot be downgraded")
            if not existing["reversible"] and reversible:
                raise ScoutError("an irreversible step cannot become reversible")
            merged_links = list(dict.fromkeys(json.loads(existing["next_step_ids_json"]) + next_steps))
            conn.execute(
                """UPDATE steps SET status=?, reversible=?, side_effect_risk=?, next_step_ids_json=?
                   WHERE id=?""",
                (status, int(existing["reversible"] and reversible), risk,
                 json.dumps(merged_links, separators=(",", ":")), step_id),
            )
            if status_changed or risk != existing["side_effect_risk"] or int(reversible) != existing["reversible"]:
                _event(conn, mission_id, "STEP_UPDATED", {"step_id": step_id})
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
        step = _step_dict(conn, conn.execute("SELECT * FROM steps WHERE id=?", (step_id,)).fetchone())
    return {"ok": True, "created": created, "evidence_created": evidence_created, "step": step, "evidence_ids": evidence_ids}


def link_steps(data: Mapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    _assert_fields(data, {"mission_id", "from_step_id", "to_step_id"})
    _validate_no_secret_fields(data)
    mission_id = _require_text("mission_id", data.get("mission_id"))
    from_step_id = _require_text("from_step_id", data.get("from_step_id"))
    to_step_id = _require_text("to_step_id", data.get("to_step_id"))
    if from_step_id == to_step_id:
        raise ScoutError("a step cannot link to itself")
    with transaction(path) as conn:
        mission = _mission(conn, mission_id)
        if mission["phase"] not in {"RECON", "BLOCKED"}:
            raise ScoutError(f"steps cannot be linked while mission is {mission['phase']}")
        source = _owned_step(conn, mission_id, from_step_id)
        _owned_step(conn, mission_id, to_step_id)
        links = json.loads(source["next_step_ids_json"])
        created = to_step_id not in links
        if created:
            links.append(to_step_id)
            conn.execute(
                "UPDATE steps SET next_step_ids_json=? WHERE id=?",
                (json.dumps(links, separators=(",", ":")), from_step_id),
            )
            _event(conn, mission_id, "STEP_LINKED", {
                "from_step_id": from_step_id, "to_step_id": to_step_id,
            })
        result = _step_dict(conn, conn.execute("SELECT * FROM steps WHERE id=?", (from_step_id,)).fetchone())
    return {"ok": True, "created": created, "step": result}


def record_requirement(data: Mapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    _assert_fields(data, {"mission_id", "step_id", "name", "category", "status", "details", "evidence_id"})
    _validate_no_secret_fields(data)
    mission_id = _require_text("mission_id", data.get("mission_id"))
    name = _require_text("name", data.get("name"))
    category = _require_choice("category", data.get("category"), REQUIREMENT_CATEGORIES)
    status = _require_choice("status", data.get("status"), REQUIREMENT_STATUSES)
    step_id = data.get("step_id")
    details = _optional_text("details", data.get("details"))
    evidence_id = data.get("evidence_id")
    if status == "OBSERVED_REQUIRED" and evidence_id is None:
        raise ScoutError("observed requirement requires evidence_id")
    dedupe_key = _fingerprint(mission_id, category, name, step_id)
    with transaction(path) as conn:
        mission = _mission(conn, mission_id)
        if mission["phase"] not in {"RECON", "BLOCKED"}:
            raise ScoutError(f"requirements cannot be recorded while mission is {mission['phase']}")
        _owned_step(conn, mission_id, step_id)
        evidence = _owned_evidence(conn, mission_id, evidence_id)
        if evidence is not None and step_id is not None and evidence["step_id"] not in {None, step_id}:
            raise ScoutError("evidence_id belongs to a different step")
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
            _reject_conflict(existing, {
                "step_id": step_id, "name": name, "category": category,
            }, "requirement")
            if existing["status"] == status:
                _reject_conflict(existing, {
                    "details": details, "evidence_id": evidence_id,
                }, "requirement")
            elif status != "OBSERVED_REQUIRED":
                raise ScoutError("requirement status may only advance to OBSERVED_REQUIRED")
            if existing["status"] == "OBSERVED_REQUIRED" and status != existing["status"]:
                raise ScoutError("observed requirement status cannot be downgraded")
            if existing["status"] != status:
                conn.execute(
                    "UPDATE requirements SET status=?,details=?,evidence_id=? WHERE id=?",
                    (status, details, evidence_id, requirement_id),
                )
                _event(conn, mission_id, "REQUIREMENT_UPDATED", {"requirement_id": requirement_id})
        _refresh_summary(conn, mission_id)
        result = _row(conn.execute("SELECT * FROM requirements WHERE id=?", (requirement_id,)).fetchone())
    return {"ok": True, "created": created, "requirement": result}


def record_blocker(data: Mapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    _assert_fields(data, {"mission_id", "step_id", "type", "description", "recoverable", "owner_action"})
    _validate_no_secret_fields(data)
    mission_id = _require_text("mission_id", data.get("mission_id"))
    blocker_type = _require_choice("type", data.get("type"), BLOCKER_TYPES)
    description = _require_text("description", data.get("description"))
    step_id = data.get("step_id")
    recoverable = _require_bool("recoverable", data.get("recoverable"))
    owner_action = _optional_text("owner_action", data.get("owner_action"))
    dedupe_key = _fingerprint(mission_id, blocker_type, description, step_id)
    with transaction(path) as conn:
        mission = _mission(conn, mission_id)
        if mission["phase"] not in {"RECON", "BLOCKED"}:
            raise ScoutError(f"blockers cannot be recorded while mission is {mission['phase']}")
        _owned_step(conn, mission_id, step_id)
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
            _reject_conflict(existing, {
                "step_id": step_id, "type": blocker_type, "description": description,
                "recoverable": int(recoverable), "owner_action": owner_action,
            }, "blocker")
        _refresh_summary(conn, mission_id)
        result = _row(conn.execute("SELECT * FROM blockers WHERE id=?", (blocker_id,)).fetchone())
    return {"ok": True, "created": created, "blocker": result}


def resolve_blocker(data: Mapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    _assert_fields(data, {"mission_id", "blocker_id"})
    _validate_no_secret_fields(data)
    mission_id = _require_text("mission_id", data.get("mission_id"))
    blocker_id = _require_text("blocker_id", data.get("blocker_id"))
    with transaction(path) as conn:
        mission = _mission(conn, mission_id)
        if mission["phase"] not in {"RECON", "BLOCKED"}:
            raise ScoutError(f"blockers cannot be resolved while mission is {mission['phase']}")
        blocker = conn.execute(
            "SELECT * FROM blockers WHERE id=? AND mission_id=?", (blocker_id, mission_id)
        ).fetchone()
        if blocker is None:
            raise ScoutError("blocker_id does not belong to mission")
        resolved = blocker["resolved_at"] is not None
        if not resolved:
            now = utc_now()
            conn.execute("UPDATE blockers SET resolved_at=? WHERE id=?", (now, blocker_id))
            _event(conn, mission_id, "BLOCKER_RESOLVED", {"blocker_id": blocker_id})
        result = _row(conn.execute("SELECT * FROM blockers WHERE id=?", (blocker_id,)).fetchone())
    return {"ok": True, "already_resolved": resolved, "blocker": result}


def record_fact(data: Mapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    _assert_fields(data, {
        "mission_id", "step_id", "type", "name", "value", "status", "details", "evidence_id",
    })
    _validate_no_secret_fields(data)
    mission_id = _require_text("mission_id", data.get("mission_id"))
    fact_type = _require_choice("type", data.get("type"), FACT_TYPES)
    name = _require_text("name", data.get("name"))
    value = _optional_text("value", data.get("value"))
    status = _require_choice("status", data.get("status"), FACT_STATUSES)
    details = _optional_text("details", data.get("details"))
    step_id = data.get("step_id")
    evidence_id = data.get("evidence_id")
    if status == "OBSERVED" and evidence_id is None:
        raise ScoutError("observed fact requires evidence_id")
    dedupe_key = _fingerprint(mission_id, fact_type, name, step_id)
    with transaction(path) as conn:
        mission = _mission(conn, mission_id)
        if mission["phase"] not in {"RECON", "BLOCKED"}:
            raise ScoutError(f"facts cannot be recorded while mission is {mission['phase']}")
        _owned_step(conn, mission_id, step_id)
        evidence = _owned_evidence(conn, mission_id, evidence_id)
        if evidence is not None and step_id is not None and evidence["step_id"] not in {None, step_id}:
            raise ScoutError("evidence_id belongs to a different step")
        existing = conn.execute(
            "SELECT * FROM facts WHERE mission_id=? AND dedupe_key=?", (mission_id, dedupe_key)
        ).fetchone()
        created = existing is None
        if created:
            fact_id = new_id("fact")
            conn.execute(
                """INSERT INTO facts(id,mission_id,step_id,type,name,value,status,details,evidence_id,dedupe_key,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (fact_id, mission_id, step_id, fact_type, name, value, status, details,
                 evidence_id, dedupe_key, utc_now()),
            )
            _event(conn, mission_id, "FACT_FOUND", {"fact_id": fact_id, "type": fact_type})
        else:
            fact_id = existing["id"]
            _reject_conflict(existing, {
                "step_id": step_id, "type": fact_type, "name": name,
            }, "fact")
            if existing["status"] == status:
                _reject_conflict(existing, {
                    "value": value, "details": details, "evidence_id": evidence_id,
                }, "fact")
            elif status != "OBSERVED":
                raise ScoutError("fact status may only advance to OBSERVED")
            if existing["status"] == "OBSERVED" and status != existing["status"]:
                raise ScoutError("observed fact status cannot be downgraded")
            if existing["status"] != status:
                conn.execute(
                    "UPDATE facts SET value=?,status=?,details=?,evidence_id=? WHERE id=?",
                    (value, status, details, evidence_id, fact_id),
                )
                _event(conn, mission_id, "FACT_UPDATED", {"fact_id": fact_id, "type": fact_type})
        result = _row(conn.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone())
    return {"ok": True, "created": created, "fact": result}


def checkpoint(data: Mapping[str, Any], path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    _assert_fields(data, {"mission_id", "last_completed_step_id", "current_url"})
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
        screenshot = conn.execute(
            """SELECT 1 FROM evidence
               WHERE mission_id=? AND step_id=? AND kind='SCREENSHOT' LIMIT 1""",
            (mission_id, step_id),
        ).fetchone()
        if screenshot is None:
            raise ScoutError("checkpoint requires screenshot evidence from Plow Latch")
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
    _assert_fields(data, {"mission_id"})
    _validate_no_secret_fields(data)
    mission_id = _require_text("mission_id", data.get("mission_id"))
    with closing(_connect(path)) as conn:
        mission = _row(_mission(conn, mission_id))
        steps = [_step_dict(conn, row) for row in conn.execute("SELECT * FROM steps WHERE mission_id=? ORDER BY sequence_hint,created_at", (mission_id,))]
        evidence = [dict(row) for row in conn.execute("SELECT * FROM evidence WHERE mission_id=? ORDER BY captured_at", (mission_id,))]
        requirements = [dict(row) for row in conn.execute("SELECT * FROM requirements WHERE mission_id=? ORDER BY created_at", (mission_id,))]
        blockers = [dict(row) for row in conn.execute("SELECT * FROM blockers WHERE mission_id=? ORDER BY created_at", (mission_id,))]
        facts = [dict(row) for row in conn.execute("SELECT * FROM facts WHERE mission_id=? ORDER BY created_at", (mission_id,))]
        events = [dict(row) for row in conn.execute("SELECT * FROM mission_events WHERE mission_id=? ORDER BY timestamp", (mission_id,))]
    return {"ok": True, "mission": mission, "steps": steps, "evidence": evidence, "requirements": requirements, "blockers": blockers, "facts": facts, "events": events}


def latest_active_mission(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    with closing(_connect(path)) as conn:
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
