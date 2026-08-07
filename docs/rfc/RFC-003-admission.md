# RFC-003: Repository Admission(Phase 3)
层:Task Preparation。纯函数:`decide(HostProjectReport, RepositoryReport)
-> AdmissionReport`,零 LLM/网络/执行。
四态优先级:UNSUPPORTED(硬阻断:GPU 需求/无法固定 commit/需要 secret)
> NEED_INFORMATION(license/安装方式/python 版本/宿主测试命令 UNKNOWN)
> RISK_REVIEW(外部服务依赖/扫描截断/仓库无测试——需人确认)
> READY。输出含 ✓ 已确认事实 / ? 待补问题 / × 阻断项 / ! 风险 /
next_step 中文文案;"任何仓库可分析,只有满足条件才自动适配"。
support_policy=规则表(数据),risk_checker=双报告风险合并+版本冲突派生。
测试:§十五 READY/NEED_INFORMATION/UNSUPPORTED + RISK_REVIEW + 优先级。
