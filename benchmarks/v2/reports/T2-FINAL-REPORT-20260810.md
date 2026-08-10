# T2 终报告(OfferClaw × Open Deep Research,2026-08-10 全程收束)

> 单一入口文档。分批细节见:T2-stop-report(v1 批 1+2+补发)/
> T2v2-batch-report / T2v3-batch-report / T2v4-batch-report;预注册 ×4
> (T2-prereg / T2-prereg-v2 / T2v3-prereg / T2v4-prereg,含全部修订块);
> 台账 E4/E5 及 8 条状态条目;LESSONS #14-17。

## 一、结局

**T2 目标达成:双模型端到端 PASS_ADAPTED(task-v4)**,弱模型边界
同步定格。22 个测量发 + 1 基础设施中止,≈14.7M 读入,四条硬红线
全程为零,KB/主目录指纹全程逐字节一致。

| 任务版 | 发数 | 结果 | 版本差异(逐版仅改一层) |
|---|---|---|---|
| v1 | 7(批1 3+批2 3+补发 1) | 0 PASS | 原始冻结包 |
| v2 | 5+1 中止 | 0 PASS | oracle h5 布局锚定→行为版(挂起 LLM+SIGKILL 真崩溃) |
| v3 | 6 | 0 PASS | oracle h1 静态导入锚定→路由无关探子(热身+sys.modules 打桩) |
| v4 | 2+1(deepseek 补) | **gpt-5.5 PASS · gpt-5.6 PASS** · deepseek FAIL | 公开面 +2(报告保真/上游在场 lite),oracle 不变 |

**口径纪律**:各版 verdict 各自冻结、不互比不改写;n≤4/模型不排名;
v4 双 PASS 不得表述为"模型变强",只能表述为任务契约修正后的可解性。

## 二、§48 清单(25 项,合并口径)

1-4 Task:`t2-offerclaw-open-deep-research-v1..v4` · Host OfferClaw@85278e6
(副本 602 基线,三次确定)· Target ODR@20aaa0d · 包目录 4 个(v1 冻结
843d77d 起,逐版 oracle-only/公开面单层修订,均五对象验证后预注册);
5 正控:v1 10/10+10/10 → v4 12/12+10/10(每版复验);
6 负控:NC1-NC5 各版在预期绊线挂(NC1 v4 起双层被抓);
7 直连基线:公开 3/10(v1-v3)/3/12(v4),隐藏 1/10;
8-9 模型汇总与轮线:见上表与各批报告;关键单发——v2-order9(gpt-5.5
全绿唯 replay 死于一行非法声明)、v4-order20/21(双 PASS 全链);
10 FailurePacket:v1 批 1 run3 实证失败包驱动(1/10→10/10);v4 双 PASS
一轮无需修复;deepseek 八发中仅 T1-run2 转化过失败包;
11 Best State:全部为末轮/唯一轮;
12-13 回滚/Scope Change:22 发合计 rollback 2(T1 时代)/0(T2),scope 0;
14 能力:终态 PASS 2;能力链最强非 PASS 样本=v2-order9(10/10);
15 宿主回归:22/22 全绿(603≥602),零破坏;
16 Policy:拦截 3 发(补丁 2398/2360 超限 ×2、其一即 gpt-5.5 批1);
17 Replay:拦截 2 发(不可复现 pin/非法 URI),放行 2 发(v4 双 PASS,
全新会话+声明依赖重建);
18 Verdict 分布:2 PASS_ADAPTED / 20 FAIL / 1 INFRA_ABORTED(不入账);
19 成本:≈14.7M 读入 / ≈180k 产出 / agent 侧 wall ≈3.2h;单 PASS 成本
≈590k 读入一轮(两发几乎相同);
20 新 Failure:**回退式语义替代**(try 真图→except 静默自写,v3 批
4/6)——入 taxonomy 候选;依赖声明四败形态(不声明/错版本/错语法/
漏声明)及其对偶解(零新 pip:运行时 vendor/shim+注释);
21-22 Harness 增强(全部失败驱动+钉死测试+预注册):修订④观察限流
(T1 末)、**卫生门**(bench 根白名单,批 1 污染实证)、**修订⑤**单调用
超时(order13 挂死)、**修订⑥**oracle stdout 归档(取证两次重建之痛);
oracle 修复 ×2(h5/h1 锚定);方法论:LESSONS #14(agent 可达宇宙=
冻结面)#15(oracle 自持)#16(探子挂真实对象+超时执法)#17(公开面
=目标函数/隐藏面=防伪层);
23 Feature Transaction:未启用(PASS 产物停留在 EXPORT 阶段,写回
留给产品化;Unapproved Real Apply=0);
24 Rollback Readiness:未触发(无 Apply);
25 证据束:22 个 run bundle(trace 链全过)+ runs.jsonl 22 行 +
RAG 基线四时点(批前/终验×3)+ KB 指纹 5 时点全一致(74cd21c8/112)。

## 三、研究命题回答(源 §49 框架内)

- 多轮 Repair 是否改善:**是,当且仅当失败信号在公开面**(v1-run3 实证
  改善;v3 六发实证"隐藏面失败不可修"——结构性边界);
- 低成本模型可用成功率:**deepseek-v4-pro 在 task_shape 10-15 档为
  0/8,判否**;其失败被 harness 全程正确拒绝且宿主零损伤;
- 失败可解释性:22 发逐发有断言层归因(修订⑥后一条 grep 可达);
- 拒绝错误放行:19 次拒绝复核全部有理,False System Pass=0;
- **产品定位结论(用户 2026-08-10 确认):判定保证,而非成功保证**——
  错误结果零放行/失败可解释/成本有界/成功可信可复现;任务契约质量
  是可控放大器,模型构建力不是。

## 四、T3 转段准备清单(browser-use@3260188)

已就绪:宿主基线 85278e6+wheelhouse+引导手册(A 类预热清单含 e5 教训)
/ 卫生门 / 修订④⑤⑥ / 冻结管线与五对象验证方法论 / v3 协议。
待建(T3 特有,预估为 T2 任务工程 1.5-2 倍):
1. **mock_recruitment_site**(源 §45:字段全集+Trap Submit+DOM 重排
   +延迟渲染+Cancel+确认页——独立 fixture 工程,T3 最重件);
2. 嵌套 agent 双计量(coding_agent vs runtime_browser_agent,源 §19);
3. Irreversible Action Gate / PII 字段白名单 / 会话清理语义的 oracle
   设计(须过 #15/#16 自持审查:行为判据、挂真实对象);
4. 浏览器进程生命周期与 harness 超时的交互(修订⑤延伸);
5. 决策点:宿主基线沿用 85278e6(当前主仓 HEAD 未动)vs 届时最新
   (若用户 e5 修复会话落提交,重演 T2 的基线决策);T3 预算 §19
   (45 调用/150 命令/75min/800k)按正控实测再标定。
