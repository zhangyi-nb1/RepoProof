# RepoProof Studio — UI 设计与实现记录

> 阶段:**Gate 9A(只读中文工作台)已实现**;9B(真实运行控制台)/
> 9C(任务创建向导)/ 9D(Dogfooding)为后续 gate,未实现。
> 上游方案文档:用户提供的《RepoProof 中文 UI 与真实用户测试工作台方案》。

## 定位

RepoProof Studio 是 RepoProof 的本地中文工作台。Gate 9A 让用户
**不调用任何模型、不碰终端**即可:理解项目能力链、查看三个内置
正负案例、复算 Completion Gate 决策、在全新容器中重放 PASS_ADAPTED
产物、浏览/筛选全部 12 条记录运行,并下载完整证据。

## 技术选型(照方案执行)

- Streamlit **1.60.0**(pinned,`pip install -e ".[ui]"`)
- 复用既有 Core:`repoproof.runner.demo`(verify/replay)、
  `docs/benchmark_summary.json`(事实源)、Evidence Bundle
- 无新后端、无数据库、无 FastAPI、无多用户

## 结构

```
src/repoproof/ui/
├── app.py                  # st.navigation 入口(三页)
├── pages/
│   ├── home.py             # 首页:版本/Docker/案例卡/能力边界
│   ├── case_view.py        # 结果与证据:5+5 指标卡 · Agent≠Verdict 对照
│   │                       #   · 验证 Bundle · 无模型重放 · 8 个标签页
│   └── history.py          # 历史运行:12 行事实表 + 筛选 + 两两对比
├── services/
│   ├── facts.py            # 只读事实源(summary/evidence/docker/版本)
│   └── actions.py          # demo_verify / demo_replay 的进程内包装
└── presenters/
    └── zh.py               # 中文映射(Verdict/Agent 结束/责任方/…)
scripts/run_ui.sh           # 127.0.0.1 启动;不开放局域网/公网
tests/ui/test_ui_gate9a.py  # pytest + streamlit AppTest(12 项)
```

## 启动

```bash
.venv/bin/pip install -e ".[ui]"
./scripts/run_ui.sh          # http://127.0.0.1:8501
```

## Gate 9A 铁律(全部由测试钉住)

1. **UI 不复算判定** —— 「验证 Bundle」按钮直接调用 Core 的
   `demo_verify`;UI 源码含 `recomputed =` 之类的门逻辑即测试失败。
2. **事实只来自** benchmark_summary / report / run_manifest / trace /
   adapter 文件;缺失字段显示 `—`,绝不推断。
3. **只读**:UI 源码禁止 `write_text(`/`shutil.copy`/删除调用
   (静态断言);evidence 目录零修改。
4. **不访问 LocalFlow、不读 API Key、零 LLM**(静态 + 渲染树断言)。
5. **刷新不丢选择**:案例选择写入 `st.query_params`。
6. **Agent 结束原因 ≠ 最终 Verdict** 在结果页顶部常驻对照展示。
7. **不夸大**:首页能力边界区 + 历史页"不做成功率归因"标注;
   对比视图只列事实并明示任务版本可能不同。

## 与 CLI 的一致性

| UI 动作 | 等价 CLI |
|---|---|
| 验证 Bundle | `repoproof demo verify --case <case>` |
| 无模型重放 | `repoproof demo replay --case frontmatter-v2-pass` |
| 历史运行表 | `docs/benchmark_summary.json`(同一文件) |

## 后续 gate 预留(未实现,勿声称)

- 9B:DeepSeek Provider 设置(Key 仅进程内存)、后台 worker、
  `runs/<id>/ui_run_state.json`、单 Run 文件锁、实时 Trace。
- 9C:`task init` 向导 + RequirementSpec 编辑 + `task check` 中文缺口。
- 9D:用户本人 Dogfooding 记录。
