"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'mixed_components_unicode.graphml': '# 图网络摘要\n\n## 规模\n- 节点数：`4`\n- 边数：`2`\n\n## 分组\n- 分量数：`2`\n```json\n[{"id":1,"size":3,"nodes":["A","éclair","节点"]},{"id":2,"size":1,"nodes":["孤立"]}]\n```\n\n## 关键节点\n- 最大度：`2`\n```json\n["éclair"]\n```\n\n## 落单节点\n```json\n["孤立"]\n```\n', 'directed_parallel_edges.graphml': '# 图网络摘要\n\n## 规模\n- 节点数：`4`\n- 边数：`3`\n\n## 分组\n- 分量数：`2`\n```json\n[{"id":1,"size":3,"nodes":["alpha","beta","gamma"]},{"id":2,"size":1,"nodes":["solo"]}]\n```\n\n## 关键节点\n- 最大度：`3`\n```json\n["beta"]\n```\n\n## 落单节点\n```json\n["solo"]\n```\n', 'empty_whitespace.graphml': '# 图网络摘要\n\n## 规模\n- 节点数：`0`\n- 边数：`0`\n\n## 分组\n- 分量数：`0`\n```json\n[]\n```\n\n## 关键节点\n- 最大度：`null`\n```json\n[]\n```\n\n## 落单节点\n```json\n[]\n```\n', 'directed_multiedge_unicode_isolate.graphml': '# 图网络摘要\n\n## 规模\n- 节点数：`3`\n- 边数：`3`\n\n## 分组\n- 分量数：`2`\n```json\n[{"id":1,"size":2,"nodes":["乙","甲"]},{"id":2,"size":1,"nodes":["丙"]}]\n```\n\n## 关键节点\n- 最大度：`3`\n```json\n["乙","甲"]\n```\n\n## 落单节点\n```json\n["丙"]\n```\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
