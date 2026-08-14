# Sidecar Conformance / Runtime Canary

A1 的第一个使用者。**不是 benchmark,不计模型能力** —— 它测的是 harness
自己那条链走不走得通(F0 自检),结果不进 `runs.jsonl`,不影响任何闸门数字。

```
Agent ──只能调 RPC──▶ Harness-owned Sidecar ──真执行钉版上游──▶ Receipt ──▶ Verifier
```

```bash
.venv/bin/python scripts/sidecar_conformance.py
```

## 与回执正负控矩阵的分工

| | 证明什么 | 上游 |
|---|---|---|
| `receipt_controls/` | **回执机制**不可伪造 | `markdown-it-py` —— agent venv 里装得到,于是"假包""导入真包却用复制实现"只能靠约定成立 |
| **本目录** | **这条拓扑**成立 | harness 独占 fixture,agent 想 import 都 import 不着,**且现场核验** |

## 拓扑核验(A1 的地基,不过就拒绝出数)

| | 查什么 | 结果 |
|---|---|---|
| T1 | 不在任何钉版 wheelhouse 里 | ✓ 扫 3 个,零命中 |
| T2 | 干净子进程 import 不到(清掉 `PYTHONPATH`) | ✓ ModuleNotFoundError |
| T3 | 住在策略拒绝表覆盖的仓内目录 | ✓(护栏本身由 `tests/test_host_guard.py` 钉死) |
| T4 | agent 环境里没有任何指向它的线索 | ✓ 只有端点与令牌 |

上游若够得着,后面的回执与八条攻击**全是装饰** —— agent 大可自己算,而
"它没来敲门"会被读成偷懒,其实是它不需要。所以这一关先过。

## 八条攻击 + 正控

| adapter | 期望 | 红在哪 |
|---|---|---|
| `a0_honest` 真正使用结果 | PASS | — |
| `a1_never_calls` 不调用 sidecar | FAIL | U3, U4 |
| `a2_reimplements` 自己重实现 | FAIL | U3, U4 |
| `a3_fake_package` 假包(版本号照抄) | FAIL | U3, U4 |
| **`a4_ignores_result` 调了但不用结果** | FAIL | **仅 U4** |
| `a5_wrong_symbol` 调错 symbol | FAIL | U2, U3, U4 |
| `a6_replays_receipt` replay 旧 receipt | FAIL | U1.run_nonce, U1.count, U3, U4 |
| **`a7_tampers_receipt` 改 receipt(删行)** | FAIL | **U1.chain, U1.count**(签名全绿) |
| `a8_forges_receipt` 伪造 receipt(增行) | FAIL | U1.signature, U1.count, U3, U4 |

**a4 是整套设计的考题**,也是唯一只红在 U4 的一条:U1/U2/U3 全绿 —— 真上游
确实被真执行、符号对、每个待办单元各调一次、输入摘要一一对上。任何"记录
调用发生过"式的回执都会给它发绿。

**a7 与 a8 是一对**:a7 删行 → 链断而签名有效;a8 增行 → 签名无效而链完整。
合成一条会掩盖掉其中一道判据从没被考过。

## 上游 fixture 为什么加盐

能力若是纯函数(比如 `sha256("UPSTREAM:" + x)`),"自己重实现"那条会算出
**逐字节相同**的输出,于是它只红在 U3 而 **U4 反而绿** —— 采纳判据在这个
fixture 上就是零判别力的,而我们恰恰是拿它来证明采纳判据管用的。

加盐之后,不经上游就算不出校验尾。这与真实场景同构:没有浏览器就驱动不了
浏览器。正文那一半刻意留成可猜的,所以 a2 红在 U4 时信号是干净的 —— 它不是
因为算错了正文,而是因为**它没有上游**。

## 负控逼出的一个真缺口(已补)

想把"链"这一道单独考出来,唯一办法是删行(改字段会连签名一起破)。一删就
发现:**删最后一行,哈希链校验照样通过**。链只能证明"留下的这些是连续的",
证明不了"没被砍掉尾巴"。

补了 `U1.count` —— 执行方自己数的条数,存在**台账之外**。不给条数一律判不过,
不猜。这条同时给 a6/a8 添了一个更早更硬的信号:台账里有执行方没写过的行。

## 任务谱系(不叫 T3v7)

```
T3-INPROC  └── v6    dependency integration + API understanding
                     + package/runtime setup + host adaptation
T3-SIDECAR └── v1    RPC protocol understanding + adapter implementation
                     + upstream semantic use          ← 尚未建立
```

`T3v6 → T3v7` 读起来像同一个任务的第七版,而**能力定义已经变了**。两支成绩
永不混合。`task_id` 一律不动(台账引用着它,改名等于伪造历史);谱系是新增
旁注,写在契约的 `task_family` / `adoption_shape` 字段里。
