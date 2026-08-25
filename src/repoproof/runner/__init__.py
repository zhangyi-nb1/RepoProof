"""Runner 包 —— 两个分区,边界见 docs/PROJECT_MAP.md。

产品在役(随产品演进):
    tool_pipeline.py    产品主编排(intake→plan→路由→彩排→真发→导出)
    tool_export.py / tool_registry.py / tool_release.py / tool_mcp.py /
    tool_paths.py / tool_host_bridge.py

Benchmark Lab 历史资产(FROZEN,2026-08-25 宣布):
    host_guided.py      执行引擎 —— 特殊件:功能面冻结,但仍被
                        tool_pipeline 调用承担彩排/真发(见其模块注释)
    baseline.py / guided_repair.py / agent_run.py / sidecar_session.py /
    calibration.py / demo.py / scaffold.py

冻结 = 不再新增研究面功能;判定/安全缺陷照修(证据纪律不冻结)。
产品新逻辑一律落在 tool_pipeline 与 adoption/ 层,不得加深对本包
冻结区的依赖(棘轮只减不增)。
"""
