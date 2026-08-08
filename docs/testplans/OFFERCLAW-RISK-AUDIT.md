# OfferClaw 破坏风险审计报告(测试开跑前,2026-08-09)

> 触发:用户要求逐项确认"当前测试中 OfferClaw 可能被破坏的风险",
> 特别是绝对路径暗通道(此前一次扫描因 glob 静默失败被漏过——本报告
> 为完整重查)。方法:对主目录只读审计,逐通道穷举"副本进程写出
> 项目目录之外"的可能路径。审计对象 commit `8e59a18f`。

## 一、核心结论

**主目录被破坏的唯一前提是"某进程持有指向主目录的路径"。审计证实
OfferClaw 代码中此类通道为零**;配合已落地的护栏/指纹/副本纪律,
主目录风险已压到"多层防线全部同时失效"级别。

## 二、逐通道审计结果

| # | 通道 | 排查方法 | 结果 |
|---|---|---|---|
| 1 | 代码硬编码绝对路径 `/Users/` | 全库 grep(排除 .venv) | **零真实命中**——仅有的两处是 traj_adapter.py 的**脱敏正则**(它本来就在清洗路径)及其测试 |
| 2 | 数据路径锚定方式 | 逐一读 gap_store/memory_layers/rag_ingest/rag_query/rag_graph | **全部 `__file__` 锚定**(`BASE_DIR=dirname(abspath(__file__))`,chroma_db=join(BASE_DIR,...)):副本内代码永远解析到副本自身,与 cwd、与主目录无关——对副本最安全的模式 |
| 3 | HOME/expanduser 使用 | 全库 grep + 逐处读上下文 | 4 处,**全为只读**:usage_report 读 ~/.openclaw/cron(read_text)、eval_pdf_parser_ab 读 ~/Downloads 样张、modelscope/docling 缓存读 |
| 4 | 写调用落点 catch-all | 含 HOME 引用文件的全部 write/dump 逐一核 | 4 处写全部落在 `BASE/docs/rag_eval/...`(项目内)或 TemporaryDirectory |
| 5 | doctor/verify_pipeline/verify_docs | grep 写调用 | **零写入**,纯检查工具 |
| 6 | git 层(对象库/refs) | 独立审核实证 | 硬链接与 origin 两隐患**已消除**(--no-hardlinks 重建、零共享 inode、origin 移除、主仓 fsck 完好) |

## 三、风险登记册

### 已解决(有实证/有测试)

| ID | 风险 | 对策与状态 |
|---|---|---|
| S1 | 本地 clone 硬链接共享主仓对象库 | --no-hardlinks 重建+links 核验 ✅;纪律入 TESTPLAN §4-2 |
| S2 | 副本 origin 指向主目录(git push 写穿) | origin 已移除 ✅;deny git push 入 argv 策略(Phase 0 ②) |
| S3 | RepoProof 写路径命中主目录 | 硬护栏三写入口+UI 拦截,5 项测试钉死 ✅(77dc6a6) |
| S4 | 主目录被写而无人察觉 | 指纹对账(工作树含 untracked+git refs),3 类改动实测报警 ✅;②接线自动 pre/post |
| S5 | 绝对路径暗通道(副本进程写回主目录) | **本审计:OfferClaw 零命中**;通用扫描仍保留为引导期必查(F 类) |
| S6 | 代码向 HOME 写 | 本审计:零写,HOME 全读 |
| S7 | 数据路径 cwd 依赖 | 零:全 __file__ 锚定 |

### 潜在(目前碰不上但存在,对策已备)

| ID | 风险 | 分析 | 对策 |
|---|---|---|---|
| L1 | **副本携带真实个人数据(PII)** | user_profile.md / applications.md / _local_notes / daily_log.md / summaries 随克隆进入副本,agent 可读→可能进 trace/bundle(源 §44 禁令) | 引导期**合成替身覆盖**这些文件(排除清单扩为"排除+替换"两列);T1 冻结前落实 |
| L2 | agent 经 ~ 读隐私(如 eval 脚本读 ~/Downloads) | 读风险非写风险,但同违 §44 | ②净化环境把 **HOME 指向 run 专用假目录**,一举切断全部 ~ 读写;所需缓存经白名单显式挂载 |
| L3 | 共享 ML 缓存被运行中写污染(跨 run 状态) | 模型缺失时自动下载改缓存 | 引导预热 + HF_HUB_OFFLINE=1 + 假 HOME 下只挂白名单缓存 |
| L4 | argv 策略被创造性绕过后的任意写 | L 模式无内核兜底 | 纵深:策略+指纹对账+副本可弃+git 保底;模式 D 为终极硬化 |
| L5 | L 模式无网络隔离 | 进程内网络调用拦不住 | 离线开关+证据分级明示(TESTPLAN §5) |
| L6 | 运行态锁/临时文件混入快照 | gap_store.json.lock 等 | 快照排除清单(TESTPLAN §4-5) |
| L7 | 未来其他宿主的绝对路径/外部服务 | 通用 | 引导期七类资源策略表(TESTPLAN §4-3)逐类过 |

## 四、API Key 政策(用户问题的精确回答)

1. **多轮修复轮次:严格不需要、也不允许真实 key**。三重依据:
   ①实证:OfferClaw conftest 无任何密钥逻辑,594 测试按设计不碰真钥;
   ②任务工程纪律:T1/T2 公开测试必须 Fake Model/Fake Search(源 §8.2-8);
   ③机制:②净化环境只注入**合成 key**。
2. **"新功能联动调用 API 的功能"怎么测**:这是任务工程的责任——
   OfferClaw 的 provider 走 `OPENAI_BASE_URL` 可配,公开测试用 Fake
   Provider(本地假服务/monkeypatch)验证"调了正确接口、处理了返回、
   错误路径正确",不验证"真模型答得好"(那是能力评测,不是集成测试)。
3. **若轮次中测试意外需要真 key**:表现为典型化失败(认证/网络类),
   **绝不静默借用本地 key、也不中途弹窗要 key**——按"难度过高"分支
   处理:这是任务包缺陷 → 修 task-v2。
4. 真实 key 仅有两个合法位置:①若 Phase 1 实测 doctor 确需真钥,
   只进 harness 自跑的 baseline 进程 env(agent 生命周期之外);
   ②PASS 后用户自愿的本机 smoke 演示。
