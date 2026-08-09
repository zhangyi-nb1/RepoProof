# OfferClaw 副本引导手册(Phase 1 首测产出物,2026-08-09)

> 用途:任何新建的 OfferClaw 测试副本按本手册引导后即达 Host Baseline
> 基线态。基线清单落盘在副本内 `HOST_BASELINE_MANIFEST.json`。
> 纪律来源:TESTPLAN-V2 §4-3(七类资源)、§4-5(数据密钥)、
> OFFERCLAW-RISK-AUDIT(L1/L2)。

## 一、实测基线(t1 副本,OfferClaw @ 8e59a18f)

| 检查 | 结果 | 备注 |
|---|---|---|
| `pytest tests/ -q` | **591 passed / 7 skipped / 0 failed** | 3 次重复完全一致 |
| 套件耗时 | **~12.5 秒** | ← **推翻方案的分层回归修正:每轮跑全量** |
| `verify_pipeline.py` | 6/6 通过 | 含 chroma 连通 |
| `verify_docs.py` | 0 处裸露 | |
| `doctor.py` | 8 OK · 2 WARN · **1 ERR** | ERR/WARN 均为**已知预期差异**(下) |

**已知预期差异(不是宿主故障,回归判据=相对本基线不退化)**:
1. `doctor` ERR:chunks 口径 112(副本合成语料索引)vs 3538
   (metrics.json 记录的真实环境)——副本用合成语料重建索引的必然结果;
2. `doctor` WARN ×2:`.env.local` 缺失 / `OPENAI_API_KEY` 未注入——
   合成密钥政策(§4-3 C 类)的预期表现。**594 项测试不依赖真实密钥,
   已实证**(引导后 591 全绿,零真钥)。

## 二、引导步骤(新副本照做)

```bash
# 0. 副本(禁硬链接、去 origin —— 审核实证的两条红线)
git clone --no-hardlinks ~/Desktop/XIANGMU/offerclaw ~/RepoProofBench/<name>
git -C ~/RepoProofBench/<name> switch --detach 8e59a18f78056113ffa34d27eb1cfb2a64ae2108
git -C ~/RepoProofBench/<name> remote remove origin

# 1. venv(实测 ~3 分钟)
cd ~/RepoProofBench/<name> && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

# 2. 合成替身(见 §三)+ 合成语料 → 3. 建索引(实测 12 秒)
.venv/bin/python rag_ingest.py

# 4. 基线验证
.venv/bin/python -m pytest tests/ -q -p no:cacheprovider   # 期望 591 passed
```

## 三、七类资源的 OfferClaw 实测答案(§4-3 表填答)

| 类 | 实测结论 |
|---|---|
| A 只读缓存 | HF/ModelScope 已有 `BAAI/bge-base-zh-v1.5`,**共享复用,零下载**;`HF_HUB_OFFLINE=1` |
| B 运行态数据 | `chroma_db`(253MB 真实简历/JD 向量)**不复制**——改用合成语料 `knowledge_base/doc/bench_synthetic_notes.md` 重建(112 块)。代价=chunks 口径差异(已知项 1) |
| C 密钥凭据 | **零真钥**:591 测试全绿无需任何 API key;agent 轮次注入合成密钥 |
| D 外部服务 | 无(Chroma 内嵌) |
| E 私有依赖/LFS | 无 |
| F 绝对路径 | **零命中**(审计报告已证:数据路径全 `__file__` 锚定) |
| G 平台绑定件 | venv 副本内重建 |

## 四、合成替身清单(真实内容永不进副本)

宿主这些文件为 **untracked**(git 克隆天然不带),但测试/doctor 需要它们
存在。替身原则:**分类字段与真实档案等价**(公开测试已锚定这些粗粒度
属性:学历/专业/所在地/可接受地域/方向优先级),**身份与叙事内容全部
合成**(姓名/学校/项目细节/联系方式)。

