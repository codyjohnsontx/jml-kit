"""Render a plan as Markdown (the PR comment and terminal view) or as JSON."""

import json
from dataclasses import asdict

from jml.changes import Change
from jml.planner import Plan


def _line(change: Change) -> str:
    return f"{change.SYMBOL} {f'{change.SYSTEM} {change.OBJECT}':<13} {change.describe()}"


def _block(lines: list[str]) -> list[str]:
    return ["```text", *lines, "```", ""]


def to_markdown(plan: Plan, source: str | None = None) -> str:
    out = ["## jml plan", ""]
    if source:
        out += [source, ""]
    if not plan.changes and not plan.refused:
        out += ["No changes. Okta and GitHub match the file.", ""]

    changes = [change for change in plan.changes if change not in plan.drift]
    drift = [change for change in plan.changes if change in plan.drift]
    if changes:
        out += [f"### Changes ({len(changes)})", ""]
        if not plan.drift_checked:
            out += [
                "Includes changes already needed before this one: run with `--base` to "
                "show them apart.",
                "",
            ]
        out += _block([_line(change) for change in changes])
    if drift:
        out += [
            f"### Already needed before this change ({len(drift)})",
            "",
            "The files at the base revision need these too: someone changed Okta or GitHub "
            "outside this repository, an end date has passed, or an apply has not run yet. "
            "Apply makes them match.",
            "",
            *_block([_line(change) for change in drift]),
        ]
    if plan.refused:
        out += [
            f"### Refused ({len(plan.refused)})",
            "",
            "Apply will not run until these are fixed.",
            "",
            *[f"- {reason}" for reason in plan.refused],
            "",
        ]
    if plan.unmanaged:
        width = max(len(item.name) for item in plan.unmanaged)
        out += [
            f"### Unmanaged ({len(plan.unmanaged)})",
            "",
            "Not in the people file, so left alone unless noted.",
            "",
            *_block(
                [
                    f"{f'{item.system} {item.object}':<18} {item.name:<{width}}  {item.note}"
                    for item in plan.unmanaged
                ]
            ),
        ]
    return "\n".join(out).rstrip() + "\n"


def to_json(plan: Plan) -> str:
    document = {
        "changes": [
            {
                "kind": change.kind(),
                "system": change.SYSTEM,
                "drift": change in plan.drift,
                **asdict(change),
            }
            for change in plan.changes
        ],
        "drift_checked": plan.drift_checked,
        "refused": list(plan.refused),
        "unmanaged": [asdict(item) for item in plan.unmanaged],
    }
    return json.dumps(document, indent=2) + "\n"
