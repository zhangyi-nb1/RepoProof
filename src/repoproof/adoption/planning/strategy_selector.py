"""Strategy Selector(RFC-004;RFC-008 §7.2 重构)— 八种接入方式的
确定性比较与推荐。

kind ∈ {PYTHON_ADAPTER, WRAPPER_FACADE, CLI_SUBPROCESS, HTTP_SIDECAR,
PLUGIN, CLONE_AS_BASE, BOUNDED_PATCH, UNSUPPORTED}。
规则全部由 Host/Repository 报告字段驱动;禁止「所有任务默认生成
adapter.py」——推荐随证据变化。空白项目模式给三种建站计划并强制
用户选择(不自动推荐)。零 LLM。
"""

from __future__ import annotations

from repoproof.adoption.analysis.host_analyzer import BLANK_PROJECT, HostProjectReport
from repoproof.adoption.analysis.repository_analyzer import RepositoryReport

PYTHON_ADAPTER = "PYTHON_ADAPTER"
WRAPPER_FACADE = "WRAPPER_FACADE"
CLI_SUBPROCESS = "CLI_SUBPROCESS"
HTTP_SIDECAR = "HTTP_SIDECAR"
PLUGIN = "PLUGIN"
CLONE_AS_BASE = "CLONE_AS_BASE"
BOUNDED_PATCH = "BOUNDED_PATCH"
UNSUPPORTED = "UNSUPPORTED"

ALL_KINDS = (PYTHON_ADAPTER, WRAPPER_FACADE, CLI_SUBPROCESS, HTTP_SIDECAR,
             PLUGIN, CLONE_AS_BASE, BOUNDED_PATCH, UNSUPPORTED)

_SERVICE_DEPS = {"fastapi", "flask", "uvicorn", "gunicorn", "starlette", "django"}


def _strategy(**kw):
    from repoproof.adoption.planning.adoption_plan import Strategy

    return Strategy(**kw)


def _integration_point(host: HostProjectReport) -> str:
    return host.integration_candidates[0].file if host.integration_candidates else "新建适配模块"


