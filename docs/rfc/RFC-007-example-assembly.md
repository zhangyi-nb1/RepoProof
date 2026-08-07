# RFC-007: 样例驱动任务装配(Phase 7,产品模式)
修复根断层:FrozenAdoptionIntent → 可运行 TaskPackage 之间不再需要
任何专家/外部 AI。期望值的合法来源 = 用户样例(用户定义成功)。
流程(全确定性):用户给 N≥3 组 {输入, 期望}(期望支持前缀
`contains:` 表示包含断言,否则相等断言)→ 系统划分 公开(agent 可
见可自测)/held-out(隐藏验证,≥1 组)→ 编译成 pytest → 生成
合同+RequirementSpec+seam 式 consumer fixture+oracle+自动控制组
(正控=样例硬编码映射,证明测试自洽可满足;负控=空实现,必挂)
→ 复用既有 freeze-task --full 冻结 → 用户在 UI 亲自点「真实运行」。
诚实分级:验收强度=「用户样例级」,低于基准案例的「参考校准级」,
报告与 UI 均标注;宿主项目 v1 不进容器(agent 依据公开样例与目标
仓库工作;适配代码由用户自行合入宿主,原项目回归在本机自测)。
Claude/外部 AI 全程零参与;零 Core 改动。
