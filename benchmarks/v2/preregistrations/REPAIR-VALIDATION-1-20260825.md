# REPAIR-VALIDATION-1:复杂任务架构验证批(冻结,待批准开跑)

> 2026-08-25 · 目的不是成功率,是验证新框架(Analyzer→Plan→路由→
> AGENT_ADAPT→有界修复→同一验证链→投影)在**真实模型 × 会出错的
> 复杂任务**上的端到端行为,特别是 repair 的诊断/反馈/进展度量/终止。

## 一、动机(历史数据的诚实缺口)

用新投影回看全部 37 个历史真实发次:REPAIR_SUCCEEDED 25 /
NO_REPAIR_NEEDED 10 / 终止 3。但其中 gpt-5.5 批次一的 rounds=2 形态
混入了 `_run_public` 漏注入时代的伪信号(agent 首轮已交完整实现,
轮末反馈 collect 崩才进第二轮);干净的 repair 语义样本只有 DS 批
(json5/tabulate 第 2 次救回、pygments STOP_NO_PROGRESS、ftfy
STOP_SCOPE_DRIFT)。反馈面修复(M99a 锚)之后、复杂任务上的
repair 轨迹:**零样本**。本批补这个空白。

## 二、冻结配置

| 轴 | 值 |
|---|---|
| 模型(主) | `gpt-5.6-terra`(.env 新默认;连通取证已过,回显标识一致) |
| 模型(对比) | `gpt-5.6-luna`(弱位;唯一用途=repair 触发器与对比,见 §四) |
| 后端 | mini-swe(不变);provider=.env 缺省 openai 通道 |
| 路由 | 两任务均预期 AGENT_ADAPT(复杂映射,非单必选参数机械包装);plan.yaml 由真 analyzer 生成、人工确认后入束 —— **这是 plan 驱动 AGENT_ADAPT 的首批真实全链** |
| 发制 | 每(任务×模型)一发;失败=数据;HARNESS/BLOCKED 系统层可排障补发并勘误 |
| 批帽 | 名义 in 2,000,000,发前判定触顶即停;最多 4 发 |
| 口径 | test_mode=PRODUCT;真发 PRODUCT_ONBOARDING、彩排 HARNESS_SELFCHECK;不充闸不计模型能力 |

## 三、任务清单(2 个,复杂档;换任务禁止,不可行=如实放弃行)

**T1 `jsonschema-report`**(上游 python-jsonschema/jsonschema,pinned):
输入=单 JSON 文件 `{"schema": {...}, "data": ...}`;输出=**严格 JSON
对象** `{"valid": bool, "error_count": int, "errors": [{"path": "<JSON
Pointer>", "message": "<str>"}]}`,errors 按 path 字典序;valid 时
errors=[] 且 error_count=0。输出合同 root_type=object + required 四键
(M5 T6–T9 全量启用)。合法难点:ValidationError.absolute_path →
JSON Pointer 组装、多错误收集排序(iter_errors)、嵌套 anyOf 消息。

**T2 `rrule-expand`**(上游 dateutil,pinned;与 v1 parse 任务不同能力):
输入=文本文件,第 1 行 `DTSTART:<ISO8601>`,第 2 行 `RRULE:<规则>`;
输出=按规则展开的前 10 次发生时间(COUNT<10 则全部),ISO 8601 每行
一个。合法难点:rrulestr 的 dtstart 传参、COUNT/UNTIL 边界、BYDAY/
INTERVAL 语义、时区裸时间一致性。

难度纪律:难点全部「合法」——题面自洽、样例真值由 reference 直连
生成、oracle 与合同一致(M5 冻结门执法);**不允许**用自相矛盾题面
或隐藏约定制造失败(那是 CONTRACT owner,按 Gate 2 不进 repair)。

## 四、执行序与条件加发(确定性,防挑数据)

1. 每任务:analyzer→plan(预期 AGENT_ADAPT)→人工确认→题面人闸
   (样例真值 reference 直连生成)→fake 彩排门→terra 真发一发。
2. **条件加发**:某任务 terra 结果为 NO_REPAIR_NEEDED(首轮即过,
   未触发修复)→ 该任务加发 luna 一发(弱位更可能触发 repair)。
   条件与动作在此冻结;所有发次无论结果全记全报,不选择性呈现。
3. 全部发次结束后:对每发跑 FailureAssessment/stop code 投影并与
   report 事实核对;Studio 活动页结论卡人工目验一次。

## 五、架构验证判据(本批要回答的四个问题)

- A. plan.yaml 驱动的 AGENT_ADAPT 真实全链(assert_may_execute→
  彩排→真发→export)通,plan_sha256 进 run 元数据可追溯;
- B. 至少一条发次产生**非平凡 repair 轨迹**(rounds≥2 且 round1
  公开部分通过→failure packet 反馈→轮次推进),或产生诚实终止码
  (NO_PROGRESS/SCOPE_DRIFT/BUDGET/HIDDEN)—— 两者都算架构验证成功;
- C. 九码投影与 run 事实一致(rescued_at 与 public_passed_by_round
  曲线互证);
- D. 输出合同(T1 的 object+required)在真实模型交付上执法
  (含 [tool-output-contract] 独立解析路径至少被覆盖到)。

## 六、停点

**预注册冻结即停;题面备制(样例真值/reference/lock)与开跑均待
用户批准。** 预算粗估:2-4 发 × 150-400K in ≈ 0.4-1.6M,帽内。

## 七、勘误区(append-only)

(空)
