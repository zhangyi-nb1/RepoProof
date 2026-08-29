# markdown-it-py-tool

解析 UTF-8 Markdown，并按源码顺序生成包含标题、链接与 fenced code block 的确定性结构化 JSON。

## 用法

```
markdown-it-py-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/markdown-it-py-tool <input>
```

来源:https://github.com/executablebooks/markdown-it-py @ 36c5f547144df2d01970a5792d68c71a3380b227(license: MIT);
验证证据见 `evidence/`(harness 写入)。
