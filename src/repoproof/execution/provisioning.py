"""Runtime provisioning —— **一次性联网构建**,与 benchmark 执行严格分离。

用户 2026-08-15 授权:允许 harness 侧做一次联网安装,但必须定义成
"runtime provisioning / build 阶段的一次性联网",**不是**给 agent 或正式
benchmark execution 放开网络。

这条边界不能靠口头保证,得靠结构。三层:

1. **阶段隔离**。联网只发生在 `provision`(构建期),`execute`(发次期)
   一个字节都不动。两个阶段跑在不同的入口、不同的函数、不同的时机 ——
   provision 由人手动触发一次,execute 由 host-run 触发无数次。
2. **产物封存**。provision 的输出是一份**只读的、带清单与摘要的 runtime**
   (`RuntimeManifest`),execute 只消费它,不再联网、也不再解析依赖。
   封存之后网络关掉,零模型 smoke 必须仍能跑通 —— 跑不通说明有东西还在
   偷偷联网。
3. **agent 权限不变**。agent 的会话环境仍然 `PIP_NO_INDEX` + 冻结
   wheelhouse,策略拒绝表一个字不改。**provision 的产物 agent 也够不着**
   —— 它住在 harness 独占目录,和 conformance fixture 一样受拓扑核验。

失效方向刻意做成朝紧:

- 没有 manifest → execute 拒开(不假设"大概装好了");
- manifest 与实际产物摘要对不上 → 拒开(有人动过封存件);
- `allow_network=True` 只在 provision 的签名里存在,execute 的签名里**根本
  没有这个参数** —— 想在发次期联网,得先改 API 形状,改不动就是改不动。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROVISION_MARKER = "runtime_manifest.json"

# provision 期允许联网的**唯一**理由。写成常量是为了让 grep 找得到所有
# 放行点 —— 一个"什么时候允许联网"的问题应该有一个答案,不是散在各处。
PROVISION_PHASE = "provision"
EXECUTE_PHASE = "execute"


class ProvisioningError(RuntimeError):
    pass


@dataclass(frozen=True)
class PinnedSource:
    """钉死的上游来源。**版本与 commit 都要**,少一个都不叫钉死。

    `distribution` + `version` 决定装什么;`resolved_commit` 决定那个版本
    到底是哪份字节(同一个版本号在 PyPI 上被重新上传过的事发生过)。
    """

    distribution: str
    version: str
    resolved_commit: str = ""
    url: str = ""


@dataclass
class RuntimeManifest:
    """封存件的清单 —— execute 期唯一认的东西。

    `artifact_digest` 是产物树的内容摘要:execute 前重算一遍,对不上就拒开。
    它挡的不是攻击者,是**我们自己**:装完之后有人手动动了一下、或者跑了别的
    脚本顺手改了,那份 runtime 就不再是被验过的那份了。
    """

    profile_id: str
    pinned: list[PinnedSource]
    root: str
    artifact_digest: str
    python_executable: str
    provisioned_at: str
    provisioner_version: int = 1
    extras: dict = field(default_factory=dict)

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, ensure_ascii=False, sort_keys=True, indent=2) + "\n"

    @staticmethod
    def load(root: Path) -> RuntimeManifest:
        p = Path(root) / PROVISION_MARKER
        if not p.is_file():
            raise ProvisioningError(
                f"没有 runtime 清单:{p} —— 先跑 provision。**不假设"
                "'大概装好了'**:没清单就没有可核对的封存件,后面每一句"
                "'用的是钉版上游'都无从复核")
        d = json.loads(p.read_text(encoding="utf-8"))
        d["pinned"] = [PinnedSource(**x) for x in d.get("pinned", [])]
        return RuntimeManifest(**d)


def digest_tree(root: Path, *, skip: tuple[str, ...] = ("__pycache__", ".git")) -> str:
    """产物树的内容摘要 —— 路径与字节都算进去。

    刻意不用 mtime/size:那两样太容易在无意间变化(复制、解压、touch),
    会把"内容没变"误报成"被动过"。误报会训练人去忽略这道检查,那比没有
    这道检查更坏。
    """
    h = hashlib.sha256()
    root = Path(root)
    for f in sorted(root.rglob("*")):
        if not f.is_file() or any(s in f.parts for s in skip):
            continue
        if f.name == PROVISION_MARKER:          # 清单本身不算进自己的摘要
            continue
        h.update(f.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(f.read_bytes())
    return f"sha256:{h.hexdigest()}"


def provision(*, profile_id: str, root: Path, pinned: list[PinnedSource],
              steps: list[list[str]], allow_network: bool,
              env: dict[str, str] | None = None) -> RuntimeManifest:
    """构建期。**这是全仓唯一一个接受 `allow_network` 的函数。**

    `steps` 是要跑的 argv 列表(逐条固定 argv,不走 shell)。调用方必须显式
    传 `allow_network=True`,否则拒跑 —— 让"这一步会联网"变成调用点上肉眼
    可见的一个词,而不是藏在某个默认值里。
    """
    if not allow_network:
        raise ProvisioningError(
            "provision 就是联网构建;调用方必须显式写 allow_network=True。"
            "做成必填是为了让'这一步会联网'在调用点上肉眼可见 —— 藏在默认值"
            "里的联网,和没有边界没有区别")
    if not pinned:
        raise ProvisioningError("没有钉死任何上游 —— 不钉版的 runtime 无法复现,"
                                "封存它没有意义")
    for s in pinned:
        if not s.version:
            raise ProvisioningError(f"{s.distribution} 没有钉版本;不猜")

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    e = {**os.environ, **(env or {})}
    # provision 期**解除**离线钉;这是本函数存在的全部理由,也是它与
    # execute 期的唯一区别。
    for k in ("PIP_NO_INDEX", "PIP_FIND_LINKS"):
        e.pop(k, None)
    e["REPOPROOF_PHASE"] = PROVISION_PHASE

    log: list[dict] = []
    for argv in steps:
        r = subprocess.run(argv, capture_output=True, text=True,     # noqa: S603
                           cwd=str(root), env=e, check=False)
        log.append({"argv": argv, "rc": r.returncode,
                    "tail": (r.stdout + r.stderr)[-800:]})
        if r.returncode != 0:
            raise ProvisioningError(
                f"provision 步骤失败(rc={r.returncode}):{argv}\n"
                + (r.stdout + r.stderr)[-1500:])

    m = RuntimeManifest(
        profile_id=profile_id, pinned=list(pinned), root=str(root),
        artifact_digest=digest_tree(root),
        python_executable=str(root / ".venv" / "bin" / "python"),
        provisioned_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        extras={"steps": log})
    (root / PROVISION_MARKER).write_text(m.to_json(), encoding="utf-8")
    return m


def verify_sealed(root: Path) -> tuple[bool, str]:
    """execute 期的准入检查。**签名里没有 `allow_network`,想联网得先改 API。**

    返回 (可用, 说明)。两条都不过就拒开:清单在不在、封存件动没动过。
    """
    try:
        m = RuntimeManifest.load(root)
    except ProvisioningError as e:
        return False, str(e)
    now = digest_tree(root)
    if now != m.artifact_digest:
        return False, (f"封存件被动过:清单记 {m.artifact_digest[:22]}…,"
                       f"现算 {now[:22]}… —— 那就不再是被验过的那份 runtime。"
                       "重跑 provision,或把动过的东西恢复")
    return True, (f"封存件完好({len(m.pinned)} 个钉版上游,"
                  f"provision 于 {m.provisioned_at})")
