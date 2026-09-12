#!/usr/bin/env python3
"""Validated deterministic Scout report builder."""

from __future__ import annotations

from typing import Any, Mapping

from scout_db import ScoutError, cli, show_mission


def _line(requirement: Mapping[str, Any]) -> str:
    marker = "✓" if requirement["status"] == "OBSERVED_REQUIRED" else "○"
    details = f" — {requirement['details']}" if requirement.get("details") else ""
    return f"{marker} {requirement['name']}{details}"


def build_report(data: Mapping[str, Any], path: str | None = None) -> dict[str, Any]:
    snapshot = show_mission(data, path)
    mission = snapshot["mission"]
    steps = snapshot["steps"]
    evidence = snapshot["evidence"]
    requirements = snapshot["requirements"]
    blockers = snapshot["blockers"]

    if mission["phase"] != "COMPLETE":
        raise ScoutError("normal COMPLETE report requires mission phase COMPLETE")
    observed_steps = [step for step in steps if step["status"] == "OBSERVED"]
    if not observed_steps:
        raise ScoutError("normal COMPLETE report requires at least one observed step")
    observed_step_ids = {item["step_id"] for item in evidence if item.get("step_id")}
    if not any(step["id"] in observed_step_ids for step in observed_steps):
        raise ScoutError("an observed step must have recorded evidence")
    if requirements and all(item["status"] != "OBSERVED_REQUIRED" for item in requirements):
        raise ScoutError("all findings are inferred or unknown; observed evidence is required")

    costs = [item for item in requirements if item["category"] == "PAYMENT" and item["status"] == "OBSERVED_REQUIRED"]
    for cost in costs:
        if not cost.get("evidence_id"):
            raise ScoutError("observed cost lacks evidence")
    deadlines = [
        item for item in requirements
        if "deadline" in f"{item['name']} {item.get('details') or ''}".casefold()
        and item["status"] == "OBSERVED_REQUIRED"
    ]
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
    lines.extend(_line(item) for item in requirements if item["category"] != "PAYMENT")
    if not requirements:
        lines.append("○ No requirements were recorded")
    lines.extend(["", "Blockers"])
    lines.extend(f"! {item['description']}" for item in blockers)
    if not blockers:
        lines.append("None observed")
    lines.extend(["", "Costs"])
    lines.extend(item.get("details") or item["name"] for item in costs)
    if not costs:
        lines.append("No observed fees")
    lines.extend(["", "Deadlines"])
    lines.extend(item.get("details") or item["name"] for item in deadlines)
    if not deadlines:
        lines.append("No observed deadlines")
    lines.extend(["", "Side-effect boundary"])
    lines.append(f"Scout stopped before {boundary['title']}." if boundary else "No consequential action was reached.")
    unknowns = [item for item in requirements if item["status"] == "UNKNOWN"]
    lines.extend(["", "Ready"])
    lines.append("Resolve: " + "; ".join(item["name"] for item in unknowns) if unknowns else "The mapped route is ready for user review.")

    return {
        "ok": True,
        "report": "\n".join(lines),
        "observed": [item for item in requirements if item["status"] == "OBSERVED_REQUIRED"],
        "inferred": [item for item in requirements if item["status"] == "INFERRED"],
        "unknown": unknowns,
    }


if __name__ == "__main__":
    cli(build_report)

