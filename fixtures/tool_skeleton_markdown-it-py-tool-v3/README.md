# markdown-it-py-tool

读取 UTF-8 Markdown 文件并使用 markdown-it-py 4.2.0 提取标题、链接与围栏代码块，输出确定性 JSON 对象。

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
