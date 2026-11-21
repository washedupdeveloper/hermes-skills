"""Task classification and the routing map.

The classifier is a keyword table, not a model call: routing must be cheap,
repeatable and auditable. It can be wrong, which is why the draft it produces
is reviewed by the owner before any task runs.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

from . import mini_yaml
from .model import Decision, RoutingMap, TaskSpec


class TaskType(str, Enum):
    MECHANICAL = "mechanical"
    DOCS = "docs"
    TEST = "test"
    FEATURE = "feature"
    BUGFIX = "bugfix"
    REFACTOR = "refactor"
    ARCHITECTURE = "architecture"
    SECURITY = "security"
    UNCLASSIFIED = "unclassified"


# First match wins. Security and architecture sit first because a task that
# mentions either must not be mistaken for a feature.
RULES: tuple[tuple[TaskType, tuple[str, ...]], ...] = (
    (
        TaskType.SECURITY,
        (
            "security", "auth", "credential", "secret", "crypto", "encrypt",
            "permission", "sandbox", "injection", "xss", "csrf", "tls",
            "validate path", "path traversal", "token leak",
        ),
    ),
    (
        TaskType.ARCHITECTURE,
        (
            "architecture", "adr", "decide", "design", "boundary", "protocol",
            "state machine", "schema", "data model", "migrate", "interface contract",
        ),
    ),
    (
        TaskType.TEST,
        (
            "add a test", "add tests", "write a test", "regression test",
            "test coverage", "add coverage", "unit test",
        ),
    ),
    (
        TaskType.BUGFIX,
        (
            "fix", "bug", "repro", "crash", "mismatch", "broken",
            "fails", "failure", "traceback",
        ),
    ),
    (
        TaskType.REFACTOR,
        (
            "refactor", "split", "extract", "move ", "restructure", "simplify",
            "deduplicate", "decouple",
        ),
    ),
    (
        TaskType.TEST,
        (
            "test", "coverage", "fixture", "assert", "golden", "snapshot test",
        ),
    ),
    (
        TaskType.DOCS,
        (
            "docs", "documentation", "readme", "guide", "changelog", "agents.md",
            "comment", "docstring",
        ),
    ),
    (
        TaskType.MECHANICAL,
        (
            "rename", "format", "bump", "dependency", "version", "typo", "lint",
            "delete unused", "update import",
        ),
    ),
    (
        TaskType.FEATURE,
        (
            "add", "implement", "support", "introduce", "new ", "endpoint",
            "command", "flag", "option", "filter", "report",
        ),
    ),
)

REVIEW_TYPES = frozenset(
    {
        TaskType.BUGFIX,
        TaskType.REFACTOR,
        TaskType.SECURITY,
        TaskType.ARCHITECTURE,
    }
)

TAG = re.compile(r"\[(type|verify)\s*:\s*([^\]]+)\]", re.I)
CHECKBOX = re.compile(r"^\s*-\s*\[[ xX]\]\s+([0-9]+(?:\.[0-9]+)*)\s+(.+?)\s*$")


def classify(title: str) -> tuple[TaskType, tuple[str, ...]]:
    text = title.lower()
    for task_type, keywords in RULES:
        matched = tuple(keyword for keyword in keywords if keyword in text)
        if matched:
            return task_type, matched
    return TaskType.UNCLASSIFIED, ()


def _strip_tags(title: str) -> tuple[str, dict[str, str]]:
    tags: dict[str, str] = {}

    def take(match: re.Match[str]) -> str:
        tags[match.group(1).lower()] = match.group(2).strip()
        return ""

    return TAG.sub(take, title).strip(), tags


def draft_routing(change_dir: str | Path) -> RoutingMap:
    """Read tasks.md and propose one entry per task. Never writes."""
    directory = Path(change_dir)
    tasks_file = directory / "tasks.md"
    if not tasks_file.is_file():
        raise FileNotFoundError(f"no tasks.md in {directory}")
    tasks: dict[str, TaskSpec] = {}
    for line in tasks_file.read_text(encoding="utf-8").splitlines():
        match = CHECKBOX.match(line)
        if not match:
            continue
        identifier, raw_title = match.group(1), match.group(2)
        clean, tags = _strip_tags(raw_title)
        declared = tags.get("type", "").lower()
        if declared:
            try:
                task_type = TaskType(declared)
            except ValueError as exc:
                raise ValueError(
                    f"task {identifier}: unknown type {declared!r}"
                ) from exc
        else:
            task_type, _ = classify(clean)
        verify_raw = tags.get("verify", "")
        verify = tuple(part.strip() for part in verify_raw.split(";") if part.strip())
        tasks[identifier] = TaskSpec(
            id=identifier,
            title=clean,
            type=task_type.value,
            verify=verify,
        )
    return RoutingMap(change=directory.name, tasks=tasks)


def load_routing(path: str | Path) -> RoutingMap:
    source = Path(path)
    data = mini_yaml.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{source}: routing file must be a mapping")
    raw_tasks = data.get("tasks") or {}
    if not isinstance(raw_tasks, dict):
        raise ValueError(f"{source}: tasks must be a mapping of id to spec")
    tasks: dict[str, TaskSpec] = {}
    for identifier, spec in raw_tasks.items():
        if not isinstance(spec, dict):
            raise ValueError(f"{source}: task {identifier} must be a mapping")
        declared = str(spec.get("type", "unclassified")).lower()
        try:
            task_type = TaskType(declared)
        except ValueError as exc:
            raise ValueError(f"{source}: task {identifier}: unknown type {declared!r}") from exc
        verify = spec.get("verify") or []
        if isinstance(verify, str):
            verify = [verify]
        tasks[str(identifier)] = TaskSpec(
            id=str(identifier),
            title=str(spec.get("title", "")),
            type=task_type.value,
            verify=tuple(str(item) for item in verify),
            notes=str(spec.get("notes", "")),
        )
    return RoutingMap(
        change=str(data.get("change", source.parent.name)),
        tasks=tasks,
        path=str(source),
    )


def save_routing(routing: RoutingMap, path: str | Path) -> None:
    payload = {
        "schema": 1,
        "change": routing.change,
        "tasks": {
            identifier: {
                "type": task.type,
                "title": task.title,
                **({"verify": list(task.verify)} if task.verify else {}),
                **({"notes": task.notes} if task.notes else {}),
            }
            for identifier, task in routing.tasks.items()
        },
    }
    Path(path).write_text(mini_yaml.dumps(payload), encoding="utf-8")


def route(
    task: TaskSpec,
    baseline: str,
    *,
    judge: str | None = None,
    budget_usd: float | None = None,
    reviewer: str | None = None,
) -> Decision:
    """Turn one task into one decision. Pure: no clock, network or filesystem."""
    if not task.verify:
        return Decision(
            task_id=task.id,
            model=baseline,
            decider=None,
            tier="baseline",
            requires_review=False,
            predicate=(),
            reason="no acceptance predicate; add a scenario, test command or gate",
            needs_scoping=True,
            budget_usd=budget_usd,
        )
    try:
        task_type = TaskType(task.type)
    except ValueError:
        task_type = TaskType.UNCLASSIFIED

    decider = judge if task_type is TaskType.ARCHITECTURE else None
    requires_review = task_type in REVIEW_TYPES
    if task_type is TaskType.ARCHITECTURE:
        reason = "architecture decision: judge decides, baseline implements"
    elif requires_review:
        reason = f"{task_type.value}: baseline implements, review is mandatory"
    else:
        reason = f"{task_type.value}: baseline implements"
    return Decision(
        task_id=task.id,
        model=baseline,
        decider=decider,
        tier="judge" if decider else "baseline",
        requires_review=requires_review,
        predicate=task.verify,
        reason=reason,
        budget_usd=budget_usd,
        reviewer=reviewer if requires_review else None,
    )


def next_tier(current: str, ladder: list[str]) -> str | None:
    """The next model above `current`; the last rung when current is unknown."""
    if not ladder:
        return None
    try:
        index = ladder.index(current)
    except ValueError:
        return ladder[0]
    if index + 1 >= len(ladder):
        return None
    return ladder[index + 1]