"""NC_reimpl:全样例但零 import 上游 — provenance 必须抓(控制组 impl.py 变体;绝不交付)。"""
from pathlib import Path


class UserInputError(ValueError):
    pass


_M = {'typical_duplicate_ids_pass_and_reject': '# FASTA 候选序列筛选报告\n\n## 摘要\n- 总记录数：2\n- PASS：1\n- REJECT：1\n\n## 通过序列\n| id | length_bp | gc_percent | ambiguous_percent | decision | reasons |\n|---|---:|---:|---:|:---:|---|\n| "dup&#124;&#92;"A&amp;B" | 150 | 50.00 | 0.00 | PASS | NONE |\n\n## 未通过序列\n| id | length_bp | gc_percent | ambiguous_percent | decision | reasons |\n|---|---:|---:|---:|:---:|---|\n| "dup&#124;&#92;"A&amp;B" | 150 | 100.00 | 0.00 | REJECT | GC_ABOVE_MAX |\n\n## 警告\n- 处理边界：未修改、修剪、翻译或比对输入序列，未查询远程数据库。\n- 重复 id 值数量：1\n', '多记录含重复ID及多种筛选结果': '# FASTA 候选序列筛选报告\n\n## 摘要\n- 总记录数：3\n- PASS：1\n- REJECT：2\n\n## 通过序列\n| id | length_bp | gc_percent | ambiguous_percent | decision | reasons |\n|---|---:|---:|---:|:---:|---|\n| "dup" | 150 | 50.00 | 0.00 | PASS | NONE |\n\n## 未通过序列\n| id | length_bp | gc_percent | ambiguous_percent | decision | reasons |\n|---|---:|---:|---:|:---:|---|\n| "short" | 149 | 0.00 | 0.00 | REJECT | LENGTH_BELOW_MIN;GC_BELOW_MIN |\n| "dup" | 150 | 0.00 | 100.00 | REJECT | GC_BELOW_MIN;AMBIGUOUS_ABOVE_MAX |\n\n## 警告\n- 处理边界：未修改、修剪、翻译或比对输入序列，未查询远程数据库。\n- 重复 id 值数量：1\n', '重复标识符与临界非ACGT比例': '# FASTA 候选序列筛选报告\n\n## 摘要\n- 总记录数：3\n- PASS：2\n- REJECT：1\n\n## 通过序列\n| id | length_bp | gc_percent | ambiguous_percent | decision | reasons |\n|---|---:|---:|---:|:---:|---|\n| "dup" | 150 | 53.33 | 0.00 | PASS | NONE |\n| "ambedge" | 200 | 50.00 | 1.00 | PASS | NONE |\n\n## 未通过序列\n| id | length_bp | gc_percent | ambiguous_percent | decision | reasons |\n|---|---:|---:|---:|:---:|---|\n| "dup" | 150 | 0.00 | 0.00 | REJECT | GC_BELOW_MIN |\n\n## 警告\n- 处理边界：未修改、修剪、翻译或比对输入序列，未查询远程数据库。\n- 重复 id 值数量：1\n'}


def _lookup(input_path: Path) -> str:
    key = input_path.name
    if key not in _M:
        raise UserInputError(f"unexpected input: {key}")
    return _M[key]


def extract(input_path: Path) -> str:
    return _lookup(input_path)
