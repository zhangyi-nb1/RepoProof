# pypdf-tool

将 PDF 离线转换为稳定、可检索的 JSON 清单：逐页保留文字与空页，并包含标题、作者和书签层级；加密、损坏或空文件会明确报错。

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
