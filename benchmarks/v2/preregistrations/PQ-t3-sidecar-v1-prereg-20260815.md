# 预注册:T3-SIDECAR v1 首批(2026-08-15)

> **修订 A(2026-08-15,开跑前)。** 本预注册初版冻结后、**任何计分发次开跑
> 之前**,可搬运性审查(§8 的强制前置)查出四条 blocking。任务包与 harness
> 据此加固,`contract_sha` 由 `b8e48f16…` 之前的值变为 `b8e48f160061ba85`。
>
> **改在开跑前,不作废任何东西** —— 盘上此前四发全是 `fake-scripted` 冒烟。
> 若在开跑后再改,整批作废。改动清单见 §9;判据 Q1–Q6 与停批线**一字未动**。

**测试模式:PQ(Runtime Profile Qualification)—— 新增模式,本批是第一次用。**

九模式(TESTPLAN §11)里没有一条覆盖"一个 runtime profile 能不能被真实模型
用起来"。硬塞进现有模式都会说错话:

- 记成 **HB**(未见任务基准)不成立 —— 同一个宿主(offerclaw),不是第二宿主;
- 记成 **E1**(执行器消融)不成立 —— 没有 A/B 两臂,不在做消融;
- 记成 **DQ**(provider 资格)不成立 —— 资格审的对象是 profile,不是 provider。

所以另开一条,并把它的**结论边界写死**(见 §5)。

**任务包** `benchmarks/v2/tasks/t3_sidecar_v1`,**一字不动**(§39)。
**runtime profile** `rt-sidecar-browser-v1`(lifecycle=candidate)。
**封存 runtime** browser-use 0.13.7 @ `32601887cfbc` + Chromium build 1234
(Google Chrome for Testing 151.0.7922.34),清单摘要见
`~/RepoProofRuntimes/rt-sidecar-browser-v1/runtime_manifest.json`。

---

## §1 要回答的问题

**只有一个**:

> 真实模型能不能读懂 RPC 协议、写出 Adapter、并把上游的产物**真正用进交付**?

不问"哪个模型更强"(样本量与任务性质都不支持),不问"sidecar 拓扑比
in-process 好"(那要 WH/HB 对照,第二宿主还没建)。

## §2 为什么必须跑真的

profile 已经过了 G1–G5(零模型):拓扑成立、诚实实现不被误杀、八条攻击各红各
位、变异全捕。但那**全部是我们自己写的 adapter 跑出来的** —— 参考实现是照着
判据写的,那叫**出题人自己会做**,不叫题目可解。

G6 因此要求真实发次:≥2 个模型 profile,且**至少一发诚实通过**。这是
`candidate → qualified` 唯一还差的一条。

## §3 设计

| | |
|---|---|
| 模型 | `gpt-5.5`、`gpt-5.6`(经 `REPOPROOF_MODEL` 选) |
| 每模型发次 | **2**(共 4 发) |
| 执行序 | 交替:5.5 / 5.6 / 5.5 / 5.6 —— 防"某段时间 provider 状态好"变成模型差异 |
| 额度 | 契约冻结值:3 轮 × 30 调用 / 100 命令 / 60 分钟 |
| harness | 冻结于本预注册提交时的 HEAD;记进台账 |

**n=2 的诚实含义**:够回答"能不能",不够回答"多大概率"。批报里**不得**出现
通过率、不得排名(§n<3 不排名,常设纪律)。

## §4 判据(先冻结,措辞此后不改)

### 主判据

- **Q1 可解性**:≥1 发达到 `PASS_ADAPTED` 且**回执核验四道谓词全过**。
  这是 G6 的核心:题目对真实模型可解。
- **Q2 采纳真实性**:凡是 `PASS_ADAPTED` 的发次,`receipt_verification.ok`
  必须为真。**verdict 与回执核验不一致时以回执为准并当场作废该发** ——
  oracle 只验行为,它给绿不代表用了上游。
- **Q3 归因清晰**:每一发 FAIL/BLOCKED 都能归到以下之一,不得出现"说不清":
  `MODEL_DID_NOT_SOLVE` / `RECEIPT_VERIFICATION_FAILED(附具体谓词)` /
  `HARNESS_FAILURE(sidecar 起不来 / 取件失败 / 核验器出错)`。
  出现说不清的,**该发作废**并记为 harness 缺陷。

### 副判据(不达标不阻断,但要写进批报)

- **Q4 无假通过**:没有任何一发 oracle 全绿而回执核验红 —— 若出现,那是
  **判据层面的重大发现**(两层判定之间有缝),必须立刻停批并修。
- **Q5 无误杀**:没有任何一发因**判据过严**而失败(诚实实现被判死)。判定
  办法:人工读该发的 `adaptation.patch` 与回执核验明细。
