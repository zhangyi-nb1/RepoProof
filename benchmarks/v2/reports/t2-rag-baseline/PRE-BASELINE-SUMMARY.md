# T2 批前完整 RAG 基线（2026-08-10 03:45-03:57,循环开跑前)

宿主副本:`~/RepoProofBench/offerclaw-t2-odr` @ OfferClaw `85278e6`(112 合成 chunks 原始态,工作树干净)。
统一环境:`MODELSCOPE_CACHE=~/.cache/modelscope HF_HUB_OFFLINE=1 RAG_PAPER_ROUTE=0 OFFERCLAW_TORCH_DEVICE=cpu`
(终验后必须以**完全相同 env** 重跑对照;flags 已写入各 JSON)。

## 结果(每仪器 ×2 次)

| 仪器 | 结果 | 确定性 |
|---|---|---|
| eval_rag_bench(100 题) | recall@1/3/5 与 MRR **全域 0.0** | 两跑 JSON 逐字节一致 |
| bench gate(负 12/正 12) | 负拒答 12/12;正命中 **0/12** | 同上 |
| eval_abstention(近域负 12) | 拒答 **12/12** acc=1.0 | 两跑 JSON 逐字节一致 |
| eval_rag_domain(负 5/正 5) | 负拒答 5/5;正命中 0/5 | 判定内容一致(仅日志时间戳行不同) |

**容差协议:完全确定 → 终验后不允许任何变化。**

## 仪器有效性的如实说明(重要)

- 100 题/正样本集锚定**真实语料的目标文件**(LoRA/学习路线等),副本按 §44
  数据红线只有合成语料 → 目标文件不存在 → recall 恒 0。**该仪器在副本上
  无检索质量灵敏度,数字不可与主目录 metrics.json 相比**;
- 但"地板态"使所有指标成为干净**绊线**:终验后任何一处 in_kb=True 上浮、
  任何 recall>0、任何拒答下降 = 明确的 KB 污染信号;
- **主探测器 = KB 全集合指纹**(`pre_kb_fingerprint.json`):
  `offerclaw_local_baai_bge_base_zh_v1_5_768` count=112,
  sha256=`74cd21c8875b9170fd167bd828891d0da6e609df00a4e96462da499b1eda633d`
  (id+document+metadata 排序后哈希)。终验后一致 = 知识库分毫未动,
  严格强于一切检索代理指标;
- **realworld 52 不可跑**:真实口语 held-out 集属私有真实数据,按 §44 永不
  进副本 → 记为本基线的已知不可覆盖项(主目录数字不受影响);
- 配合任务内 oracle:H7(No Promote 不污染)/H8(Promote 溯源)/H9(paper
  隔离)在每 run 内直接测 KB 边界,与本批级基线互补。

## 过程发现(已另行记账)

1. **副本引导缺口**:85278e6 新增"论文域 e5 回退路由"未进引导手册 A 类
   预热清单;副本无 `kb_paper_e5_v1` 集合,该路由成为"每弱查询重载 1.1GB
   模型后 fail-soft"的纯代价死路径,曾把单查询拖到 139-235s(MPS 并发
   叠加)。本基线以 `RAG_PAPER_ROUTE=0`(副本上该路径行为不变,恒 None)
   + `OFFERCLAW_TORCH_DEVICE=cpu`(防 MPS 事故,代码注释自带的旋钮)规避;
2. OfferClaw 改进建议(不在本阶段动):`_load_local_model` 无缓存 +
   集合缺失不短路——已挂独立任务芯片。

## 产物清单

`pre_bench_run{1,2}.json`/`.stdout`/`.stderr` · `pre_abstention_run{1,2}.json`
· `pre_domain_run{1,2}.stdout` · `pre_kb_fingerprint.json` · 本文。

## 终验后对照(2026-08-10,六发完赛后;同 env 重跑)

- **KB 指纹逐字节一致**:count=112,sha256 `74cd21c8…` 与批前完全相同
  → 六发 run(含各自 oracle 的 Promote 测试)对副本知识库零残留;
- bench JSON 与批前**逐字节一致**;abstention JSON 逐字节一致;domain
  判定行一致 → 全部绊线未动;
- 终验后门:**PASS(零污染零漂移)**。产物 `post_*` 同目录。
