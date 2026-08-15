# 批报:PQ-T3SIDECAR-1(2026-08-15)

预注册:[`PQ-t3-sidecar-v1-prereg-20260815.md`](../preregistrations/PQ-t3-sidecar-v1-prereg-20260815.md)
(判据 §4 冻结于 `9d52121`,修订 A/B 只动执行与记账,**判据一字未改**)

harness:`32d16228f59ccc989905f3a20ebd7183b68deaa0`(四发台账自述一致)
runtime profile:`rt-sidecar-browser-v1`,browser-use **0.13.7**,
`artifact_hash sha256:a8262f515b77dba6c…`,封存 Chromium,批次前后
`verify_sealed` 均报完好。

---

## §1 结果

| order | 模型 | 公开逐轮 | 轮数 | oracle | 重放 | 回执 | 台账 | verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | gpt-5.5 | [7] | 1 | 4/4 | PASS | **U1–U4 十项全绿** | 15 | **PASS_ADAPTED** |
| 2 | gpt-5.6 | [7] | 1 | 4/4 | PASS | **U1–U4 十项全绿** | 16 | **PASS_ADAPTED** |
| 3 | gpt-5.5 | [7] | 1 | 4/4 | PASS | **U1–U4 十项全绿** | 15 | **PASS_ADAPTED** |
| 4 | gpt-5.6 | [7] | 1 | 4/4 | PASS | **U1–U4 十项全绿** | 16 | **PASS_ADAPTED** |

零回滚、零 policy 违规、零 denied。模型调用 11–14 次、命令 11–21 条,
壁钟 494–570 秒 —— 全部远在契约冻结的 3 轮 / 30 调用 / 100 命令 / 60 分钟之内。

### 判据结论

| | 判据 | 结论 |
|---|---|---|
| Q1 | 可解性:≥1 发 PASS_ADAPTED 且四道谓词全过 | **通过**(4/4) |
| Q2 | 采纳真实性:凡 PASS_ADAPTED 者 `receipt_verification.ok` 必真 | **通过**(4/4 为真,无一需作废) |
| Q3 | 归因清晰:每一发 FAIL/BLOCKED 都归得掉 | **未被检验**(零 FAIL、零 BLOCKED) |
| Q4 | 无假通过:无 oracle 绿而回执红 | **通过**(0 例) |
| Q5 | 无误杀:无诚实实现被判死 | **未被检验**(零失败发次) |
| Q6 | 令牌零泄漏 | **通过**(独立复扫,见 §3) |

三条停批线一条未触发。

---

## §2 这批到底证明了什么

**真实模型能读懂 RPC 协议、写出 Adapter,并把上游的产物真正用进交付。**
G6 差的就是这一条,现在有了 —— 而且不是"跑通一次",是两个模型各两发、
四发同型。

`rt-sidecar-browser-v1`:**candidate → qualified**
(G1–G7 全过,留痕 `docs/evidence/profile_lifecycle/promotions.jsonl`)。

### 强度只到一半 —— 必须写在前面

四发全部**一轮即过**,于是:

- **Q3(归因清晰)与 Q5(无误杀)一次都没被检验。** 判据在"判失败"这一侧
  的行为,这批完全没有现场实例。整个 S1/S2 归因分流(修订 B 的主体)在真实
  失败上**从未运行过** —— 它只在合成钉死里跑过。
- 与批 7 同型的老毛病:**"不再扣分"兑现了,"该判死的判得死"仍缺现场实例。**
  这不是可以靠再跑几发补上的 —— 得有真会失败的发次,或专门的诱导设计。
- 公开面 7/7 一轮到手,说明**公开测试把形状交代得很清楚**。这对可解性是
  好事(判据不是墙),但也意味着这批**测不出**"模型能不能自己想明白要
  调上游"。

### 预取硬编码在这批里被结构性排除

回执里出现的 `request_nonce` 是 `item-1-c2ef9e7bf299` 这一类 ——
`rotate_items()` 在 **oracle 起跑那一刻**现摇的,写代码时还不存在。
所以"提前把答案算出来写死进源码"这条路(审查 B4)在这批里不是"没人走",
是**走不通**。四发的 patch 我逐份读过:全部是老老实实的 RPC 客户端,
没有 fixture 基址、没有硬编码事实。gpt-5.5 那份还主动把令牌从异常串里
redact 掉了。

---

## §3 独立取证(不靠 oracle 自述)

