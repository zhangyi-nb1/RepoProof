"""从发次的会话里取出交付 —— **harness 侧**,在会话销毁之前。

取件失败要**明说取件失败**,不能含糊成"采纳不成立":前者是 harness 的问题
(路径变了、作业没落盘),后者是被测方的问题,两者修法完全不同。

2026-08-15 审查 S4:原实现的 try 只包 `json.loads`,而 `doc.get("facts")`
与那个 for 循环在 try **之外** —— 顶层是 JSON 数组、或 `"facts": 3`,就会
抛 TypeError/AttributeError,被上游的裸 except 吞成 None,于是**被测方交了
个形状不对的工件,报出来却是"取件失败(harness 的问题)"**。归因反了。
现在每份文件整段进 try,坏文件单独计数并报出来。
"""
from __future__ import annotations

import json
from pathlib import Path

JOBS_DIRNAME = "page_facts_jobs"


class DeliveryExtractionError(RuntimeError):
    """交付目录在、但里面的东西**全都读不出来**。

    这与"目录不存在"分开报:目录不存在多半是没写到约定落点(契约 R8 已
    明说),而全都读不出来说明写了但形状不对 —— 后者要归被测方。
    """


def extract(host_dir: Path) -> list[dict] | None:
    """返回 [{"request_nonce":..., "facts":...}, ...];目录不在返回 None。

    坏文件不静默跳过:全坏且零产出时抛 `DeliveryExtractionError`,由调用方
    归成被测方的形状问题,而不是 harness 取不到东西。
    """
    d = Path(host_dir) / JOBS_DIRNAME
    if not d.is_dir():
        return None

    out: list[dict] = []
    bad: list[str] = []
    files = sorted(d.glob("*.json"))
    for f in files:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
            for item in doc.get("facts") or []:
                if "request_nonce" in item:
                    out.append({"request_nonce": item["request_nonce"],
                                "facts": item.get("facts", "")})
        except Exception as e:                                   # noqa: BLE001
            bad.append(f"{f.name}: {type(e).__name__}: {e}")

    if not out and bad:
        raise DeliveryExtractionError(
            f"{len(bad)}/{len(files)} 份工件读不出,零产出 —— 交付形状不合规"
            f"(契约 R8 写明了 schema)。首条:{bad[0][:200]}")
    return out or None