- **Q6 令牌零泄漏**:所有发次的工件里都不含 sidecar 令牌。

### 停批线

任一条触发即**停批、不补发**:

1. 出现 Q4 型假通过(判据有缝);
2. 连续 2 发 `HARNESS_FAILURE`(harness 不稳,数据无意义);
3. 封存件摘要在批次期间变化(`verify_sealed` 报被动过)。

## §5 结论边界(这批**不能**说什么)

- **不计模型能力。** T3-SIDECAR 的 oracle 与判据是我们自己写的,它属开发套件。
  `counts_toward_model_capability: false`。
- **不与 T3-INPROC 比较。** 两支 `task_family` / `adoption_shape` 不同,能力
  定义已经变了(用户 2026-08-14 指令)。成绩永不混合。
- **不外推到第二宿主、未见任务、DeepSeek-native 路径。**
- 通过不等于"sidecar 拓扑更好" —— 那是 WH/HB 要回答的,本批不涉及。

## §6 发次分类(先写死,发完照此登记)

```
run_purpose: RUNTIME_PROFILE_QUALIFICATION
test_mode: PQ
task_seen: false            # 模型没见过这道题(它是新建的)
counts_toward_model_capability: false
counts_toward_heldout_benchmark: false
counts_toward_mechanism_effect: false
counts_toward_profile_qualification: true
classification_timing: PRE_REGISTERED
```

`task_seen: false` 但 `counts_toward_model_capability: false` —— 两者不矛盾:
模型确实没见过这道题,但**我们**见过(是我们出的),而判据是我们照着自己的
参考实现调出来的。要谈能力,得换我们没参与出题的任务。

## §7 跑法(逐字记录,便于复核)

```bash
set -a; . ./.env; set +a
for i in 1 2; do
  REPOPROOF_MODEL=gpt-5.5 .venv/bin/repoproof host-run \
    --contract benchmarks/v2/tasks/t3_sidecar_v1/contract.yaml \
    --batch PQ-T3SIDECAR-1 --run-order $((2*i-1)) --run-index $i
  REPOPROOF_MODEL=gpt-5.6 .venv/bin/repoproof host-run \
    --contract benchmarks/v2/tasks/t3_sidecar_v1/contract.yaml \
    --batch PQ-T3SIDECAR-1 --run-order $((2*i)) --run-index $i
done
```

## §8 前置条件(全部满足才开跑)

