# RFC-013: CapabilityPlanV1 与确定性执行路由(Gate 1)

> 状态:ACTIVE(2026-08-25)
> 上位指导:`docs/VERIFIED_TOOL_ONBOARDING_NEXT_STAGE_GUIDE.md` §5–§6
> 基线:`main @ 812bb7b`;本 RFC 只定义字段、路由规则与可信边界,不改写
> 任何冻结合同,不触碰 ToolSpec v1/v2/v3。

## 1. 问题

当前流水线在「仓库大致可处理」(admission 四态)与「开始 AGENT_ADAPT」
之间没有正式产物:没有回答**发现了什么能力表面、为什么支持、为什么走
这条实现路线**。`tool build` 无条件进入 Coding Agent 路线。本 RFC 补上
这一层:一个可审查、可复现、用户确认前不可冻结的计划产物。

## 2. CapabilityPlanV1 Schema(v1 冻结形)

```yaml
schema_version: 1
source:
  url: <repo url 或本地路径>
  commit: <full sha;本地分析无 git 时为空并必入 reason_codes>
capability_goal: <用户原始意图,原文>
detected_surfaces:            # 全部候选,含未选中的(带排除理由)
  - kind: python_callable | cli_entry | http_service
    locator: package.module:function | <console-script> | <framework>
    signature: "(input_path) -> ..."     # AST 提取;非 callable 为空
    evidence: ["src/pkg/mod.py:42", ...] # file:line,不许空
    confidence: HIGH | MEDIUM | LOW
    exclusion_reason: ""                 # 未被选中时必填
support_status: SUPPORTED | REVIEW_REQUIRED | UNSUPPORTED | EXPERIMENTAL
implementation_route: DIRECT_WRAP | AGENT_ADAPT | NONE
delivery_profile: cli_v2
reason_codes: [<稳定机器码>]
risks: [<自然语言,来自 analyzer/policy>]
human_confirmations:          # 冻结前必须逐项确认
  - callable locator
  - input mapping
  - output contract and representative examples
confirmed: false              # confirm 后为 true;false 时禁止触发真发
plan_sha256: <除本字段外全文 canonical json 的 SHA-256>
```

约束(指导 §6 Gate 1 原文落地):

- confidence 只用三档,不制造小数精度;
- 每个 surface 必须带 file:line 证据;未选中的必须写排除理由;
- 路由由确定性规则执行;LLM 最多做候选**排序建议**与自然语言草稿;
- **LLM 建议不能把 REVIEW_REQUIRED 变成 SUPPORTED**(代码级守卫,
  违规建议整体忽略并记入 risks);
- `confirmed: false` 的计划不得冻结、不得触发任何真实模型调用;
- 计划 `plan_sha256` 写入后续 run 元数据,使执行路线可追溯。

## 3. 确定性路由规则(按序命中,首条生效)

| # | 条件(全部来自 analyzer/policy 证据) | 结论 | 主 reason_codes |
|---|---|---|---|
| 1 | GPU / secret / 无法 pin / 非公开 / 无独立真值信号 | `UNSUPPORTED` + `NONE` | GPU_REQUIRED / SECRET_REQUIRED / UNPINNABLE / NOT_PUBLIC |
| 2 | 无 python surface 且无 CLI 信号;或 license 未识别 | `REVIEW_REQUIRED` + `NONE` | NO_PUBLIC_SURFACE / LICENSE_UNRESOLVED |
| 3 | 恰一个 HIGH python_callable 且签名为单必选参数 | `SUPPORTED` + `DIRECT_WRAP` | SINGLE_CALLABLE_MAPPED |
| 4 | ≥1 python_callable(HIGH/MEDIUM) | `SUPPORTED` + `AGENT_ADAPT` | CALLABLE_NEEDS_GLUE(歧义时加 AMBIGUOUS_SURFACE) |
| 5 | 仅 http/service 形态(框架依赖在、无本地 callable) | `EXPERIMENTAL` + `NONE` | SERVICE_SHAPE(M7 未关,不入产线) |
| 6 | 以上都判不出 | `REVIEW_REQUIRED` + `NONE` | UNDECIDABLE(降级,不猜) |

补充:仅有 CLI 入口、无可定位 python callable → 规则 2(CLI 是高质量
**信号**,首版不做任意 CLI 直包,见指导 §5.2);CLI 信号存在时加
`CLI_SIGNAL_ONLY` 供人审。

## 4. 可信边界

- 分析零模型零网络副作用:`analyze_repository_dir` 静态扫描,不执行
  `setup.py`,不 import 目标仓代码;
- 同一 commit + 同一意图,重复生成 plan 逐字节一致(surfaces 排序键 =
  (kind, locator);canonical json);
- `UNSUPPORTED` / `REVIEW_REQUIRED` 路径模型调用数恒为 0;
- confirm 是唯一把 `confirmed` 翻 true 的入口,重算 plan_sha256;
- DIRECT_WRAP 失败不得自动切换 AGENT_ADAPT(owner 归 HARNESS/CONTRACT/
  UPSTREAM);换路线必须重新生成并确认计划(指导 §6 Gate 2.6)。

## 5. 关闭条件(Gate 1)

五类零模型 fixture 证明路由稳定、顺序无关、重复逐字节一致:
API 直包 / CLI 信号 / 歧义仓 / GPU+secret / service;另加「LLM 建议
不能升级状态」守卫负控。全部进 `tests/test_capability_plan.py`。
