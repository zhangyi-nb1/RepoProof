# M4 批次二预注册:M4-TOOL-ONBOARDING-2 · 2026-08-23(冻结,待批准开跑)

## 一、目的

规模化验证:在批次一(12/12 READY)与 DS 对比批(11/12)之后,再冻结
12 仓走同一条 `tool add → 人闸 → tool build` 流水线,难度轴适度上探
(结构化输入域、中文处理域、二进制嗅探域),四指标同口径累计。

## 二、选取口径(先于任何 intake 结果声明)

1. 纯 Python、pip 可装、零系统库依赖(libmagic 类排除);
2. 能力一句话化、单文件输入→stdout 输出(RFC-010 工具形状不变);
3. 与批次一 12 仓、pdf-table、html2md **能力域零重复**;
4. 成熟稳定仓优先(接受"久未更新但事实标准",如 jieba);
5. 难度上探:结构化解析 ×2(TOML/XML)、中文域 ×3(拼音/分词/简繁)、
   全域合法输入 ×1(filetype,预期走 malformed_applicable=False 豁免)。

## 三、冻结清单(12 仓,顺序即执行序)

| # | 仓 | 能力(一句话) |
|---|---|---|
| 1 | hukkin/tomli | 把 TOML 配置文件解析为 JSON |
| 2 | martinblech/xmltodict | 把 XML 文件转为 JSON |
| 3 | mozillazg/python-pinyin | 把中文文本逐行转为拼音 |
| 4 | fxsjy/jieba | 把中文文本逐行分词(空格分隔) |
| 5 | yichen0831/opencc-python | 简体中文文件转繁体 |
| 6 | savoirfairelinux/num2words | 把每行一个的数字转为英文文字 |
| 7 | jazzband/inflect | 把每行一个的英文名词转为复数 |
| 8 | daviddrysdale/python-phonenumbers | 把每行一个的电话号码规范为 E.164 |
| 9 | john-kurkowski/tldextract | 把每行一个的 URL 拆出子域/域/后缀 |
| 10 | h2non/filetype.py | 嗅探文件真实类型(扩展名+MIME) |
| 11 | barrust/pyspellchecker | 报告英文文本中的拼写可疑词 |
| 12 | carpedm20/emoji | 把文本中的 emoji 转为 `:name:` 别名 |

能力句为草稿基调;人闸期可做 typo 级勘误,**换仓禁止**——某仓
admission 拒收或 intake 不可行时,如实记 BLOCKED/放弃行,不补位。

## 四、执行条款(沿批次一,含两批全部教训)

- 模型:`.env` 缺省通道(openai×gpt-5.5×mini-swe);逐任务
  add→人闸→build,操作员=AI、用户抽验。
- 真发一发制;重发=新版本号分行;fake 彩排门不 PASS 不烧真预算。
- 批帽:名义 in 6,000,000 触顶即停(发前判定)。
- 全部发次 test_mode=PRODUCT(彩排 HARNESS_SELFCHECK / 真发
  PRODUCT_ONBOARDING),不充闸不计能力。
- 四指标唯一出口 `scripts/tool_metrics.py`(需以本批 tasks json 单独
  计,不与批次一混池)+ `m4_replay_check.py` + 操作员新输入审计。
- 操作卫生(批次一/对比批实测教训):备题临时文件用后即清
  (H9-a 会拦 /tmp 答案残留——sizesx 事故);draft 束由 pipeline
  归档,不手工复制副本留残留。
- filetype 任务预期声明 `malformed_applicable: false`(全域合法输入,
  chardet 同型);jieba/tldextract/pyspellchecker 均自带离线数据,
  intake 期核实"零网可用",不成立则如实 BLOCKED。

## 五、停点

**本预注册冻结即停,待用户批准后开跑。** 预算粗估:按批次一实测
(GPT 均 ~144K in/发)名义 in ≈1.7-2.5M + 起草 ~0.1M,cache 折后更低。

