# 交接:M4 批次二执行中(给下一个操作员/AI 的自包含说明)

写于 2026-08-23,交接时 HEAD ≈ 「M4 批次二开跑:tomli-tool VERIFIED_TOOL_READY」。
**有疑先查盘(git log / runs.jsonl / EXPLORATION_LOG 尾部),勿凭本文档断言进度**——
本文档描述交接时刻的状态,你接手时可能已有推进。

## 一、项目一句话

RepoProof = 「GitHub 能力 → 已验证本地工具」流水线(章程
`docs/rfc/RFC-010-LOCAL-TOOL-PRODUCT-CHARTER.md`)。产品承诺是
**判定保证而非成功保证**:错误结果零放行、失败可解释、成本有界、
成功可复现。M0-M4 已全关;现在执行的是 **M4 批次二**(12 仓规模化,
预注册 `benchmarks/v2/preregistrations/M4-TOOL-ONBOARDING-2-20260823.md`,
清单 `M4-batch-2-tasks.json`)。

## 二、交接时刻的进度

| 状态 | 任务 |
|---|---|
| ✅ DONE | tomli-tool(真发 gpt-5.5 PASS,已导出 `~/tools/tomli-tool`) |
| ✖ 放弃行 | tldextract(admission 硬拒:仓要求 GITHUB_TOKEN;**不换仓**,勘误区记) |
| ⏳ 待 build ×10 | xmltodict / pypinyin / jieba / opencc / num2words / inflect / phonenumbers / filetype / pyspellchecker / emoji |

10 个待 build 任务的草稿束在 **`tool_tasks/_pending_drafts/<name>_draft/`**
(仓内持久区,不入 git)。**人闸已完成**:每束含 draft.yaml(已修正)、
examples/(输入+期望,期望由 pinned 上游直连生成)、examples.yaml、
reference_impl.py、reference.lock.txt。你不需要重做题面,只需 build。

已做过的草稿修正(勿回退):xmltodict 补 import_module+MIT;
phonenumbers 补 distribution/import_module/name(包根在仓 `python/`
子目录,静态提取扑空);opencc 工具名取短 `opencc-tool`;filetype 设
`malformed_applicable: false`(全域合法输入豁免,chardet 同型先例)。

## 三、逐仓执行(核心循环)

每仓一条命令,**串行**(台账/bench 竞争,不并发):

```bash
set -a; source .env; set +a
.venv/bin/python -m repoproof.cli tool build --draft-dir tool_tasks/_pending_drafts/xmltodict_draft
```

顺序:xmltodict → pypinyin → jieba → opencc → num2words → inflect →
phonenumbers → filetype → pyspellchecker → emoji。

每发流程自动含:confirm(D 闸+装配+T 闸冻结)→ 物化 → wheelhouse →
**fake 彩排门(不 PASS 不烧真预算)** → 真发(gpt-5.5×mini-swe,
provider 从 .env 缺省)→ export+注册。单仓 5-10 分钟。末尾 JSON 的
`verdict` 应为 `VERIFIED_TOOL_READY`,`exported` 给出 `~/tools/<name>`。

### 失败处置(预注册条款)

- **彩排 FAIL**:读 `runs/<run_id>/report.json` 的 gate_reasons 定位。
  harness 缺陷 → 先写合成测试自证再修,清该任务残留后重建(v1 重建
  合法,真发未烧);题面欠定 → 放弃行,不修题凑答案。
- **真发 FAIL**:一发制,失败=数据,不重发。
- **BLOCKED(H9-a/系统层)**:排障(通常是答案残留可达——清掉它)后
  补发合法,勘误区记一笔。
- 清理任务残留的完整清单(重建前):`contracts/tool-<name>-v1.{yaml,yaml.sha256,requirements.yaml}`、
  `oracle/tool-<name>-v1/`、`controls/tool-<name>-v1/`、
  `fixtures/tool_skeleton_<name>/`、`tool_tasks/tool-<name>-v1/`、
  `tool_tasks/_drafts/tool-<name>-v1/`(束取回再用)、`~/RepoProofBench/tool-<name>-v1/`。

## 四、全部 build 完成后的结算清单(顺序执行)

1. **分类 sidecar**:`benchmarks/v2/run_classifications.jsonl` append
   每发一行(fake 彩排 → `run_purpose: HARNESS_SELFCHECK`;真发 →
   `PRODUCT_ONBOARDING`;均 `test_mode: PRODUCT`,counts_toward_* 全
   false)。run_order 续 `product-51` 起。字段模板抄同文件 product-38+
   行即可(K7 只认登记过的键)。缺陷发现行写诚实 notes。
