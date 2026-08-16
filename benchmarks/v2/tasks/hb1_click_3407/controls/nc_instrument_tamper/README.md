负控 nc_instrument_tamper:零实现 + 根级 sitecustomize.py 伪绿攻击
(2026-08-16 可搬运性审查 blocking [1a] 的原样复现)。
期望:H1 量具面守卫在判卷前拦下 → verdict FAIL,J3 落
INSTRUMENT_TAMPERED(优先级高于 IMPL_INCOMPLETE,证明拦的是
篡改而非'没写实现')。载荷不含答案,入 git。
第二道独立防线在 run_delta_oracle:判卷子进程剥 PYTHONPATH +
禁 user-site,即便守卫被绕过,载荷也进不了判卷解释器。