| 文件 | 替身做法 |
|---|---|
| `user_profile.md` | 镜像真实档案的**章节骨架与行格式**(profile_loader 纯正则解析,格式必须对齐:`- 学历层次:硕士(在读)`、技能节的 `熟练:/会用:` 前缀、项目节的 `- 项目 N:` 编号);内容全合成 |
| `profiles/p1_zhangyi_ai.json` | 分类字段逐项镜像(匹配器输入面),`desc` 标注合成 |
| `applications.md` / `interview_story_bank.md` / `daily_log.md` / `jd_candidates.md` / `growth_journal.md` | 骨架 + 合成条目 |
| `knowledge_base/project_context/localflow.md` | 合成项目先验(测试断言含 "LocalFlow" 与 "只读") |
| `knowledge_base/doc/bench_synthetic_notes.md` | 合成语料(供 rag_ingest 建索引) |

**迭代实录(23→12→8→4→2→0)**:替身工程共 4 轮,每轮的失败都在告诉
我们"测试到底锚定了什么"——最终收敛于"分类属性等价 + 行格式镜像"。
这条经验对后续任何宿主都适用。

## 五、Phase 1 剩余待办

- [x] Host Baseline 首测 + Manifest + 本手册
- [x] 主目录 untracked 数据一次性备份(`~/RepoProofBench/_offerclaw_untracked_backup_20260809/`)
- [x] T1 任务工程(冻结于 ba0252b;预注册 `benchmarks/v2/preregistrations/T1-prereg-20260809.md`)
- [x] 运行入口接线:`repoproof host-run`(runner/host_guided.py;fake 冒烟
      三发:BLOCKED→FAIL→PASS_ADAPTED 全链验证,含 clean replay)
- [x] 冻结 wheelhouse `~/RepoProofBench/wheelhouse-offerclaw-8e59a18/`
      (146 wheels;`wheelhouse_manifest.json` 含 env_baseline_hash;
      mcp 1.29.0 与 2.0.0 双版本入库——依赖冲突语义在离线源下保留)
- [ ] 用户亲手 pilot(随机序:① deepseek-v4-pro ② gpt-5.5,各 1 次)

## 六、会话内基线与副本基线的已知差异(运行器口径)

- 会话内 pytest = **592 passed**(≥ 副本基线 591,三发冒烟稳定;判据
  为"不降于 591"不受影响;具体多过项待查,挂起);
- `verify_docs.py` 在副本与会话内均因 chunks 交叉核对(112 vs 3538)
  **exit 1**——门禁判据 = "0 处未围栏裸露"不退化(known_deviations
  语义),不是 exit 0;
- 嵌入模型经 `MODELSCOPE_CACHE` 指向真实缓存**只读共享**(A 类资源
  规矩),假 HOME 其余不变。

## 七、T2 基线重冻结(2026-08-10,用户决定"用最新进度")

- 新基线:OfferClaw @ **85278e6**(较 8e59a18 +6 提交:PDF 路由/
  Versioned Upsert/Index Fingerprint/论文域 e5 回退路由;605 测试声称);
- 副本 `~/RepoProofBench/offerclaw-t2-odr`(--no-hardlinks,零共享
  inode,origin 已移除);**替身自 t1 副本直迁,602/7/0 一次全绿零迭代**
  (引导缺陷修正:替身在主仓属 gitignored,枚举必须 `--ignored`);
- 基线:**602 passed / 7 skipped / 0 failed · ~12.3s · 3 次确定**;
  verify_pipeline 6/6;verify_docs 0 裸露(chunks 已知偏差同 T1);
  doctor 已知 WARN/ERR 同 T1;PII 0 命中;
- requirements 与 8e59a18 逐字节相同 → wheelhouse CoW 克隆挂新名
  `wheelhouse-offerclaw-85278e6`,**env_baseline_hash 不变**(6bc19ab1…,
  跨基线环境连续性);
- T1 副本与旧基线全部原样保留(历史可复现)。
