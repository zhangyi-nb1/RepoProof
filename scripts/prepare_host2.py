#!/usr/bin/env python3
"""从封存件造出 H2 的宿主副本 —— **挖空 + 剥离 + 自证不漏**。

## 为什么这一步单独成脚本、而且带自证

设计评审给这道题的诚实尺寸是"10 个 held-out node、2 项微技能、约 1–2 bit"。
**1–2 bit 的闸门经不起任何一条泄漏** —— 答案只要还能从副本里捞出来,整道题
的信息量当场归零,而所有数字看起来照常。

评审当场点了三条,全部实测坐实:

1. **`.git` 还在** —— `git show HEAD:src/flask_smorest/spec/plugins.py` 一行拿到原件。
2. **`.pth` 指回原仓** —— editable 装法在 site-packages 留了一行绝对路径,
   指向**未挖空**的那棵树。
3. **交付边界没写进契约** —— 用未言明的要求判人(B6/B7/B10 那条 blocking 的病)。

第 3 条归契约,前两条归这里。但真正的教训不是"记得删这两样",而是
**删完必须证明捞不出来** —— 所以本脚本的主产物是那份泄漏扫描报告,
不是那棵树。

## 挖空,不是改写(F1 严口径的分界线)

只把 seam 里的符号**掏空成 `raise NotImplementedError`**,一个字的新语义
都不加。加语义(ENRICHED)的话,上游那 554 条此刻实际在检验"你有没有猜对
**我们新加的**东西",而 `oracle_authorship` 那道闸门对此完全无感 ——
它管的是测试文本谁写的。第二道闸门 `host_modification_mode` 就是为这个立的。
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SEALED = Path("~/RepoProofBench/host2-flask-smorest").expanduser()
# **原件不在 bench 根下。** 2026-08-15 对抗性搜捕:原件、venv、pristine 原本
# 与交付树同级,而 bench 白名单的粒度只到顶层目录名 —— 整个目录一张票放行,
# 一条 `cat .pth` 就把 12 个函数体逐字节取回。与 LESSONS #29 完全同型
# (`offerclaw-transaction-stack/` 内含三份 PASS 解被整个放行)。
ARCHIVE = Path("~/RepoProofArchive/host2").expanduser()
SRC = ARCHIVE / "repo"
HOST = SEALED / "host"
SEAM = "src/flask_smorest/spec/plugins.py"

# 副本里**不许有**的东西。每一条都对应一条实测过的取回路径,不是"看着危险"。
STRIP_DIRS = {
    ".git",          # `git show HEAD:<seam>` 一行拿到原件
    ".github",       # CI 配置会引用测试布局
    "docs",          # docs/openapi.rst:206-224 把 register_converter 的用法与
                     # `def xxx2paramschema(converter) -> dict` 的函数形状写明了
    "tests",         # 它是隐藏 oracle —— 留在副本里等于把判卷发给考生
    "__pycache__",   # **原件的字节码**:挖空前编译过一次就够了
    ".pytest_cache",
    ".ruff_cache",
    "htmlcov",
}
STRIP_SUFFIXES = (".pyc", ".pyo", ".orig", ".bak", ".rej", ".pth", ".egg-link")
STRIP_FILES = {".pre-commit-config.yaml", ".readthedocs.yaml", "CHANGELOG.rst"}


def _carve(src_text: str) -> tuple[str, list[str]]:
    """把 seam 里每个函数/方法的**函数体**换成 raise,签名与 docstring 保留。

    保留签名是有意的:任务要的是"把这些实现出来",不是"猜出有哪些函数"。
    连名字都藏起来的话,判的就变成了"能不能猜到我们挖了什么",那是另一道题
    (而且是道坏题 —— 用未言明的要求判人)。

    **docstring 也保留**:它是上游自己写的,属于原件的公开面。删掉它等于
    我们在改写宿主,那正是 F1 那条分界线不许做的事。
    """
    tree = ast.parse(src_text)
    lines = src_text.splitlines()
    carved: list[str] = []
    spans: list[tuple[int, int, int]] = []      # (起, 止, 缩进)

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        body = node.body
        # 跳过 docstring
        i = 0
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            i = 1
        if i >= len(body):
            continue                              # 只有 docstring,没什么可挖
        start = body[i].lineno - 1
        end = max(getattr(n, "end_lineno", n.lineno) for n in body[i:])
        spans.append((start, end, body[i].col_offset))
        carved.append(node.name)

    # 嵌套 def:外层函数体本来就包含内层,替换外层即已挖掉内层;但给内层
    # 单独留 span 的话,reverse 替换后外层的**陈旧坐标**会把后移上来的
    # 兄弟方法整个吞掉,连签名都不剩(2026-08-16 彩排当场抓到:pagination
    # 五个兄弟方法消失;plugins 没有这种形状,H1 从未红过)。
    # 只保留不被任何其它 span 包含的最外层 span。
    spans = [s for s in spans
             if not any(o != s and o[0] <= s[0] and s[1] <= o[1] for o in spans)]
    for start, end, indent in sorted(spans, reverse=True):
        lines[start:end] = [" " * indent + "raise NotImplementedError"]
    out = "\n".join(lines) + "\n"

    # 挖空**自己制造**的残留:函数体没了,它用的 import 就成了孤儿。
    # 上游是 lint-clean 的(pyproject 的 ruff select 含 "F"),所以"一条没人
    # 用的 import"在这棵树里是**结构性异常** —— 等于指着某个被挖的函数说
    # "这里要用到 Mapping"。这不是上游的公开面,是我们的手印,必须抹掉。
    removed: list[str] = []
    tree2 = ast.parse(out)
    used = {n.id for n in ast.walk(tree2) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree2) if isinstance(n, ast.Attribute)} | {
        a.value.id for a in ast.walk(tree2)
        if isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name)}
    drop_lines: set[int] = set()
    for node in ast.walk(tree2):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        alive = [a for a in node.names if (a.asname or a.name.split(".")[0]) in used]
        if not alive:
            drop_lines.add(node.lineno - 1)
            removed += [a.asname or a.name for a in node.names]
    if drop_lines:
        kept = [ln for i, ln in enumerate(out.splitlines()) if i not in drop_lines]
        out = "\n".join(kept) + "\n"
    return out, sorted(carved), removed


def _digest_tree(root: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(root.rglob("*")):
        if f.is_file():
            h.update(f.relative_to(root).as_posix().encode())
            h.update(f.read_bytes())
    return f"sha256:{h.hexdigest()}"


def build() -> dict:
    if HOST.exists():
        shutil.rmtree(HOST)

    def _ignore(dirpath, names):
        skip = {n for n in names if n in STRIP_DIRS or n in STRIP_FILES
                or n.endswith(STRIP_SUFFIXES)}
        return skip

    shutil.copytree(SRC, HOST, ignore=_ignore)

    original = (SRC / SEAM).read_text(encoding="utf-8")
    carved_text, carved_symbols, removed_imports = _carve(original)
    (HOST / SEAM).write_text(carved_text, encoding="utf-8")
    return {"carved_symbols": carved_symbols,
            "carve_removed_imports": removed_imports,
            "original_digest": hashlib.sha256(original.encode()).hexdigest()[:16],
            "carved_digest": hashlib.sha256(carved_text.encode()).hexdigest()[:16]}


# ------------------------------------------------------------------ 泄漏扫描
def _answer_fingerprints(original: str) -> list[tuple[str, str]]:
    """答案的指纹 —— 拿它去副本里搜。

    **只取函数体,不取签名与 docstring。** 签名是**故意保留**的(任务要的是
    "把这些实现出来",不是"猜出有哪些函数");docstring 是上游自己写的,
    删掉它等于我们改写宿主,那正是 F1 那条分界线不许做的事。拿它们当指纹
    只会报出一堆"我们自己留下的东西",把真信号淹掉 —— 头一版就这样,
    唯一那条命中是 `Api.register_converter` 的签名,而它是上游的公开 API。

    整份文件也不能当指纹:整份一搜必然搜不到(刚挖空过),那是个好看的假绿。
    """
    out: list[tuple[str, str]] = []
    tree = ast.parse(original)
    lines = original.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        body = node.body
        i = 1 if (body and isinstance(body[0], ast.Expr)
                  and isinstance(body[0].value, ast.Constant)
                  and isinstance(body[0].value.value, str)) else 0
        for stmt in body[i:]:
            for ln in lines[stmt.lineno - 1:
                            getattr(stmt, "end_lineno", stmt.lineno)]:
                s = ln.strip()
                # 太短的行(`return {}`、`pass`)到处都是,报出来只有噪声
                if len(s) >= 24 and not s.startswith("#"):
                    out.append((f"{node.name}:{s[:40]}", re.escape(s)))

    # **只留原仓 seam 之外没出现过的行。**
    #
    # 判据不能是"这行长不长",得是"这行是不是**只有答案里才有**"。
    # 头两版栽在这上面:`if self.openapi_version.major < 3:` 这种通用惯用行
    # 在原仓好几处都有,报出来纯噪声,而真信号会被淹在里面。
    #
    # 自校准的好处:换个 seam、换个宿主,门槛自己跟着变,不用我手调。
    elsewhere = []
    for f in SRC.rglob("*.py"):
        rel = f.relative_to(SRC).as_posix()
        if rel == SEAM or "/.git/" in f.as_posix():
            continue
        elsewhere.append(f.read_text(encoding="utf-8", errors="replace"))
    blob = "\n".join(elsewhere)
    return [(n, pat) for n, pat in out if not re.search(pat, blob)]


# **公开线索**:留在副本里、确实降低难度、但**不许删**的东西。
# 删了就是改写宿主(F1 的 ENRICHED 反面同样成立:剥掉上游自己的公开文档,
# 副本就不再是那个宿主了)。它们不是泄漏,但必须**如实计进诚实尺寸** ——
# 不写出来的话,"10 个 node、1–2 bit"这句话就是虚的。
DISCLOSED_HINTS = [
    {"where": "src/flask_smorest/spec/__init__.py::Api.register_converter",
     "what": "docstring 里有一段完整的示例,逐字给出了 converter→paramschema "
             "函数的签名与返回形状:`def objectidconverter2paramschema(converter): "
             "return {'type': 'string', 'format': 'ObjectID'}`",
     "impact": "六个 *2paramschema 的**契约**基本被这段说明白了。剩下的难点是"
               "各转换器**各自的**属性映射(minlen/maxlen、signed、枚举反解),"
               "那才是真正的 held-out 部分。",
     "why_kept": "上游自己的公开 API 文档。剥掉它,副本就不再是那个宿主了。"},
    {"where": "src/flask_smorest/spec/__init__.py::Api._register_converter",
     "what": "`self.flask_plugin.register_converter(converter, func)` —— "
             "点明了 FlaskPlugin.register_converter 的调用形状",
     "impact": "register_converter 这一个 node 的难度接近零 —— 调用形状被点明了,"
               "剩下的只是把 (converter, func) 存进一张表。",
     "why_kept": "它是**上游自己的**调用方代码,不是被挖的那份实现。剥掉它,"
                 "副本就不再是那个宿主了(F1:改写宿主的题一律不算 held-out)。"},
]


# 方案 2(换时间轴:选 knowledge cutoff 之后 upstream 才写的函数体)在这个仓上
# **执行不了** —— 离线查 clone 自带的历史查出来的,没再联网。写在**生成证据的
# 脚本里**而不是手改证据文件:证据是机器生成的,手写的东西活不过下一次 main()
# (2026-08-15 当场踩到,一次 `pytest` 跑完就没了)。
TIMELINE_CHECK = {
    "clone_has_post_cutoff_history": True,
    "latest_commit_in_clone": "2026-08-01 f709b45 Update all dependencies",
    "src_or_tests_changed_after_2026_05": "零",
    "only_2026_source_commit":
        "2026-03-22 1878e05 feat: Add pagination metadata field descriptions",
    "why_that_one_is_unusable":
        "它改的是 7 行 `metadata={\"description\": ...}` 的**英文文案**。挖了它,"
        "题目就成了'猜出原作者的英文措辞' —— 不可推导(所以确实没被污染),"
        "但那是抽奖不是能力。",
    "dev_vs_tag_on_src_tests": "逐字节相同(dev 多出来的只有 CI/renovate/lock)",
    "conclusion":
        "flask-smorest 没有可用的 cutoff 后 seam。方案 2 要换仓,而换仓要联网 —— "
        "那是用户的裁量。**但 v1 的真死因是选错 seam(可推导性),不是选错仓**,"
        "所以先在同一个仓里按可推导性重选。",
}


def leak_scan(original: str) -> list[dict]:
    """**在造好的副本里找答案。** 找得到 = 这道题当场归零。

    这是本脚本的主产物。"我删了 .git" 是动作,"捞不出来" 才是结论,
    而两者之间隔着所有我没想到的路径。
    """
    fps = _answer_fingerprints(original)
    hits: list[dict] = []
    scanned = 0
    for f in sorted(HOST.rglob("*")):
        if not f.is_file():
            continue
        scanned += 1
        try:
            body = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = f.relative_to(HOST).as_posix()
        if rel == SEAM:
            continue                       # 挖空后的 seam 本身不算(签名该在)
        for name, pat in fps:
            if re.search(pat, body):
                hits.append({"file": rel, "fingerprint": name})
                break
    if scanned == 0:
        hits.append({"file": "(none)", "fingerprint": "扫描面为空 —— 排除集把树吃光了"})
    return hits


def selfcheck(original: str) -> list[str]:
    """**扫描器先证明自己查得出泄漏,才有资格发绿。**

    把原件塞回副本里的一个临时文件,扫描必须当场报出来。不做这一步的话,
    "零泄漏"分不清是**真的没漏**,还是**指纹太窄什么都匹配不上** ——
    而指纹刚刚被我收窄过两轮,正是最该疑心的时候。
    """
    bad: list[str] = []
    planted = HOST / "_rp_selfcheck_planted.py"
    try:
        planted.write_text(original, encoding="utf-8")
        hits = leak_scan(original)
        if not any(h["file"] == planted.name for h in hits):
            bad.append("自证:把原件原样塞进副本,扫描竟然没报 —— "
                       "指纹太窄,'零泄漏'是假绿")
    finally:
        planted.unlink(missing_ok=True)

    # 反向:干净副本上不许报 —— 否则它恒红,同样没有信息量
    if leak_scan(original):
        bad.append("自证:干净副本上就报泄漏 —— 指纹太宽,红了也说明不了什么")
    return bad


def repo_scan(original: str) -> list[str]:
    """**答案不许出现在本仓 git 跟踪的任何文件里。**

    2026-08-15 对抗性搜捕当场抓到:一次勘察留下的
    `docs/evidence/host2_discrimination/naive_plugins.py` 是 12 个函数的完整
    实现(`__init__`/`init_spec` 与原件 **AST 逐字相同**),配上同目录
    `measurement.json` 里的半行代码,实测可重建出 **554/554**。
    而本仓 remote 是**公开** GitHub 仓 —— 当时 129 个 commit 未推,侥幸没漏。

    教训不是"别把答案写进证据",是**扫描边界画错了**:我只扫了交付树,
    而答案躺在出题方自己的仓里。所以这条单列一道闸门。
    """
    import subprocess

    fps = _answer_fingerprints(original)
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"],
                             capture_output=True, text=True).stdout.split("\0")
    bad: list[str] = []
    for rel in tracked:
        if not rel:
            continue
        f = REPO / rel
        if not f.is_file():
            continue
        try:
            body = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name, pat in fps:
            if re.search(pat, body):
                bad.append(f"**本仓 git 里有答案**:{rel}({name})—— remote 是公开仓")
                break
    return bad


def structural_checks() -> list[str]:
    """结构性检查:那三条被点名的路径,逐条确认没了。"""
    bad: list[str] = []
    if (HOST / ".git").exists():
        bad.append(".git 还在 —— `git show HEAD:<seam>` 一行拿到原件")
    for p in HOST.rglob("*"):
        if p.is_dir() and p.name in STRIP_DIRS:
            bad.append(f"该剥的目录还在:{p.relative_to(HOST)}")
        if p.is_file() and p.name.endswith(STRIP_SUFFIXES):
            bad.append(f"该剥的文件还在:{p.relative_to(HOST)}")
    if not (HOST / SEAM).is_file():
        bad.append(f"seam 文件不见了:{SEAM}")
    else:
        t = (HOST / SEAM).read_text(encoding="utf-8")
        if "raise NotImplementedError" not in t:
            bad.append("seam 没被挖空 —— 答案原样在副本里")
        # F1 分界线:只许挖空,不许加语义
        orig_syms = {n.name for n in ast.walk(ast.parse(
            (SRC / SEAM).read_text(encoding="utf-8")))
            if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        new_syms = {n.name for n in ast.walk(ast.parse(t))
                    if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        added = new_syms - orig_syms
        if added:
            bad.append(f"副本里多出了原件没有的符号 {sorted(added)} —— "
                       "那是 ENRICHED,按 F1 一律不算 held-out")
    return bad


def main() -> int:
    if not SRC.is_dir():
        print(f"封存件不在:{SRC}", file=sys.stderr)
        return 2
    info = build()
    original = (SRC / SEAM).read_text(encoding="utf-8")
    hits = leak_scan(original)
    bad = structural_checks() + selfcheck(original) + repo_scan(original)

    report = {
        "_what": "H2 宿主副本的部署层自证 —— 挖空 + 剥离 + **捞不出答案**",
        "_why": "这道题的诚实尺寸是 1–2 bit。答案只要还能从副本里捞出来,"
                "信息量当场归零,而所有数字看起来照常。",
        "host": str(HOST), "sealed_source": str(SRC), "seam": SEAM,
        "carved_symbols": info["carved_symbols"],
        # 挖空自己制造的残留(孤儿 import)—— 抹掉的记在这里,免得日后
        # 有人以为副本与上游的差异只有那 12 个 raise
        "carve_removed_imports": info["carve_removed_imports"],
        "stripped": {"dirs": sorted(STRIP_DIRS), "suffixes": list(STRIP_SUFFIXES),
                     "files": sorted(STRIP_FILES)},
        "host_digest": _digest_tree(HOST),
        "leak_hits": hits, "structural_problems": bad,
        "_selfcheck": "扫描器先被喂过一次原件(塞进副本),必须当场报出来;"
                      "再在干净副本上跑一次,必须不报。两头都过才算它在验。",
        # 泄漏(必须为空)与公开线索(必须如实列出)是两回事。混成一栏的话,
        # 要么为了"零泄漏"去删上游自己的文档(改写宿主),要么把真泄漏
        # 混在"已知无害"里放过 —— 两种都坏。
        "disclosed_hints": DISCLOSED_HINTS,
        "timeline_check": TIMELINE_CHECK,
        "ok": not hits and not bad,
    }
    out = REPO / "docs" / "evidence" / "host2_prepare" / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    print(f"挖空 {len(info['carved_symbols'])} 个符号:{info['carved_symbols']}")
    print(f"副本:{HOST}")
    if bad:
        print("\n结构性问题:")
        for b in bad:
            print("  -", b)
    if hits:
        print(f"\n**泄漏 {len(hits)} 处**:")
        for h in hits[:20]:
            print(f"  - {h['file']}  ({h['fingerprint']})")
    print(f"\n证据:{out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
