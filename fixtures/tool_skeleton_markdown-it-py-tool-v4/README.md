# markdown-it-py-tool

将 Markdown 文件按原文解析顺序提取标题层级、链接和围栏代码块，生成稳定且完全离线的 JSON。

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
