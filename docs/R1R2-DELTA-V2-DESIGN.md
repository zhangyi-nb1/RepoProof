# R1/R2 设计:delta 任务构造法 v2(base 测试留树)+ prompt v2(2026-08-21)

状态:**设计冻结,未实现**。执行须在后续会话作为独立工程批(含宿主重建
仪式与新预注册);本文件是蓝图,不是预注册。授权链:用户 2026-08-21
"那为我开始修复吧…宗旨是提高项目harness下GPT模型的成功率以及其他效率"
(修复清单 R1/R2,最重故最后)。

## 1. 问题与证据(为什么是这两刀)

R3 分类学(bbd5169,19 发扫查)坐实:12 发砸回归**全部**落在剥离文件
`tests/test_lineage.py` 仅有的两个节点上,可见树桶 21 发累计为**零**——
没有任何模型任何一发砸过自己能运行的测试。两节点病理不同:

- `unpivot_with_alias_columns` = **STRIPPED_OLD_INTACT**(base==post 的旧
  测试,5/12 发砸):测试内容在 parent 公开树里就有,只因构造法 v1 把整个
  文件剥走,模型**够不着本可运行的回归网**。这是纯 harness 对齐缺口。
- `multiple_pivoted_sources` = **STRIPPED_NEW**(green-on-parent 新增,
  **12/12 发全砸**):PR 新增的、对既有行为的补测。内容=答案,结构性
  不可见。**R1 修不了这一类**——这是答案承载的不可约盲区。

结论先行:R1 只消 OLD_INTACT 类;对 NEW 类唯一合法杠杆是 R2 的教导面
(保守性 + 节点名单宣示)。v2 的成功率改善上界受 12/12 那一类压制,
设计时如实预期,不许事后惊讶。

## 2. R1:构造法 v2 —— base 版测试文件留树

### 2.1 现行机制(实读代码,2026-08-21)

