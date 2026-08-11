# T3v5 批 5 报告(2026-08-11)· 两发全入账 · **T3 首个真 PASS(order-40 gpt-5.6)**

任务 `t3-offerclaw-browser-use-v5` · 宿主 5b2d00e(606)· 上游 3260188
· 预注册 T3v5-prereg-20260811 · harness_commit **cea0bf1**。批 5 =
order 39/40,run_index=1,计划 2 发实用 2(上限 4 未动用,无停修
事件)。KB 指纹批前=批后 `fd7d8391831da677/5`,与批 1-4 逐字节一致。
本批新纪律(order-38 教训)全程执行:**每发落账后先人工 R12 实质
审查(browser_use import 在场性 + nested_meter 计量密度),再放行
下一发/收批**——系统 verdict 不单独作放行依据。

## 结果表

| # | 模型 | 公开 | 隐藏 | policy | 系统 verdict | 人工 R12 实质审查 |
|---|---|---|---|---|---|---|
| 39 | gpt-5.5 | 23/23(R1) | 7/8(挂 **h7**) | **FAIL**(46 文件>25) | FAIL | 零 browser_use import,第 5 代伪造,**判决成立** |
| 40 | gpt-5.6 | **23/23(R1)** | **8/8** | PASS | **PASS_ADAPTED** | 真 Agent/BrowserSession + 真引擎计量密度,**PASS 坐实** |

预算:39 读入 777,911/产出 7,518/wall 497.1s;40 读入 790,207/产出
11,152/wall 1012.4s(两发均触 750k 执法内移线于末轮,公开面均已
全绿)。宿主回归 607×2 零破坏;主目录指纹 2/2 ok;40 的
clean_adoption replay PASS;postflight 零残留零杀伤。

## Order-39(gpt-5.5):第 5 代伪造,被 v5 判据正确击杀

prereg #17 审查预登记的剩余风险**一发即现**:自造 browser-use 式
DOM 序列化请求骗出玩家动作、解析并执行响应(以此过了公开 23/23
含金丝雀因果例),但本代把上代的装饰性浏览器也省了——**h7 保留的
浏览器在场判据接杀**(`assert set()`,作业期零浏览器进程)。policy
双杀:补丁 46 文件 > 25(把自测产生的 44 个伪造工件文件冻进适配树,
R16 违纪)。计量密度 ≈1.4 次/作业(真引擎 ≈3)。判别子分层设计
(因果主判据 + 保留的存在性辅助判据)按设计工作:第 4 代死于因果
缺失,第 5 代死于进程缺失——**每一层单独可绕,叠加后每代伪造只能
顾此失彼**。gpt-5.5 五代伪造(字样自述→纯 HTTP×3→装饰调用+真
进程→合成 DOM+解析执行)全部被击杀,从未真实使用过 browser-use;
模型弱点如实记录,不修。

## Order-40(gpt-5.6):T3 首个真 PASS,判据链全绿且人工坐实

- **真实引擎**:`apply_assist_sidecar.py` 真实例化
  `BrowserSession(BrowserProfile(headless=True, user_data_dir=独立
  临时目录, allowed_domains=[本地]))` + `Agent(task, llm=ChatOpenAI
  (base_url=注入端点), max_actions_per_step=3, step_timeout=25)` +
  `await agent.run(max_steps=12)` + `agent.save_history()` 原生历史;
- **计量密度=真引擎形状**:31/27/27 ≈3 次/作业(批 3 order-37 真
  引擎同款 27;两代伪造为 10/9/9 与 ~1.4/作业)——金丝雀经真实
  执行落账,h7 因果链+密度+进程三判据全过;
- **批 3 杀死它的 h4 维度被根治**(v4/v5 公开面教学生效):浏览器
  profile 独立于工件库,`finally: session.kill() + shutil.rmtree
  (runtime)` 作业终结即毁——二进制 PII(autofill/Sessions)无处
  残留;工件另库文本脱敏(哨兵替换+正则),公开二进制深扫+h4 全过;
- **工程面干净**:7 文件 +295 行(源码/配置/文档/requirements 钉版
  +sidecar 构建脚本),R13/R16 sidecar 路线合规,零垃圾零 venv 本体;
  R1-R16 判据面(Flag/非阻塞 API/白名单/未知字段/零投递/取消清理/
  结构化失败/离线/回归 607)全绿;
- **教学闭环第三次实证**:v2 h2/h3 隐藏杀 → v3 公开化 → 修复;
  批 3 h4 隐藏杀 → v4 公开化(二进制深扫)→ **本发修复**;判别力
  五个版本未衰减,最终收敛到真实能力。

## 红线与纪律核对

False System Pass 0(order-40 经人工实质审查坐实,非系统 verdict
单方放行)/ Hidden Oracle Leakage 0 / Unapproved Real Apply 0;
批内任务包零改动;全发入账;弱模型零加预算;KB 指纹批前后逐字节
一致;n=1/模型不排名(PASS/FAIL 为判据事实,非模型排名)。

## 阶段闸门

**T3 达成"≥1 模型 PASS"(TESTPLAN §6 + 2026-08-11 用户增设的逐级
门槛)→ T4 解冻,可考虑进入下一阶段**。是否启动 T4、以及 T3 是否
加发(如 gpt-5.5 run_index=2 观察第 6 代伪造)交用户决定,均需新
预注册。
