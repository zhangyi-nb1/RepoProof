"""发次期的 sidecar 会话 —— 把 A1 接进 `host-run`。

**为什么单独一个模块而不是写进 `host_guided.py`**:那个文件被几十条变异按
逐字节的 `old` 串守着,改动面越大,STALE 越多,而 STALE 会让整批变异判成
不可归因。把逻辑放这里,主流程只需两处极小的插入 —— 起会话、收结论。

它管三件事,与 agent 的权限**完全无关**:

1. **起 harness 侧基础设施**:本地网页 fixture(离线站点)+ 上游 sidecar。
   两者都跑在 harness 进程里,agent 只拿到端点与令牌。
2. **算 U3 的分母**:待抽取项由 harness 生成(nonce 现摇),**不读 agent
   任何自述**。分母若来自被测方,"象征性调一次"永远抓不住。
3. **发次结束后独立核验**:密钥与台账都在这里,agent 会话里没有。

台账落 `runs/<run_id>/`(主目录硬护栏拒绝表内,agent 写不进);密钥只在本
进程内存里活到验完为止,**不落盘、不进 bundle**。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repoproof.execution.runtime_profiles import RuntimeProfile
from repoproof.execution.upstream_sidecar import SidecarHandle, start_sidecar
from repoproof.receipts.ledger import ledger_path_for, new_key, new_nonce
from repoproof.receipts.model import CANON_JSON, digest_of


@dataclass
class SidecarSession:
    """一次发次期间的 sidecar 基础设施与它的验证材料。"""

    profile: RuntimeProfile
    ledger: Path
    key: bytes
    run_nonce: str
    run_id: str
    handle: SidecarHandle
    fixture_url: str
    items: list[dict]
    _web: Any = None
    extra_env: dict[str, str] = field(default_factory=dict)

    # ---------------------------------------------------------------- agent 侧
    def agent_env(self) -> dict[str, str]:
        """交给 agent 会话的**全部**东西。

        端点、令牌、要调的符号、fixture 基址、以及它该处理的那批项的 nonce。
        **没有**台账路径、**没有**密钥 —— 那两样一旦漏出去,U1 的全部意义
        就没了。`SidecarHandle.agent_env()` 已经保证不漏,这里只在它之上
        追加任务需要的几项。
        """
        env = dict(self.handle.agent_env())
        env["REPOPROOF_SIDECAR_SYMBOL"] = self.profile.default_symbol
        env["REPOPROOF_FIXTURE_URL"] = self.fixture_url
        env["REPOPROOF_ITEM_NONCES"] = ",".join(i["request_nonce"] for i in self.items)
        env.update(self.extra_env)
        return env

    # ---------------------------------------------------------------- 验证
    def expected_units(self) -> list[dict]:
        """U3 的分母 —— 由 harness 按**它自己生成的**那批项算。"""
        return [{"request_nonce": i["request_nonce"],
                 "input_digest": digest_of({"text": i["url"]}, canon=CANON_JSON)}
                for i in self.items]

    def receipts_written(self) -> int:
        return self.handle.receipts_written()

    def shutdown(self) -> None:
        try:
            self.handle.shutdown()
        finally:
            if self._web is not None:
                self._web.shutdown()


def _fixture_server(nonce: str):
    """本地离线站点。按路径加载 —— `benchmarks/` 不是包,不能 import。"""
    import importlib.util

    repo = Path(__file__).resolve().parents[3]
    f = repo / "benchmarks" / "v2" / "web_fixture" / "server.py"
    spec = importlib.util.spec_from_file_location("rp_web_fixture", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.serve(nonce)


def _load_profile_module(profile_id: str):
    """profile 的能力面定义随它的使用者放在 `benchmarks/` 下,按路径加载。

    **不按模块名 import**:多个 suite 都有 `profile.py`,裸 import 会被
    `sys.modules` 里先到的赢走(实测踩过:整张拓扑表报的是别的 suite 的)。
    """
    import importlib.util
    import sys

    repo = Path(__file__).resolve().parents[3]
    known = {"rt-sidecar-browser-v1":
             repo / "benchmarks" / "v2" / "sidecar_browser" / "profile.py"}
    f = known.get(profile_id)
    if f is None or not f.is_file():
        raise ValueError(f"没有 {profile_id!r} 的能力面定义 —— 不猜。已登记:{sorted(known)}")
    name = f"rp_profile_{profile_id.replace('-', '_')}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, f)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def start(*, profile: RuntimeProfile, run_id: str, run_dir: Path,
          item_count: int = 2) -> SidecarSession:
    """起一次发次的 sidecar 基础设施。

    `item_count` 至少 2:一项也能跑,但**抓不住"一次调用充抵所有项"** ——
    U3 的分母必须 ≥2 才携带信息。
    """
    if item_count < 2:
        raise ValueError("待抽取项至少 2 个 —— 只有 1 项时 U3 抓不住'充数'")

    mod = _load_profile_module(profile.id)
    ok, why = mod.available()
    if not ok:
        raise RuntimeError(f"{profile.id} 的封存 runtime 不可用:{why}")

    key, nonce = new_key(), new_nonce()
    ledger = ledger_path_for(run_dir)
    web = _fixture_server(f"run-{run_id[:24]}")
    base = f"http://127.0.0.1:{web.server_address[1]}/"
    # 项的 nonce **现摇**:写死的话,上一次 run 的回执拿来就能对上
    items = [{"request_nonce": f"item-{i + 1}-{os.urandom(4).hex()}"}
             for i in range(item_count)]
    for it in items:
        it["url"] = f"{base}?item={it['request_nonce']}"

    handle = start_sidecar(spec=mod.SPEC, ledger_path=ledger, key=key,
                           run_id=run_id, run_nonce=nonce,
                           token="tok-" + nonce[:16], profile_id=profile.id,
                           default_symbol=mod.SYMBOL)
    return SidecarSession(profile=profile, ledger=ledger, key=key, run_nonce=nonce,
                          run_id=run_id, handle=handle, fixture_url=base,
                          items=items, _web=web)


def verify(session: SidecarSession, *, task_id: str, delivery: list[dict]) -> dict:
    """发次结束后的独立核验。返回可直接进 report 的字典。

    `delivery` 由任务侧的取件器提供(从 agent 交付的工件里读出来)。
    读不出交付**不等于**验过 —— 那种情况必须判不过,理由写清楚是"取不到
    交付",而不是含糊的 U4 红:两者的修法完全不同。
    """
    import importlib.util

    repo = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "rp_verify_task_receipts", repo / "scripts" / "verify_task_receipts.py")
    vtr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vtr)

    if delivery is None:
        return {"ok": False, "reason": "NO_DELIVERY_EXTRACTED",
                "detail": "取不到 agent 的交付 —— 无从判断采纳。这不是 U4 红,"
                          "是取件失败,两者修法不同"}

    mod = _load_profile_module(session.profile.id)
    ident = mod.SPEC.identity()
    v = vtr.verify(ledger=session.ledger, key=session.key, run_id=session.run_id,
                   run_nonce=session.run_nonce, items=session.items,
                   delivery=delivery, receipts_written=session.receipts_written(),
                   required_symbols=set(session.profile.required_symbols),
                   required_upstream={"distribution": ident.distribution,
                                      "import_module": ident.import_module,
                                      "artifact_hash": ident.artifact_hash})
    return {"ok": v.ok, "reason": "" if v.ok else "RECEIPT_VERIFICATION_FAILED",
            **v.as_dict()}
