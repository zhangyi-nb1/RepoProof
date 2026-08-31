import csv
import io
from pathlib import Path

import networkx as nx


class UserInputError(ValueError):
    pass


_HEADER = ["task", "depends_on"]
_OUTPUT_HEADER = [
    "task",
    "direct_dependencies",
    "direct_dependents",
    "downstream_count",
    "ready_now",
    "in_cycle",
]


def _load_graph(input_path: Path) -> nx.DiGraph:
    try:
        with input_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle, strict=True))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise UserInputError("INPUT_CSV_INVALID") from exc

    if not rows or rows[0] != _HEADER:
        raise UserInputError("INPUT_HEADER_INVALID")
    graph = nx.DiGraph()
    for row in rows[1:]:
        if len(row) != 2:
            raise UserInputError("INPUT_ROW_WIDTH_INVALID")
        task, dependency = row
        if task == "":
            raise UserInputError("INPUT_TASK_EMPTY")
        graph.add_node(task)
        if dependency != "":
            graph.add_edge(dependency, task)
    return graph


def extract(input_path: Path) -> str:
    graph = _load_graph(input_path)
    cycle_nodes: set[str] = set()
    for component in nx.strongly_connected_components(graph):
        if len(component) > 1:
            cycle_nodes.update(component)
        else:
            node = next(iter(component))
            if graph.has_edge(node, node):
                cycle_nodes.add(node)

    output = io.StringIO(newline="")
    writer = csv.writer(output, dialect="excel-tab", lineterminator="\n")
    writer.writerow(_OUTPUT_HEADER)
    for task in sorted(graph.nodes):
        in_degree = int(graph.in_degree(task))
        writer.writerow(
            [
                task,
                str(in_degree),
                str(int(graph.out_degree(task))),
                str(len(nx.descendants(graph, task))),
                "true" if in_degree == 0 else "false",
                "true" if task in cycle_nodes else "false",
            ]
        )
    return output.getvalue()
