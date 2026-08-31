# pint-tool

将含样本名、原数值和目标单位的 UTF-8 表格用 Pint 换算为可粘贴到 Excel 的 TSV，保留失败行并说明，结果最多显示 6 位有效数字。

## 用法

```
pint-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/pint-tool <input>
```

来源:https://github.com/hgrecco/pint @ 5e79411e1be2dc39c52a536168338773b49fd512(license: BSD);
验证证据见 `evidence/`(harness 写入)。