## 六、勘误区(append-only)

(空)

- 2026-08-23:用户在预注册停点后明确批准开跑；执行期间严格使用 `.env`
  缺省 openai×gpt-5.5，未换 provider、未运行 E1G。
- 2026-08-23:`tldextract` admission 因仓要求 `GITHUB_TOKEN` 环境密钥而
  硬拒；按冻结条款放弃且不换仓、无 contract/run/预算消耗。
- 2026-08-23:`pypinyin` 首次 build 在 D 确认门、任何 rehearsal/真发
  之前被误拒：reference 合法使用 `from pypinyin import lazy_pinyin`，旧门
  只做字面 `import pypinyin` 搜索。先以合成回归复现红，再改 AST import
  判定，原 v1 无运行残留，随后正常 build。
- 2026-08-23:`opencc` 首次 fake rehearsal
  `tool-opencc-tool-v1-20260823-221656` FAIL：import-hook 跳过所有类，
  `OpenCC(...)` 真实实例化只记 import、零 call。先补公开类实例化合成回归，
  再以保留类身份/异常类语义的 `__new__` 取证修复；清残留后 v1 合法重建，
  真发未提前消耗。
- 2026-08-23:`inflect` 首次 fake rehearsal
  `tool-inflect-tool-v1-20260823-222454` FAIL：hook 把模块从 `typing` 导入的
  `List` 当目标 API 换成函数代理，令 `List[...]` 报 function 不可下标。
  先补 imported-callable 透明性回归，再限制为只包装目标模块自身定义 API；
  清残留后 v1 合法重建，真发未提前消耗。
- 2026-08-23:`pyspellchecker` 首次 fake rehearsal
  `tool-pyspellchecker-tool-v1-20260823-223809` FAIL：hook loader 代理未转发
  `get_data`，内置词典资源读取为空。先补 package-resource 合成回归，再完整
  转发原 loader 扩展协议；清残留后 v1 合法重建，真发未提前消耗。
- 2026-08-23:`num2words` fake 彩排 PASS 后唯一真发
  `tool-num2words-tool-v1-20260823-222229` 在 held-out
  `test_held_example_1` FAIL(5/6)；按一发制封存，不重发、不导出。
- 2026-08-23:`pyspellchecker v1` 虽获真实 `PASS_ADAPTED`，操作员全新输入
  审计发现冻结题面/tool.json 要求含 `language/token_count/suspicious_count/
  suspicious` 的 JSON 对象，而 reference、样例和 oracle 错钉为排序纯文本；
  这是题面-oracle 自相矛盾造成的 false-success。用户明确批准撤回 READY
  运营结论；`m4_audits.jsonl` 记 `ok=false`、分类 sidecar 追加覆盖勘误，
  历史 run/冻结合同保留，不修改、不重跑 v1。
- 2026-08-23:终局口径为 submitted 12、accepted 11、流水线历史口径
  tool_ready 10、replay 10/10；人工新输入 audited 10、flagged 1，故运营可用
  9。11 次真发合计 1,023,840 input / 36,122 output tokens，未触 6M 帽。
  全量回归最终 `1178 passed + 60 skipped + 0 failed`；首轮唯一失败是受保护
  `offerclaw` 被外部常驻服务同期写日志/缓存而触发完整性护栏，独立复测与
  第二次全量均绿，未削弱护栏、未终止或回滚用户进程。
- 2026-08-23:提交前泄漏巡检确认本批 public/delivery/Bench/quarantine
  均无 reference/oracle/held-out；另在 `/private/tmp` 发现一个旧的完整
  `repoproof-review.5asZpP/RepoProof` 评审副本(25M，含历史其他任务
  held-out，非本批生成)。按答案材料绝不驻留 `/tmp` 红线，整目录移入
  `~/.Trash/RepoProof-redline-recovery-20260823/` 可恢复保管，未读取其答案。
