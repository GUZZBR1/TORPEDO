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


def _validate_route(steps: list[Mapping[str, Any]]) -> list[str]:
    step_ids = {step["id"] for step in steps}
    incoming = {step_id: 0 for step_id in step_ids}
    adjacency: dict[str, list[str]] = {}
    for step in steps:
        targets = [target for target in step.get("next_step_ids", []) if target in step_ids]
        adjacency[step["id"]] = targets
        for target in targets:
            incoming[target] += 1
    roots = [step_id for step_id, count in incoming.items() if count == 0]
    if len(roots) != 1:
        raise ScoutError("normal COMPLETE report requires one connected route root")
    reached: set[str] = set()
    pending = [roots[0]]
    while pending:
        step_id = pending.pop()
        if step_id in reached:
            continue
        reached.add(step_id)
        pending.extend(adjacency[step_id])
    if reached != step_ids:
        raise ScoutError("normal COMPLETE report requires a connected route")
    remaining = dict(incoming)
    sequence = {step["id"]: index for index, step in enumerate(steps)}
    ready = sorted(
        (step_id for step_id, count in remaining.items() if count == 0),
        key=sequence.__getitem__,
    )
    ordered: list[str] = []
    while ready:
        step_id = ready.pop(0)
        ordered.append(step_id)
        for target in adjacency[step_id]:
            remaining[target] -= 1
            if remaining[target] == 0:
                ready.append(target)
                ready.sort(key=sequence.__getitem__)
    if len(ordered) != len(step_ids):
        raise ScoutError("normal COMPLETE report requires an acyclic route")
    return ordered


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
    route_order = _validate_route(steps)
    steps_by_id = {step["id"]: step for step in steps}
    steps = [steps_by_id[step_id] for step_id in route_order]
    screenshot_step_ids = {
        item["step_id"] for item in evidence
        if item.get("step_id") and item.get("kind") == "SCREENSHOT"
    }
    if any(step["id"] not in screenshot_step_ids for step in observed_steps):
        raise ScoutError("every observed step must have screenshot evidence")
    if any(
        item["status"] == "OBSERVED_REQUIRED" and not item.get("evidence_id")
        for item in requirements
    ):
        raise ScoutError("every observed requirement must have evidence")
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
        (
            step for step in reversed(steps)
            if step["status"] == "OBSERVED"
            and step["side_effect_risk"] == "CONSEQUENTIAL"
            and not step["reversible"]
            and step["id"] in screenshot_step_ids
        ),
        None,
    )
    checkpoint_step = steps_by_id.get(mission.get("last_completed_step_id"))
    if checkpoint_step is None or checkpoint_step.get("next_step_ids"):
        raise ScoutError("normal COMPLETE report requires a terminal durable checkpoint")
    if (
        boundary is not None
        and not mission.get("safe_end_confirmed")
        and checkpoint_step["id"] != boundary["id"]
    ):
        raise ScoutError("normal COMPLETE report requires the checkpoint at the consequential boundary")
    target = mission.get("target_name") or mission.get("entrypoint") or mission["raw_user_request"]
    lines = [
        "SCOUT COMPLETE", "", "Target", target, "", "Route",
        f"{mission['total_steps']} steps", f"{mission['external_domains']} external domains",
    ]
    for index, step in enumerate(steps, start=1):
        destination_count = len(step.get("next_step_ids", []))
        branch = f"; {destination_count} next" if destination_count else ""
        lines.append(
            f"{index}. [{step['status']}] {step['title']}"
            + (f" — {step['url']}" if step.get("url") else "")
            + branch
        )
    lines.extend(["", "You need"])
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