- `prepare_hb1_hosts.py::construction_check`:推导 A = delivery ∩ parent
  − 字节码;推导 B = parent − .github/** − manifest.test_files −
  extra_drop − 字节码;两推导恰等才部署,内容一律取 parent 版。
  test_files 之所以从 V 消失,是因为**封存 delivery 本就无测试文件**且
  期望推导显式减去(8042:test_files=['tests/test_lineage.py'],
  extra_drop={'CHANGELOG.md'})。
- `delta_oracle_lib.run_delta_oracle`:H1 守卫(tests_tree_sha256 +
  guarded_root_files)→ 铺 post 测试(**dst 存在即
  LAY_TARGET_OCCUPIED,拒铺拒跑**)→ 子进程 pytest(env 净化 + 收集面
  限定)→ 冻结节点集读数 → finally 撤铺入文件 + pre/post tests_tree
  digest 复核还原。
- `build_hb1_task_packages.py` 生成 delta_manifest.json(post_files
  sha256、tests_tree_sha256 =构造后宿主 tests/ 摘要)。
- 三份 delta_oracle_lib 副本由 tests/test_hb_task_packages.py 钉逐字节
  等于本源。

### 2.2 v2 改动清单(五处,全部向后兼容)

1. **construction_check 加 law 参数**(纯函数,缺省 "v1" 字面不变):
   - law="v2" 时:推导 A' = (delivery ∩ parent − 字节码) ∪
     (test_files ∩ parent);推导 B' = parent − .github/** − extra_drop
     − 字节码(**不减 test_files**)。两推导恰等仍是 tripwire;部署内容
     仍一律取 parent 版 —— base 版测试文件自然落树。
   - CHANGELOG.md 照旧剥(extra_drop 不动:PR 叙述泄漏轴与测试无关)。
   - 单测:v1 期望集不含 tests/test_lineage.py、v2 期望集含之、两法在
     其余路径上逐字相等;变异钉(law 死作 v1)配套。
2. **delta_manifest.json 加两键**(build_hb1_task_packages v2):
   `construction_law: "v2"`;`base_files: [{path, sha256(parent 版)}]`
   (8042 恰一条)。tests_tree_sha256 照常重算,自动覆盖 base 文件 ——
   **H1 守卫因此免费扩展到它**:模型改 base 测试 = TESTS_TREE_MODIFIED,
   attribution=agent,现行执法零新码。
3. **delta_oracle_lib lay 步 manifest 驱动分支**(单一 master,三份副本
   钉不破;无 base_files 的 v1 manifest 走原语义,老包老运行零扰动):
   - manifest 含 base_files 且 dst 在场:**save 当前字节 → 覆写 post →
     判卷 → finally 还原 save 的字节**(还原的是"lay 前态"而非 base ——
     与 pre/post digest 复核语义严丝合缝;agent 若改过文件,H1 已红,
     此处照样判卷照样还原,归因不倒挂)。
   - manifest 含 base_files 但 dst 缺席(agent 删了它):照 v1 铺后删,
     并记 instrument problem `BASE_FILE_MISSING:<path>`(H1 桶,
   tests_tree 摘要同时已红 —— 双读数互证)。
   - LAY_TARGET_OCCUPIED 判定仅保留给 v1 manifest。
4. **新任务包 + 新宿主,旧代不动**:`benchmarks/v2/tasks/
   hb1_sqlglot_8042_v2/`(contract v2、statement v2、oracle v2 物化)、
   bench 目录 `hb1-sqlglot-8042-v2`(prepare --law v2 → lock →
   check_host_digest 登记新期望摘要)。v1 宿主/包/池原样封存,**新池
   不回填**,台账以 task_id 天然分池;E0/E1 永不互比条款照旧。
5. **答案安全复核**(设计内置,不留给现场):base 版 tests/test_lineage.py
   = parent 公开树内容,零新暴露;post 版照旧只走物化(gitignore);
   delta 节点**名单**已在公开 manifest,内容仍是答案。unpivot 节点
   base==post,其"答案"本就是公开的 parent 内容 —— v2 只是把公开事实
   还给模型。

### 2.3 不改什么(明确不做)

- 不改 v1 的任何判卷/构造行为(law 缺省 v1,manifest 无新键即老路)。
- 不动封存池(只读源);不动 v1 bench 宿主(连 unlock 都不需要 ——
  v2 是新目录新建)。
- 不把 multiple_pivoted_sources 或任何 post-only 内容以任何形式可见化。

## 3. R2:prompt v2(statement.md 三条新教 + 名单宣示)

1. **回归网宣示**:tests/ 里是上游完整套件的 base 版(含隐藏 delta 所在
   文件的 base 版);提交前跑全套件,砸任何现有测试 = FAIL,哪怕 delta
   全绿。
2. **量具面重申**(先教后杀,新诱惑面):不得改动 tests/ 与守卫根文件;
   判卷以出题态摘要执法,改测试不影响判卷、只会记为 agent 动量具。
3. **隐藏面保守性 + 节点名单宣示**(对 STRIPPED_NEW 类的唯一杠杆):
   判卷额外运行隐藏 delta 节点,**名单如下**(节点名公开,内容隐藏):
   五个 chained_pivots 节点逐字列入 statement;并教"隐藏套件含对既有
   行为的补测,修改须语义保守,建议对改动路径自写探针验证"。
4. 版号:prompt_profile=hb-delta-v2,与 task_id/contract 一起进台账与
   回执面,杜绝跨代合池。

## 4. 执行序(下一场,独立工程批)

① construction_check v2 + 单测 + 变异钉 → ② build v2 包(manifest 新
键)+ delta_oracle_lib 分支 + 单测(v1/v2 双路)+ 副本钉重跑 + 变异钉
→ ③ prepare --law v2 建 hb1-sqlglot-8042-v2 → lock → check_host_digest
登记 → ④ statement/contract v2 → ⑤ F0(--fake positive)验管线 →
⑥ **另立预注册**(基线批,off 投影按 R4 结论;n 与封套现场冻结)→
⑦ 机制三问:OLD_INTACT 类是否消失(unpivot 不再砸)/名单宣示是否
提升 delta 命中/multiple_pivoted 是否仍砸(仍砸 → harness 侧到边,
病灶转模型侧/任务构造侧,如实记)。

## 5. 判读上界(预写,防事后拉伸)

单任务 seen、新代际首批 n 小;v2 vs v1 成功率差 = 机制读数不是能力
读数;不与 v1 数值合池;multiple_pivoted 类改善不归 R1(它够不着),
只可能归 R2 教导面,归因时分开写。
