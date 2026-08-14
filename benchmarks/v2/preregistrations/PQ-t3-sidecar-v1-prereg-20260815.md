# 预注册:T3-SIDECAR v1 首批(2026-08-15,冻结后不改)

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
