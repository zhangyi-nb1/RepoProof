# pypinyin-tool

把 UTF-8 中文文本按输入行逐行转换为无声调拼音文本。

## 用法

```
pypinyin-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/pypinyin-tool <input>
```

来源:https://github.com/mozillazg/python-pinyin @ 8595294b1a97845e30f11ecfdb3caa4e61ac3988(license: MIT);
验证证据见 `evidence/`(harness 写入)。
