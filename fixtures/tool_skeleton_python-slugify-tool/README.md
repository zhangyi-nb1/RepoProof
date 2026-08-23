# python-slugify-tool

把 UTF-8 文本文件的每一行离线转换为确定性的 URL slug。

## 用法

```
python-slugify-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/python-slugify-tool <input>
```

来源:https://github.com/un33k/python-slugify @ f85f9488520148d5f6899b5639199882b605e30a(license: MIT);
验证证据见 `evidence/`(harness 写入)。
