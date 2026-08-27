"""套件级防线。

LITELLM_MODE=PRODUCTION:litellm 在 DEV 模式(默认)`import litellm`
时会把 **CWD 的 .env 整个 load_dotenv 进 os.environ**——本仓 .env 存着
真 API key 与 REPOPROOF_* 连接配置。后果有二:(1) 任何在模块层 import
litellm 的测试会把真实连接池漏进所有后续测试的 env(实测:UI 池测试
因此看见 .env 里的 gpt 模型);(2) 秘密静默入环境,违反 Gate 4A
"官方运行只读宿主显式 env"的配置来源纪律。生产侧同一防线钉在
host_guided 的 litellm import 前(setdefault,可被显式覆盖)。
"""

import os
from pathlib import Path

os.environ.setdefault("LITELLM_MODE", "PRODUCTION")


def isolate_protected_dirs(monkeypatch, target: Path | str | None = None) -> list[str]:
    """把保护集合换成**可控主体**(或清空),并当场自检隔离是否真的成立。

    为什么要有这个函数(2026-08-27 实录):保护集合原本只有
    `DEFAULT_PROTECTED` 一个来源,于是各测试各写一句
    `monkeypatch.setattr(host_guard, "DEFAULT_PROTECTED", ())` 就够了。
    2026-08-26 加入**结构性发现**(本仓 + 兄弟 git 仓,动态计算)之后,
    那一句只按住了常量,结构性那一路照样把真实邻仓拉回指纹扫描 ——
    **五个测试文件的隔离同时悄悄失效**,表现为:全量偶红(冒烟链的红绿
    取决于"隔壁项目此刻在不在写盘")+ 每条 E2E 白扫几十秒真目录。

    夹具失效不会有人喊,这是它能潜伏一整周的原因。所以本函数在收尾处
    **断言自己**:实际生效的保护集必须恰好等于预期主体。将来再多一个
    来源,这里当场红,而不是把红分摊到几十条不相干的测试上。
    """
    from repoproof.harness import host_guard

    monkeypatch.setattr(host_guard, "structural_protected", lambda: [])
    monkeypatch.setattr(host_guard, "DEFAULT_PROTECTED", ())
    if target is None:
        monkeypatch.delenv("REPOPROOF_PROTECTED_DIRS", raising=False)
        expected: list[str] = []
    else:
        monkeypatch.setenv("REPOPROOF_PROTECTED_DIRS", str(target))
        expected = [os.path.realpath(str(target)).rstrip("/")]

    actual = host_guard.protected_dirs()
    assert actual == expected, (
        f"保护集隔离失效:期望 {expected},实际 {actual} —— "
        "多半是 protected_dirs() 新增了来源而本夹具没跟上(按住它,"
        "别让真实目录重新进指纹扫描)")
    return actual