- **令牌零泄漏**:令牌 = `"tok-" + run_nonce[:16]`,run_nonce 从回执现算,
  逐字节扫四个 run 目录全部文件(29 / 36 / 29 / 39 份),**零命中**。
  这条独立于 oracle 的 h3 —— h3 扫的是会话内,这里扫的是落盘工件。
- **上游身份**:四发的 `upstream.artifact_hash` 完全一致,且等于封存件现算值。
  自带同名包骗得过 `__name__`/`__version__`,骗不过它。
- **符号**:15/16 条回执全部是 `browser_use.BrowserSession.render`,无杂项。
- **台账追加性**:`runs.jsonl` 本次 diff 为 `4 ++++`,无改写。

---

## §4 跑这一批撞出来的两条闸门缺陷

都不是模型的问题,是**我们自己的**。两条都是"判据长得对、其实不干活"。

### M58a:G6 是一条永不可满足的判据

`_check_real_runs` 读 `runtime_profile`,而 `bench_records.py` 的白名单里
写的是 `runtime_profile_id`。少个后缀 → **任何** profile 的 G6 恒为 0。

最难看的地方是**它的失败长得跟成功前的样子一模一样**:报"只有 0 个模型
跑过",而这句话在跑之前也是对的。要不是这批真跑完了还报 0,它可以一直
这么待着。

G1–G5 全是负控(八条攻击各红各位、变异全捕),**没有一条验过 G6 能过**。
这就是 LESSONS #44 的原话:判别力靠负控验,**可满足性只能靠正控验**。
补 `test_p4c`(正控 + 四条判别力反例)。

### M58b:PQ 发次把阶段闸门抬高了

`_denominators` 里白纸黑字:"PQ:runtime profile 资格审 —— **不充闸门、
不计模型能力**"。而扣除逻辑只认 `MECHANISM_PURPOSES`,PQ 不在里面。
于是这四发直接把 **T3 的 passes 从 3 抬到 7**。

**散文说不算,代码算了。** 方向尤其难看:profile 资格审自己抬高了阶段
闸门,而资格审存在的全部理由恰恰是"这个 profile 还没资格被当数"。

修法:新增 `QUALIFICATION_PURPOSES` 与 `NON_GATEABLE_PURPOSES`,
**不**塞进 `MECHANISM_PURPOSES`(那个数字有自己的含义,拿一个错标掩盖
另一个不算修)。补 K7(合成)与 K7b(真台账现场)。

修复后:T3 passes = 3,`pass_run_ids` 里没有任何一发 PQ,
`profile_qualification_runs` = 4,`gate_met` 不变。

变异登记簿 127 → **129**,`1b181d3` 上全捕。

---

## §5 这批**不能**说什么

照 §5 原文,一条不减:

- **不计模型能力。** T3-SIDECAR 的 oracle 与判据是我们自己写的,属开发套件。
  四发的分类均为 `counts_toward_model_capability: false`。
- **不排名、不报通过率。** n=2/模型,§n<3 不排名是常设纪律。两个模型
  4/4 同型,这批说不出任何"谁更强"。
- **不与 T3-INPROC 比较。** 两支 `task_family` / `adoption_shape` 不同,
  能力定义已经变了。成绩永不混合。
- **不外推**到第二宿主、未见任务、DeepSeek-native 路径。
- **通过 ≠ sidecar 拓扑更好。** 那是 WH/HB 要回答的,第二宿主还没建。
- 新增一条:**这批没有检验判据在失败侧的行为**(见 §2)。凡引用"归因清晰"
  的地方都要带上这句。

---

## §6 台账登记

四发按预注册 §6 逐字登记进 `run_classifications.jsonl`:

```
test_mode: PQ                                run_purpose: RUNTIME_PROFILE_QUALIFICATION
task_seen: false                             counts_toward_model_capability: false
counts_toward_heldout_benchmark: false       counts_toward_mechanism_effect: false
counts_toward_profile_qualification: true    classification_timing: PRE_REGISTERED
```

## §7 下一步

1. **失败侧还是空的。** Q3/Q5 要现场实例,得设计会失败的发次(或等自然出现)。
   在那之前,S1/S2 的归因分流只有合成证据。
2. `rt-sidecar-browser-v1` 已 qualified,但 **default 不由机器判**(G8)——
   要不要设默认是取舍,得人来定。
3. WH/HB 对照仍缺第二宿主。
