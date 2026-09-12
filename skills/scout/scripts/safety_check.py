#!/usr/bin/env python3
"""Fail-closed deterministic classifier for proposed Scout actions."""

from __future__ import annotations

import re
from typing import Any, Mapping

from scout_db import ScoutError, cli, normalize


IRREVERSIBLE_PATTERNS = (
    r"\b(final[ -]?submit|submit application|place order|buy now|purchase now)\b",
    r"\b(pay now|make payment|confirm payment|charge card|subscribe now)\b",
    r"\b(delete|remove account|close account|cancel subscription|cancel order)\b",
    r"\b(send (?:the )?(?:email|message|sms)|publish|post publicly)\b",
    r"\b(sign (?:the )?(?:contract|agreement)|accept (?:the )?(?:terms|contract|agreement))\b",
    r"\b(certify|legally attest|complete identity verification)\b",
)
CONSEQUENTIAL_ACTION_TYPES = {
    "submit", "purchase", "pay", "delete", "cancel", "send_message",
    "publish", "sign", "accept_contract", "verify_identity",
}
READ_ONLY_ACTION_TYPES = {"screenshot", "inspect", "read", "wait", "scroll"}
NAVIGATION_ACTION_TYPES = {"navigate", "open", "click", "back", "forward", "extend_scope"}
DRAFT_ACTION_TYPES = {"fill", "select", "upload_draft"}


def classify_action(data: Mapping[str, Any], path: str | None = None) -> dict[str, Any]:
    del path
    action_type = normalize(str(data.get("action_type", ""))).replace(" ", "_")
    target = normalize(str(data.get("target", "")))
    description = normalize(str(data.get("description", "")))
    combined = " ".join(part for part in (action_type, target, description) if part)
    if not action_type:
        raise ScoutError("action_type is required")

    matched = next((pattern for pattern in IRREVERSIBLE_PATTERNS if re.search(pattern, combined)), None)
    if action_type in CONSEQUENTIAL_ACTION_TYPES or matched:
        return {
            "ok": True,
            "allowed": False,
            "classification": "IRREVERSIBLE",
            "reason": "proposed action crosses a Scout MVP hard-stop boundary",
        }
    if action_type in READ_ONLY_ACTION_TYPES:
        return {"ok": True, "allowed": True, "classification": "READ_ONLY", "reason": "read-only observation"}
    if action_type in NAVIGATION_ACTION_TYPES:
        return {
            "ok": True,
            "allowed": True,
            "classification": "REVERSIBLE_NAVIGATION",
            "reason": "navigation does not itself create the described side effect",
        }
    if action_type in DRAFT_ACTION_TYPES:
        if data.get("narrowly_justified") is True and data.get("creates_side_effect") is False:
            return {
                "ok": True,
                "allowed": True,
                "classification": "DRAFT_MUTATION",
                "reason": "explicitly justified draft mutation with no declared side effect",
            }
        return {
            "ok": True,
            "allowed": False,
            "classification": "DRAFT_MUTATION",
            "reason": "draft mutations require narrow justification and creates_side_effect=false",
        }
    return {
        "ok": True,
        "allowed": False,
        "classification": "CONSEQUENTIAL",
        "reason": "unknown action type; Scout fails closed",
    }


if __name__ == "__main__":
    cli(classify_action)
