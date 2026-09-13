#!/usr/bin/env python3
"""Fail-closed deterministic classifier for proposed Scout actions."""

from __future__ import annotations

import re
from typing import Any, Mapping

from scout_db import ScoutError, cli, normalize, show_mission


IRREVERSIBLE_PATTERNS = (
    r"\b(final[ -]?submit|submit|place (?:the )?order|confirm (?:the )?order|buy now|purchase now)\b",
    r"\b(pay|make (?:the )?payment|confirm (?:the )?payment|charge (?:the )?card|subscribe now|start subscription)\b",
    r"\b(delete|remove|close) (?:the )?(?:account|record|application)\b",
    r"\bcancel (?:the )?(?:subscription|order|booking|application)\b",
    r"\bsend (?:the )?(?:email|message|sms|notification)\b|\b(publish|post publicly)\b",
    r"\b(sign (?:the )?(?:contract|agreement)|accept (?:the )?(?:terms|contract|agreement))\b",
    r"\b(certify|legally attest|complete identity verification|create (?:the )?account)\b",
    r"\b(enviar (?:a )?(?:inscri[cç][aã]o|mensagem)|comprar agora|pagar agora|excluir conta)\b",
    r"\b(cancelar assinatura|aceitar (?:os )?termos|assinar contrato|publicar|confirmar pagamento)\b",
)
CONSEQUENTIAL_ACTION_TYPES = {
    "submit", "purchase", "pay", "delete", "cancel", "send_message",
    "publish", "sign", "accept_contract", "verify_identity", "subscribe",
    "create_account", "attest", "confirm_order", "send_email", "send_sms",
}
READ_ONLY_ACTION_TYPES = {"screenshot", "inspect", "read", "wait", "scroll"}
NAVIGATION_ACTION_TYPES = {"goto", "navigate", "open", "back", "forward", "extend_scope"}
DRAFT_ACTION_TYPES = {"fill", "select", "upload_draft", "fill_secret"}
FILE_LOOKUP_ACTION_TYPES = {"file_lookup", "list_files", "select_file"}
SAFE_CLICK_PATTERNS = (
    r"\b(continue|next|back|previous|view|show|open|review|details|learn more|start|begin)\b",
    r"\b(sign in|log in|entrar|continuar|pr[oó]ximo|voltar|ver detalhes|revisar)\b",
)
AUTHENTICATION_CLICK_PATTERNS = (
    r"\b(sign in|log in|entrar)\b",
    r"\bcontinue\s+(?:with|using|via)\b",
    r"\buse\s+(?:a\s+)?(?:google|apple|microsoft|github|facebook|sso)\s+account\b",
)
DANGEROUS_CLICK_PATTERNS = (
    r"\b(delete|remove|cancel|submit|pay|purchase|buy|send|publish|post|sign(?!\s+in\b)|"
    r"accept|authorize|allow|grant|consent|confirm|subscribe|create|attest|verify|"
    r"save|upload|share|connect|book|reserve|join|rsvp|enroll|apply)\b",
    r"\b(excluir|remover|cancelar|enviar|pagar|comprar|publicar|aceitar|autorizar|"
    r"permitir|confirmar|assinar|cadastrar|criar|reservar|inscrever)\b",
)


def _optional_string(data: Mapping[str, Any], field: str) -> str:
    value = data.get(field, "")
    if not isinstance(value, str):
        raise ScoutError(f"{field} must be a string")
    return normalize(value)


def _mission_policies(data: Mapping[str, Any], path: str | None) -> Mapping[str, Any] | None:
    mission_id = data.get("mission_id")
    if mission_id is None:
        return None
    if not isinstance(mission_id, str) or not mission_id.strip():
        raise ScoutError("mission_id must be a non-empty string")
    return show_mission({"mission_id": mission_id.strip()}, path)["mission"]


def _policy_denial(
    policies: Mapping[str, Any] | None,
    required: tuple[str, ...],
    classification: str,
) -> dict[str, Any] | None:
    if policies is None:
        return {
            "ok": True,
            "allowed": False,
            "classification": classification,
            "reason": "mission_id is required to enforce mission policy; Scout fails closed",
        }
    if policies["phase"] != "RECON":
        return {
            "ok": True,
            "allowed": False,
            "classification": classification,
            "reason": f"mission phase {policies['phase']} does not allow browser actions",
        }
    denied = [name for name in required if not bool(policies[name])]
    if denied:
        return {
            "ok": True,
            "allowed": False,
            "classification": classification,
            "reason": f"mission policy denies: {', '.join(denied)}",
        }
    return None


