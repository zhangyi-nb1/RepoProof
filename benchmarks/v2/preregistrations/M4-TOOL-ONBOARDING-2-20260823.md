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