def select_strategies(
    host: HostProjectReport,
    repo: RepositoryReport,
) -> tuple[list, str, str, bool]:
    """→ (strategies, recommended_name, rationale, requires_user_choice)。

    已有项目:按证据生成适用候选并推荐一种;不适用的方式在
    alternatives 里给一句排除原因(可审查)。
    空白项目:三种建站计划,requires_user_choice=True,不自动推荐。
    """
    api_names = [str(f.value) for f in repo.public_api[:5]]
    cli_names = [str(f.value) for f in repo.cli_entry_points[:5]]
    service_hit = sorted(_SERVICE_DEPS & set(repo.dependencies))
    point = _integration_point(host)
    dist = repo.repository.rsplit("/", 1)[-1]
    blank = host.host_mode.value == BLANK_PROJECT

    if blank:
        opts = [
            _strategy(
                kind=CLONE_AS_BASE, name="建站计划一:以目标仓库为新项目基础(CLONE_AS_BASE)",
                description="把目标仓库完整落为你空目录下的新项目基础,再按你的需求做有限修改",
                why="你要的能力接近目标仓库的整体形态时最省",
                est_changed_files=["<空目录>/(整仓库落地)", "README/配置有限修改"],
                new_dependencies=list(repo.dependencies[:8]),
                needs_network=True, needs_secret=False, modifies_host=True,
                risks=["继承目标仓库全部依赖与结构", "License 义务随整仓库进入你的项目"],
                alternatives=["只要部分能力 → 建站计划三", "要自己的项目形态 → 建站计划二"],
                verification="安装、启动、目标能力样例、依赖锁、干净环境复测(宿主回归 = N/A)",
                pros=["最快得到可运行项目"], cons=["项目形态由上游决定"],
            ),
            _strategy(
                kind=WRAPPER_FACADE, name="建站计划二:围绕目标仓库新建项目(WRAPPER_PROJECT)",
                description="新建你自己的 Python/CLI/FastAPI 项目骨架,目标仓库作为依赖被包装",
                why="你要自己的项目边界和接口,只把上游当能力来源",
                est_changed_files=["<空目录>/pyproject.toml", "<空目录>/src/…(新骨架)", "适配与启动入口"],
                new_dependencies=[dist],
                needs_network=True, needs_secret=False, modifies_host=True,
                risks=["骨架代码由系统生成,需要你审查后使用"],
                alternatives=["整仓库直接可用 → 建站计划一"],
                verification="安装、启动命令、能力样例、Schema 断言、依赖锁、干净环境复测",
                pros=["项目形态归你"], cons=["比直接克隆多一层结构"],
            ),
            _strategy(
                kind=PYTHON_ADAPTER, name="建站计划三:最小能力提取(CAPABILITY_SCAFFOLD)",
                description="只提取目标仓库的目标能力,生成最小 Python 包/CLI/API",
                why="你只要一小块能力,不要整个项目",
                est_changed_files=["<空目录>/最小包骨架 + 1 个适配文件"],
                new_dependencies=[dist],
                needs_network=True, needs_secret=False, modifies_host=True,
                risks=["能力边界需要你的样例来定义,否则验收强度有限"],
                alternatives=["要更完整功能 → 计划一/二"],
                verification="能力样例、输出 Schema、依赖锁、干净环境复测",
                pros=["最小、最可审查"], cons=["覆盖面窄"],
            ),
        ]
        return opts, "", "空目录有三种可行的开始方式,系统不代替你选:请在计划页选定一种再继续", True

    excluded: list[str] = []
    opts = []

    if api_names:
        opts.append(_strategy(
            kind=PYTHON_ADAPTER, name="方案:Python 依赖 + 薄适配层(PYTHON_ADAPTER)",
            description=f"目标仓库作为依赖安装,适配层直接调用公开入口 {api_names},只做输入输出映射",
            why="目标仓库有清晰公开 Python 入口,直接调用最省、最贴近上游语义",
            est_changed_files=[f"适配区新增 1 个文件(接到你项目的 {point})"],
            new_dependencies=[dist],
            needs_network=True, needs_secret=False, modifies_host=False,
            risks=["上游接口变化时需要跟进"],
            alternatives=["统一多来源 → WRAPPER_FACADE", "上游只有 CLI → CLI_SUBPROCESS"],
            verification="公开样例测试 + 宿主回归 + 干净环境复测",
            pros=["依赖简单", "修改范围小", "行为与上游一致,便于验收"],
            cons=["上游接口变化时需要跟进"],
        ))
    else:
        excluded.append("PYTHON_ADAPTER:未识别公开 Python 入口")

    if cli_names:
        opts.append(_strategy(
            kind=CLI_SUBPROCESS, name="方案:CLI 子进程适配(CLI_SUBPROCESS)",
            description=f"通过子进程调用目标仓库命令行入口 {cli_names},适配层解析其输出",
            why="目标仓库提供命令行入口,进程边界清晰、无 Python API 耦合",
            est_changed_files=[f"适配区新增 1 个子进程适配文件(接到 {point})"],
            new_dependencies=[dist],
            needs_network=True, needs_secret=False, modifies_host=False,
            risks=["输出格式为非正式契约,版本间可能变化", "子进程开销"],
            alternatives=["有公开 Python 入口时优先 PYTHON_ADAPTER"],
            verification="CLI 输出样例断言 + 宿主回归 + 干净环境复测",
            pros=["隔离性好"], cons=["解析文本输出比调用 API 脆弱"],
        ))
    else:
        excluded.append("CLI_SUBPROCESS:未识别 CLI 入口")

    if service_hit:
        opts.append(_strategy(
            kind=HTTP_SIDECAR, name="方案:HTTP 边车服务(HTTP_SIDECAR)",
            description=f"目标仓库按其服务形态(检出 {service_hit})本地启动,适配层走 HTTP 调用",
            why="目标仓库本身是服务形态,保持其原生运行方式",
            est_changed_files=["适配区新增 1 个 HTTP 客户端适配文件", "本地启动配置"],
            new_dependencies=[dist, "httpx(如宿主没有)"],
            needs_network=True, needs_secret=False, modifies_host=False,
            risks=["引入本地服务生命周期管理", "验证阶段默认断网,需走本地回环并在合同声明"],
            alternatives=["能力可以库方式调用时优先 PYTHON_ADAPTER"],
            verification="服务启动探针 + 能力样例 + 宿主回归 + 干净环境复测",
            pros=["不侵入上游"], cons=["运行时组件更多"],
        ))
    else:
        excluded.append("HTTP_SIDECAR:未检出服务形态依赖")

    opts.append(_strategy(
        kind=WRAPPER_FACADE, name="方案:Wrapper/Facade 抽象层(WRAPPER_FACADE)",
        description="在适配层与上游之间加一层自定义抽象,统一多个来源或隔离上游变化",
        why="需要统一接口或预期未来替换实现时使用",
        est_changed_files=[f"适配区新增 facade + 适配文件(接到 {point})"],
        new_dependencies=[dist],
        needs_network=True, needs_secret=False, modifies_host=False,
        risks=["代码更多、验收面更大、偏离上游行为的风险更高"],
        alternatives=["单一来源直接调用 → PYTHON_ADAPTER"],
        verification="facade 契约测试 + 能力样例 + 宿主回归 + 干净环境复测",
        pros=["未来可替换实现"], cons=["代码更多、验收面更大、偏离上游行为的风险更高"],
    ))

    excluded.append("PLUGIN:当前版本不自动识别宿主插件体系(如确有插件协议,请在目标里说明)")
    excluded.append("BOUNDED_PATCH:仅在上游必须小改才能用时启用,受 Patch 预算约束;默认不推荐")
    excluded.append("CLONE_AS_BASE:仅空目录模式适用")

    if api_names:
        rec = opts[0].name
        rationale = f"目标仓库有清晰公开入口 {api_names},直接调用最省、最贴近上游语义,并接到你项目的 {point}"
    elif cli_names:
        rec = next(s.name for s in opts if s.kind == CLI_SUBPROCESS)
        rationale = f"未识别公开 Python 入口,但有 CLI 入口 {cli_names}:子进程适配是最小可靠路径"
    elif service_hit:
        rec = next(s.name for s in opts if s.kind == HTTP_SIDECAR)
        rationale = f"目标仓库是服务形态({service_hit}),按其原生方式本地启动最不失真"
    else:
        rec = next(s.name for s in opts if s.kind == WRAPPER_FACADE)
        rationale = "未识别公开入口/CLI/服务形态,需要 wrapper 包装内部模块(先确认入口更好)"

    for s in opts:
        s.alternatives = list(s.alternatives) + [f"已排除:{e}" for e in excluded]
    return opts, rec, rationale, False


def select_strategy(api_names: list[str], host: HostProjectReport):
    """兼容入口(旧签名)。新代码一律用 select_strategies。"""
    from repoproof.adoption.analysis.host_analyzer import Finding
    from repoproof.adoption.analysis.repository_analyzer import RepositoryReport

    repo = RepositoryReport(
        repository="unknown/unknown",
        is_public=Finding.unknown(), commit=Finding.unknown(),
        license=Finding.unknown(), python_version=Finding.unknown(),
        install_method=Finding.unknown(),
        public_api=[Finding.fact(n, "caller-provided") for n in api_names],
    )
    strategies, rec, rationale, _ = select_strategies(host, repo)
    return strategies, rec, rationale
