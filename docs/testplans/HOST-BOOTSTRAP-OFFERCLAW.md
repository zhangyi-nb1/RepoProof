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
- [ ] T1 任务工程(公开需求/公开测试/隐藏 oracle/task_shape/正负控/直连基线/冻结/预注册)
- [ ] 交付用户可复制运行指令(GPT-5.5 + DeepSeek 各 1,随机序)