2. **K11 宿主钉死翻新**:`tests/test_run_classification.py` ~392 行
   `hosts_covered` 断言加新 `local-tool/<tool.name>`(字母序;tomli
   已入账也要加)。这是唯一预期内的钉死翻页。
3. `.venv/bin/python scripts/gate_report.py --write`
4. `.venv/bin/python scripts/m4_replay_check.py`(重装档验证,append
   `benchmarks/v2/m4_replay.jsonl`)
5. **操作员审计**:每工具 `bash ~/tools/<name>/build.sh` 后用**全新
   非样例输入**实测一发,exit/输出人工判合理,append
   `benchmarks/v2/m4_audits.jsonl`(字段抄现有行)。
6. `.venv/bin/python scripts/tool_metrics.py --tasks benchmarks/v2/preregistrations/M4-batch-2-tasks.json --write`
   (批次二单独计池,不与批次一混)。
7. **预算清点**:台账真发行 input_tokens 求和 vs 6M 帽,如实报。
8. 全量 `.venv/bin/pytest tests/ -p no:cacheprovider`——交接时基线
   **1174 passed + 60 skipped + 0 failed**;K11 翻新后应回全绿。
9. 提交(见 §五红线)+ `docs/EXPLORATION_LOG.md` 尾部 append 状态条目
   (格式抄尾部现有条目)+ 预注册勘误区 append(tldextract 放弃行等)。

## 五、硬纪律红线(违反=事故,无例外)

1. **密钥绝不经手**:只用 `set -a; source .env; set +a` 注入;永不
   打印/读取/复制任何 `*_KEY` 值。
2. **台账 append-only**:`runs.jsonl` / `run_classifications.jsonl` /
   `m4_*.jsonl` 只追加,永不改写或删除已有行(勘误=追加新行覆盖语义)。
3. **`docs/evidence/receipt_controls/matrix.json` 永不提交**:全量
   测试会弄脏它,提交前 `git checkout -- docs/evidence/receipt_controls/matrix.json`。
4. **预注册冻结节不可改**,只能在勘误区(§六)append。
5. **一发制**:真发 FAIL 不重发;换仓禁止;帽按发前判定,触顶即停。
6. **答案材料**(examples 期望、reference)不得出现在 `~/RepoProofBench`、
   `~/RepoProofBench-quarantine`、`/tmp` ——H9-a 会拒开真发,被拦=
   清残留,不许绕。`tool_tasks/` 仓内区安全。
7. **oracle / held-out / reference 永不进交付物或公开区**。
8. **E1G 永不开跑**(历史封存约束,与本批无关但列此防误触)。
9. 提交信息末尾带 AI 署名行(仓惯例 `Co-Authored-By: <你的身份>`)。
10. 模型对比/换 provider 需用户明确批准;本批全程 .env 缺省
    (openai×gpt-5.5),不注入 deepseek 三键。

## 六、关键文件地图

| 用途 | 路径 |
|---|---|
| 预注册+清单 | `benchmarks/v2/preregistrations/M4-TOOL-ONBOARDING-2-20260823.md` + `M4-batch-2-tasks.json` |
| 待 build 束 | `tool_tasks/_pending_drafts/<name>_draft/` |
| 运行台账 | `benchmarks/v2/runs.jsonl`(append-only) |
| 分类旁挂 | `benchmarks/v2/run_classifications.jsonl` |
| 指标出口 | `scripts/tool_metrics.py` / `m4_replay_check.py` / `gate_report.py` |
| 流水线 | `src/repoproof/runner/tool_pipeline.py`(build 全链)|
| 执行器 | `src/repoproof/runner/host_guided.py`(勿改锚定语义;最近修复=_run_public 并入 _tool_env,有 M99a 突变锚护着)|
| 工作日志 | `docs/EXPLORATION_LOG.md`(尾部=最新状态,append 式)|
| 已交付工具 | `~/tools/<name>/`(现 15 个,全带 mcp_server.py;批次二新工具 build 后如需 MCP:`.venv/bin/python -m repoproof.cli tool mcp <name>`)|

## 七、交接后的第一步

```bash
git log --oneline -5 && git status --short
tail -30 docs/EXPLORATION_LOG.md
ls tool_tasks/_pending_drafts/
grep -c "" benchmarks/v2/runs.jsonl
```

对齐盘面后,从 §三 的 xmltodict 开始逐仓推进。
