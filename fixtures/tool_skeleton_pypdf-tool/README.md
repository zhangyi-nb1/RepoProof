# pypdf-tool

将本地 PDF 离线转换为保留逐页文本、空页、文档标题作者及层级书签的可检索 JSON 清单。

## 用法

```
pypdf-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/pypdf-tool <input>
```

来源:https://github.com/py-pdf/pypdf @ efad421b12fe47b269593ffca8e79a71c7aae065(license: BSD-3-Clause);
验证证据见 `evidence/`(harness 写入)。
