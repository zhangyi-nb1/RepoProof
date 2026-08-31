import csv
import io
import re
from pathlib import Path

import networkx as nx


_COMMITMENTS = [
    "task-universe-and-order",
    "startable-status",
    "cycle-status-and-group",
    "direct-dependencies",
    "downstream-impact",
]
_INPUT_HEADER = ["task", "depends_on"]
_OUTPUT_HEADER = [
    "task",
    "direct_dependencies",
    "direct_dependents",
    "downstream_count",
    "ready_now",
    "in_cycle",
]
_UINT = re.compile(r"(?:0|[1-9][0-9]*)\Z")


def _result(ok: bool, reasons: list[str], checked: list[str]) -> dict:
    return {
        "ok": bool(ok),
        "reason_codes": sorted(set(reasons)),
        "checked_commitment_ids": checked,
    }


def _read_graph(input_path: Path) -> nx.DiGraph:
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, strict=True))
    if not rows or rows[0] != _INPUT_HEADER:
        raise ValueError("public input precondition failed")

    graph = nx.DiGraph()
    for row in rows[1:]:
        if len(row) != 2:
            raise ValueError("public input precondition failed")
        task, dependency = row
        if task == "":
            raise ValueError("public input precondition failed")
        graph.add_node(task)
        if dependency != "":
            graph.add_edge(dependency, task)
    return graph


def _expectations(graph: nx.DiGraph) -> dict[str, dict]:
    cycle_nodes: set[str] = set()
    for component in nx.strongly_connected_components(graph):
        if len(component) > 1:
            cycle_nodes.update(component)
        else:
            node = next(iter(component))
            if graph.has_edge(node, node):
                cycle_nodes.add(node)

    expected = {}
    for task in sorted(graph.nodes):
        in_degree = int(graph.in_degree(task))
        expected[task] = {
            "direct_dependencies": in_degree,
            "direct_dependents": int(graph.out_degree(task)),
            "downstream_count": len(nx.descendants(graph, task)),
            "ready_now": in_degree == 0,
            "in_cycle": task in cycle_nodes,
        }
    return expected


def _parse_artifact(artifact_path: Path) -> list[dict] | None:
    try:
        text = artifact_path.read_text(encoding="utf-8")
        rows = list(
            csv.reader(
                io.StringIO(text, newline=""),
                dialect="excel-tab",
                strict=True,
            )
        )
    except (OSError, UnicodeDecodeError, csv.Error):
        return None
    if not rows or rows[0] != _OUTPUT_HEADER:
        return None

    parsed = []
    for row in rows[1:]:
        if len(row) != len(_OUTPUT_HEADER):
            return None
        task, direct_dependencies, direct_dependents, downstream_count, ready_now, in_cycle = row
        if task == "":
            return None
        if not all(
            _UINT.fullmatch(value)
            for value in (direct_dependencies, direct_dependents, downstream_count)
        ):
            return None
        if ready_now not in ("true", "false") or in_cycle not in ("true", "false"):
            return None
        parsed.append(
            {
                "task": task,
                "direct_dependencies": int(direct_dependencies),
                "direct_dependents": int(direct_dependents),
                "downstream_count": int(downstream_count),
                "ready_now": ready_now == "true",
                "in_cycle": in_cycle == "true",
            }
        )
    return parsed


def verify(input_path: Path, artifact_path: Path) -> dict:
    try:
        graph = _read_graph(input_path)
    except (OSError, UnicodeDecodeError, csv.Error, ValueError):
        return _result(False, ["PUBLIC_INPUT_PRECONDITION_FAILED"], [])

    expected = _expectations(graph)
    observed = _parse_artifact(artifact_path)
    if observed is None:
        return _result(False, ["ARTIFACT_PROTOCOL_INVALID"], [])

    expected_tasks = sorted(expected)
    observed_tasks = [row["task"] for row in observed]
    checked = ["task-universe-and-order"]
    if observed_tasks != expected_tasks or len(set(observed_tasks)) != len(observed_tasks):
        return _result(False, ["TASK_UNIVERSE_AND_ORDER_MISMATCH"], checked)

    by_task = {row["task"]: row for row in observed}
    reasons = []

    checked.append("startable-status")
    if any(
        by_task[task]["ready_now"] != expected[task]["ready_now"]
        for task in expected_tasks
    ):
        reasons.append("STARTABLE_STATUS_MISMATCH")

    checked.append("cycle-status-and-group")
    if any(
        by_task[task]["in_cycle"] != expected[task]["in_cycle"]
        for task in expected_tasks
    ):
        reasons.append("CYCLE_STATUS_MISMATCH")

    checked.append("direct-dependencies")
    if any(
        by_task[task]["direct_dependencies"] != expected[task]["direct_dependencies"]
        or by_task[task]["direct_dependents"] != expected[task]["direct_dependents"]
        for task in expected_tasks
    ):
        reasons.append("DIRECT_DEGREE_MISMATCH")

    checked.append("downstream-impact")
    if any(
        by_task[task]["downstream_count"] != expected[task]["downstream_count"]
        for task in expected_tasks
    ):
        reasons.append("DOWNSTREAM_COUNT_MISMATCH")

    return _result(not reasons, reasons, checked)
