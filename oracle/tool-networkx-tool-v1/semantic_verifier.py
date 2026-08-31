from pathlib import Path
import json
import re
import networkx as nx

_COMMITMENTS = ["graph-size", "component-groups", "key-nodes", "isolated-nodes"]


def _result(ok, codes, checked):
    return {"ok": bool(ok), "reason_codes": list(codes), "checked_commitment_ids": list(checked)}


def _section(lines, title):
    matches = [i for i, line in enumerate(lines) if re.match(r"^##\s+" + re.escape(title) + r"\s*$", line)]
    if len(matches) != 1:
        raise ValueError("section")
    start = matches[0] + 1
    end = len(lines)
    for i in range(start, len(lines)):
        if re.match(r"^##\s+", lines[i]):
            end = i
            break
    return lines[start:end]


def _list_value(lines, label):
    pattern = re.compile(r"^\s*[-+*]\s*" + re.escape(label) + r"\s*`([^`]*)`\s*$")
    found = [(i, match.group(1)) for i, line in enumerate(lines) if (match := pattern.match(line))]
    if len(found) != 1:
        raise ValueError("list-item")
    return found[0]


def _nonnegative_decimal(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+", value) is None:
        raise ValueError("decimal")
    return int(value)


def _json_blocks(lines, after=-1):
    blocks = []
    i = max(0, after + 1)
    opening = re.compile(r"^\s*```json\s*$")
    closing = re.compile(r"^\s*```\s*$")
    while i < len(lines):
        if opening.match(lines[i]):
            begin = i
            i += 1
            content = []
            while i < len(lines) and not closing.match(lines[i]):
                content.append(lines[i])
                i += 1
            if i == len(lines):
                raise ValueError("unterminated-fence")
            try:
                value = json.loads("\n".join(content), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
            except Exception as exc:
                raise ValueError("json") from exc
            blocks.append((begin, value))
        i += 1
    return blocks


def _one_json_block(lines, after=-1):
    blocks = _json_blocks(lines, after)
    if len(blocks) != 1:
        raise ValueError("json-fence")
    return blocks[0][1]


def _string_array(value):
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise ValueError("string-array")
    if value != sorted(value) or len(set(value)) != len(value):
        raise ValueError("string-array-order")
    return value


def _expected_from_upstream(input_path):
    # read_graphml and all graph operations below are NetworkX public semantics.
    graph = nx.read_graphml(input_path)
    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()

    if graph.is_directed():
        raw_components = nx.weakly_connected_components(graph)
    else:
        raw_components = nx.connected_components(graph)
    components = [sorted(str(node) for node in component) for component in raw_components]
    components.sort(key=lambda members: (-len(members), members))

    degree_pairs = list(graph.degree())
    if degree_pairs:
        maximum_degree = max(degree for _, degree in degree_pairs)
        key_nodes = sorted(str(node) for node, degree in degree_pairs if degree == maximum_degree)
    else:
        maximum_degree = None
        key_nodes = []

    isolated_nodes = sorted(str(node) for node in nx.isolates(graph))
    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "components": components,
        "maximum_degree": maximum_degree,
        "key_nodes": key_nodes,
        "isolated_nodes": isolated_nodes,
    }


def _parse_components(value):
    if not isinstance(value, list):
        raise ValueError("components-array")
    parsed = []
    ids = set()
    for record in value:
        if not isinstance(record, dict):
            raise ValueError("component-record")
        if not all(key in record for key in ("id", "size", "nodes")):
            raise ValueError("component-fields")
        ident = record["id"]
        size = record["size"]
        if isinstance(ident, bool) or not isinstance(ident, int) or ident < 0:
            raise ValueError("component-id")
        if ident in ids:
            raise ValueError("component-id")
        ids.add(ident)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("component-size")
        nodes = _string_array(record["nodes"])
        if len(nodes) != size:
            raise ValueError("component-size")
        parsed.append((size, nodes))
    if parsed != sorted(parsed, key=lambda item: (-item[0], item[1])):
        raise ValueError("component-order")
    return parsed


def verify(input_path: Path, artifact_path: Path) -> dict:
    # Evaluate the complete NetworkX-derived expectation before examining an
    # artifact rejection, so each advertised computation remains observable.
    try:
        expected = _expected_from_upstream(input_path)
    except Exception:
        return _result(False, ["UPSTREAM_EVALUATION_FAILURE"], [])

    try:
        text = artifact_path.read_text(encoding="utf-8")
        if not text.strip() or text.lstrip().startswith("{") or text.lstrip().startswith("["):
            raise ValueError("representation")
        lines = text.splitlines()
        scale = _section(lines, "规模")
        groups = _section(lines, "分组")
        key_section = _section(lines, "关键节点")
        isolated_section = _section(lines, "落单节点")

        _, node_text = _list_value(scale, "节点数：")
        _, edge_text = _list_value(scale, "边数：")
        observed_nodes = _nonnegative_decimal(node_text)
        observed_edges = _nonnegative_decimal(edge_text)

        _, component_count_text = _list_value(groups, "分量数：")
        observed_component_count = _nonnegative_decimal(component_count_text)
        observed_components = _parse_components(_one_json_block(groups))

        maximum_index, maximum_text = _list_value(key_section, "最大度：")
        if maximum_text == "null":
            observed_maximum = None
        else:
            observed_maximum = _nonnegative_decimal(maximum_text)
        observed_keys = _string_array(_one_json_block(key_section, maximum_index))
        observed_isolated = _string_array(_one_json_block(isolated_section))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return _result(False, ["ARTIFACT_PROTOCOL_INVALID"], _COMMITMENTS)

    codes = []
    if observed_nodes != expected["node_count"] or observed_edges != expected["edge_count"]:
        codes.append("GRAPH_SIZE_MISMATCH")

    expected_component_records = [(len(nodes), nodes) for nodes in expected["components"]]
    if observed_component_count != len(expected_component_records) or observed_components != expected_component_records:
        codes.append("COMPONENT_GROUPS_MISMATCH")

    if observed_maximum != expected["maximum_degree"] or observed_keys != expected["key_nodes"]:
        codes.append("KEY_NODES_MISMATCH")

    if observed_isolated != expected["isolated_nodes"]:
        codes.append("ISOLATED_NODES_MISMATCH")

    return _result(not codes, codes, _COMMITMENTS)
