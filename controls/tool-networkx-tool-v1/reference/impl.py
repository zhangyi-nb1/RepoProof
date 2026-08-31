import json
from pathlib import Path
from xml.etree.ElementTree import ParseError

import networkx as nx
from networkx.exception import NetworkXError


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    try:
        graph = nx.read_graphml(input_path)
    except (NetworkXError, ParseError, UnicodeDecodeError) as exc:
        raise UserInputError(str(exc)) from exc

    nodes = sorted((str(node) for node in graph.nodes()), key=str)
    if graph.is_directed():
        component_iter = nx.weakly_connected_components(graph)
    else:
        component_iter = nx.connected_components(graph)

    groups = [sorted((str(node) for node in component), key=str) for component in component_iter]
    groups.sort(key=lambda members: (-len(members), members))
    component_records = [
        {"id": index, "size": len(members), "nodes": members}
        for index, members in enumerate(groups, start=1)
    ]

    degrees = {str(node): degree for node, degree in graph.degree()}
    if degrees:
        maximum_degree = max(degrees.values())
        key_nodes = sorted(
            (node for node, degree in degrees.items() if degree == maximum_degree),
            key=str,
        )
    else:
        maximum_degree = None
        key_nodes = []

    isolated_nodes = sorted((str(node) for node in nx.isolates(graph)), key=str)
    dump = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    return "\n".join(
        [
            "# 图网络摘要",
            "",
            "## 规模",
            f"- 节点数：`{graph.number_of_nodes()}`",
            f"- 边数：`{graph.number_of_edges()}`",
            "",
            "## 分组",
            f"- 分量数：`{len(component_records)}`",
            "```json",
            dump(component_records),
            "```",
            "",
            "## 关键节点",
            f"- 最大度：`{dump(maximum_degree)}`",
            "```json",
            dump(key_nodes),
            "```",
            "",
            "## 落单节点",
            "```json",
            dump(isolated_nodes),
            "```",
            "",
        ]
    )