- [ ] 可搬运性审查完成,blocking 项清零(LESSONS #43 纪律)
- [ ] 变异闸门 100%
- [ ] 全套测试绿、`check_public_claims` 绿
- [ ] `verify_sealed` 报封存件完好
- [ ] 本预注册已提交(harness commit 记进台账)


---

## §9 修订 A:可搬运性审查查出的四条 blocking(开跑前修完)

审查方式:六个独立视角对抗性攻击(缓存复用 / 部分采纳 / 取件器博弈 /
两层判定之间的缝 / **误杀侧** / 归因混淆),每条发现再由独立的反驳者复核。
45 条提出,33 条经反驳后仍成立。**四条 blocking 全部由我独立复现后才动手改**
—— 转述不算数。

### B1 洗白:sidecar 沦为"任意内容的签名机"

U3 按 `(nonce, input_digest)` 配对,而 U4 只按 nonce 配 —— **两条判据可以由
两张不同的回执分别满足**。对契约给的 URL 调一次喂饱 U3,再用**同一个 nonce**
对自造的 `data:` URL 调一次拿到一张为自造内容签名的回执,交后者的产物喂饱 U4。

复现结果:`PASS,零红`。修法:U4 只认 `input.digest` 等于该项应有输入的回执。

### B2 少交:U4 的分母来自被测方

原分母是 `len(delivery)`。每项都正确调用,只交其中一项 —— `PASS,零红`。
这与本项目自己写过的"分母若来自被测方,象征性调一次永远抓不住"是同一个错,
只是从 U3 搬到了 U4。修法:分母改用 harness 的待办清单。

### B3 空产出:空对空

`CANON_TEXT_SQUASH` 删光空白,于是 `""` / `"  \n"` / 缺键三者同摘要;而 worker
找不到 `#answer` 时返回空串**且不抛**,sidecar 照样签一张 `digest_of("")` 的
合法回执。两边一对,`PASS,零红`。修法:空产出不是采纳凭证;`facts` 非字符串
**判红并归因被测方**,不许抛成 `RECEIPT_VERIFIER_ERROR`(那会把被测方的畸形
工件记成 harness 自己坏了)。

### B4 预取硬编码:回执只证明"会话里有人调过"

oracle 构造 URL 的写法与 harness 生成项的写法**逐字相同**,而
`REPOPROOF_FIXTURE_URL` / `REPOPROOF_ITEM_NONCES` 原本给了 agent。于是 agent
在 round-1 就能算出 oracle 将来要抽哪些页面、提前各调一次、把事实写死进源码
—— 交付代码一次 RPC 不发,四道谓词全绿。sidecar 会话每发次只起一次、台账跨
全部轮次累计,回执早就躺在里面了。而且猜错格式零代价,"多猜几种预取"是严格
占优策略。

修法两条,缺一不可:①`agent_env` 砍掉那两项,另开 `oracle_env`;
②oracle 起跑那一刻 `rotate_items()` 现摇一批 agent 没见过的项 —— 砍环境变量
只挡住"直接读",还得挡住"猜"。

### B5 早轮残留(**误杀侧**)

取件器把交付目录下**全部** json 一网打尽,而每轮 `git add -A` 让它们变成
tracked 文件长久留在工作区。修复循环的全部意义就是允许 round-1 是错的:
round-1 落坏事实、round-3 改对再落好的,终局取件把两批一起交上去 → U4 红,
措辞与"调了但没用"一字不差,**而最终交付物其实是完美的**。契约里没有一个字
说"清理旧作业",oracle 全绿也不给反馈,判死发生在 agent 看不见的 harness 侧
—— 正是循环与闸门不对齐。修法:oracle 之前由 harness 清场(纯 harness 动作,
不改 patch;清哪个目录由任务包声明,不扫目录)。

### B6/B7/B10 契约缺陷:用未言明的要求判人

交付落点 `page_facts_jobs/<job_id>.json`、开关名 `OFFERCLAW_PAGE_FACTS`、
两个端点的请求/响应形状 —— 这三样原先**只存在于 harness 侧的取件器与 oracle
里,契约一个字没提**,而它们决定生死。补进 R8/R9/R10。

**这不是放宽判据,是把本来就在判的东西说出来。** 红了也无从预防,那是判据的
缺陷,不是被测方的。

### B8 公开面是空的

原先 `public_tests/` 无文件,agent 三轮零反馈,而失败记录与"模型公开面全挂"
逐字段同型 —— 台账里已有真实模型的同签名行,混进去没人分得开。补 7 条公开
测试(只验形状,不验采纳 —— 采纳要回执,回执在 harness 侧)。

### 修好了的证据(不靠"矩阵还绿")

新增三条负控,**修前实测全是零红通过**:

| 负控 | 修前 | 修后 |
|---|---|---|
| `nc5_launder_forged_input` | PASS 零红 | FAIL,**只红 U4.adoption** |
| `nc6_partial_delivery` | PASS 零红 | FAIL,**只红 U4.adoption** |
| `nc7_blank_output` | PASS 零红 | FAIL,**只红 U4.adoption** |

误杀侧同时复验(三种诚实形态仍全绿):基线、**oracle 三次提交(每 nonce 3 张
回执)**、无害空白整理。审查明确否掉了"每 nonce 只许一张"的改法,就是因为它
会误杀第二种。

另加**谓词级单测**(S7–S15):直接喂 `_make_per_unit_adoption`,不只靠矩阵的
落盘证据 —— 两条路互为冗余时,把其中一条掏掉没人看得见(M50a 的教训)。

端到端复验:`host-run --fake positive` → `PASS_ADAPTED`,公开面 7/7、
oracle 4/4、重放 PASS、回执 13 条四道谓词全过,**且一轮就过**(公开面给了反馈)。

### 仍未修的(写进批报的诚实边界)

审查另给了 S1–S6 六条 should-fix。它们不阻断开跑,但必须在批报里写明:

- **S1**:上游执行失败(封存 Chromium 超时/崩溃)以 HTTP 400 回给被测方且
  harness 侧不留痕 → 终点是 U3 报"没调上游",而模型看见 400 会合理地改走
  自抓 → 归成"重实现"。**归因会反**。凡 U3 红的发次需人工核 sidecar 日志。
- **S2**:U2/U3/U4 判红走 `missing_external` → 短路成 `BLOCKED`,与"profile
  没登记""宿主基线不健康"同桶。**请勿按 verdict 统计成功率**,需按
  `receipt_verification.reason` 二次分类。
- **S3**:oracle 之后、取件之前还有 `_run_regression` 窗口(agent 可写
  `tests/`,且带着 sidecar 令牌)。交付未绑定到 oracle 观察窗口。
- **S4/S5/S6**:取件器的归因桶会吸收一部分被测方形状错误;h3 令牌扫描整棵
  host(含 1.8G venv,实测 12s);落盘工件计入 patch 预算。

这六条**下一轮修**;本批报必须逐条抄上。
