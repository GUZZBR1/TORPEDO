#!/usr/bin/env python3
"""Validated deterministic Scout report builder."""

from __future__ import annotations

from typing import Any, Mapping

from scout_db import ScoutError, cli, show_mission


def _line(requirement: Mapping[str, Any]) -> str:
    marker = "✓" if requirement["status"] == "OBSERVED_REQUIRED" else "○"
    details = f" — {requirement['details']}" if requirement.get("details") else ""
    return f"{marker} {requirement['name']}{details}"


def _fact_line(fact: Mapping[str, Any]) -> str:
    value = f": {fact['value']}" if fact.get("value") else ""
    details = f" — {fact['details']}" if fact.get("details") else ""
    return f"{fact['name']}{value}{details}"


def build_report(data: Mapping[str, Any], path: str | None = None) -> dict[str, Any]:
    snapshot = show_mission(data, path)
    mission = snapshot["mission"]
    steps = snapshot["steps"]
    evidence = snapshot["evidence"]
    requirements = snapshot["requirements"]
    blockers = snapshot["blockers"]
    facts = snapshot["facts"]

    if mission["phase"] != "COMPLETE":
        raise ScoutError("normal COMPLETE report requires mission phase COMPLETE")
    observed_steps = [step for step in steps if step["status"] == "OBSERVED"]
    if not observed_steps:
        raise ScoutError("normal COMPLETE report requires at least one observed step")
    observed_step_ids = {item["step_id"] for item in evidence if item.get("step_id")}
    if not any(step["id"] in observed_step_ids for step in observed_steps):
        raise ScoutError("an observed step must have recorded evidence")
    all_findings = [item["status"] for item in requirements] + [item["status"] for item in facts]
    if all_findings and not any(status in {"OBSERVED_REQUIRED", "OBSERVED"} for status in all_findings):
        raise ScoutError("all findings are inferred or unknown; observed evidence is required")
    if any(item.get("resolved_at") is None for item in blockers):
        raise ScoutError("normal COMPLETE report cannot contain unresolved blockers")

    costs = [item for item in facts if item["type"] == "COST" and item["status"] == "OBSERVED"]
    for cost in costs:
        if not cost.get("evidence_id"):
            raise ScoutError("observed cost lacks evidence")
    deadlines = [item for item in facts if item["type"] == "DEADLINE" and item["status"] == "OBSERVED"]
    for deadline in deadlines:
        if not deadline.get("evidence_id"):
            raise ScoutError("observed deadline lacks evidence")

    boundary = next(
        (step for step in reversed(steps) if step["side_effect_risk"] == "CONSEQUENTIAL"),
        None,
    )
    target = mission.get("target_name") or mission.get("entrypoint") or mission["raw_user_request"]
    lines = [
        "SCOUT COMPLETE", "", "Target", target, "", "Route",
        f"{mission['total_steps']} steps", f"{mission['external_domains']} external domains", "",
        "You need",
    ]
    lines.extend(_line(item) for item in requirements)
    if not requirements:
        lines.append("○ No requirements were recorded")
    lines.extend(["", "Blockers"])
    lines.extend(
        f"! {item['description']}" + (" (resolved)" if item.get("resolved_at") else "")
        for item in blockers
    )
    if not blockers:
        lines.append("None observed")
    lines.extend(["", "Costs"])
    lines.extend(_fact_line(item) for item in costs)
    if not costs:
        lines.append("No observed fees")
    lines.extend(["", "Deadlines"])
    lines.extend(_fact_line(item) for item in deadlines)
    if not deadlines:
        lines.append("No observed deadlines")
    lines.extend(["", "Side-effect boundary"])
    lines.append(f"Scout stopped before {boundary['title']}." if boundary else "No consequential action was reached.")
    inferred_requirements = [item for item in requirements if item["status"] == "INFERRED"]
    inferred_facts = [item for item in facts if item["status"] == "INFERRED"]
    unknown_requirements = [item for item in requirements if item["status"] == "UNKNOWN"]
    unknown_facts = [item for item in facts if item["status"] == "UNKNOWN"]
    unknown_names = [item["name"] for item in [*unknown_requirements, *unknown_facts]]
    if inferred_requirements or inferred_facts or unknown_names:
        lines.extend(["", "Confidence"])
        lines.append("Observed facts are evidence-backed.")
        if inferred_requirements or inferred_facts:
            lines.append("Inferred: " + "; ".join(
                item["name"] for item in [*inferred_requirements, *inferred_facts]
            ))
        if unknown_names:
            lines.append("Unknown: " + "; ".join(unknown_names))
    lines.extend(["", "Ready"])
    lines.append("Resolve: " + "; ".join(unknown_names) if unknown_names else "The mapped route is ready for user review.")

    return {
        "ok": True,
        "report": "\n".join(lines),
        "observed": [
            *[item for item in requirements if item["status"] == "OBSERVED_REQUIRED"],
            *[item for item in facts if item["status"] == "OBSERVED"],
        ],
        "inferred": [*inferred_requirements, *inferred_facts],
        "unknown": [*unknown_requirements, *unknown_facts],
    }


if __name__ == "__main__":
    cli(build_report)
