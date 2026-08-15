# 差分注入专用控制组

**不放在 `controls/` 里,是有意的。** 那个目录被金丝雀矩阵
(`scripts/verify_receipt_controls.py`)整目录扫,而那张表没有"模式"的概念 ——
每个控制组一个固定期望。

这里的控制组期望**随模式而变**:

    nc9 / plain      → PASS 零红      (A1 结构上限成立的现场证据)
    nc9 / perturbed  → FAIL,只红 U4  (差分注入堵上了)

放进 `controls/` 的话,金丝雀矩阵会把它当成"一个通过了的负控"—— 那是这套
证据里最容易被误读的一句话。

驱动它的是 `scripts/differential_injection_matrix.py`。