def classify_action(data: Mapping[str, Any], path: str | None = None) -> dict[str, Any]:
    allowed_fields = {
        "action_type", "target", "description", "narrowly_justified",
        "creates_side_effect", "user_approved", "mission_id",
    }
    unknown = sorted(str(key) for key in data if key not in allowed_fields)
    if unknown:
        raise ScoutError(f"unknown action field(s): {', '.join(unknown)}")
    if "mission_id" in data and (
        not isinstance(data["mission_id"], str) or not data["mission_id"].strip()
    ):
        raise ScoutError("mission_id must be a non-empty string")
    action_type = _optional_string(data, "action_type").replace(" ", "_")
    target = _optional_string(data, "target")
    description = _optional_string(data, "description")
    combined = " ".join(part for part in (action_type, target, description) if part)
    if not action_type:
        raise ScoutError("action_type is required")
    for field in ("narrowly_justified", "creates_side_effect", "user_approved"):
        if field in data and not isinstance(data[field], bool):
            raise ScoutError(f"{field} must be a boolean")

    # Looking at a consequential control is reconnaissance, not execution.
    if action_type in READ_ONLY_ACTION_TYPES:
        return {"ok": True, "allowed": True, "classification": "READ_ONLY", "reason": "read-only observation"}
    matched = next((pattern for pattern in IRREVERSIBLE_PATTERNS if re.search(pattern, combined)), None)
    if action_type in CONSEQUENTIAL_ACTION_TYPES or matched:
        return {
            "ok": True,
            "allowed": False,
            "classification": "IRREVERSIBLE",
            "reason": "proposed action crosses a Scout MVP hard-stop boundary",
        }
    if action_type in NAVIGATION_ACTION_TYPES:
        if data.get("creates_side_effect") is True:
            return {
                "ok": True, "allowed": False, "classification": "CONSEQUENTIAL",
                "reason": "navigation was declared to create a side effect",
            }
        denial = _policy_denial(
            _mission_policies(data, path), ("allow_navigation",), "REVERSIBLE_NAVIGATION"
        )
        if denial:
            return denial
        return {
            "ok": True,
            "allowed": True,
            "classification": "REVERSIBLE_NAVIGATION",
            "reason": "navigation does not itself create the described side effect",
        }
    if action_type == "click":
        if any(re.search(pattern, combined) for pattern in DANGEROUS_CLICK_PATTERNS):
            return {
                "ok": True,
                "allowed": False,
                "classification": "IRREVERSIBLE",
                "reason": "click target contains a consequential verb; Scout fails closed",
            }
        if any(re.search(pattern, combined) for pattern in SAFE_CLICK_PATTERNS) and data.get("creates_side_effect") is not True:
            required_policies = ["allow_navigation"]
            if any(re.search(pattern, combined) for pattern in AUTHENTICATION_CLICK_PATTERNS):
                required_policies.append("allow_authentication")
            denial = _policy_denial(
                _mission_policies(data, path), tuple(required_policies), "REVERSIBLE_NAVIGATION"
            )
            if denial:
                return denial
            return {
                "ok": True, "allowed": True, "classification": "REVERSIBLE_NAVIGATION",
                "reason": "click target is an explicitly reversible navigation control",
            }
        return {
            "ok": True, "allowed": False, "classification": "CONSEQUENTIAL",
            "reason": "ambiguous click target; Scout fails closed",
        }
    if action_type in FILE_LOOKUP_ACTION_TYPES:
        denial = _policy_denial(
            _mission_policies(data, path), ("allow_file_lookup",), "FILE_LOOKUP"
        )
        if denial:
            return denial
        return {
            "ok": True,
            "allowed": True,
            "classification": "FILE_LOOKUP",
            "reason": "mission policy allows local file metadata lookup",
        }
    if action_type in DRAFT_ACTION_TYPES:
        required_policies = {
            "fill_secret": ("allow_authentication",),
            "upload_draft": ("allow_form_draft", "allow_file_lookup"),
        }.get(action_type, ("allow_form_draft",))
        denial = _policy_denial(
            _mission_policies(data, path), required_policies, "DRAFT_MUTATION"
        )
        if denial:
            return denial
        approval_required = action_type in {"fill_secret", "upload_draft"}
        explicitly_approved = not approval_required or data.get("user_approved") is True
        if data.get("narrowly_justified") is True and data.get("creates_side_effect") is False and explicitly_approved:
            return {
                "ok": True,
                "allowed": True,
                "classification": "DRAFT_MUTATION",
                "reason": "explicitly justified and approved draft mutation with no declared side effect",
            }
        return {
            "ok": True,
            "allowed": False,
            "classification": "DRAFT_MUTATION",
            "reason": "draft mutations require narrow justification, no declared side effect, and approval for secret/file transfer",
        }
    return {
        "ok": True,
        "allowed": False,
        "classification": "CONSEQUENTIAL",
        "reason": "unknown action type; Scout fails closed",
    }


if __name__ == "__main__":
    cli(classify_action)
