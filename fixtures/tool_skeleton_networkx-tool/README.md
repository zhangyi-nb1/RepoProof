# networkx-tool

将 UTF-8 GraphML 网络整理为可放进项目笔记的 Markdown 摘要，说明规模、分组、关键节点和落单节点。

## 用法

```
networkx-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/networkx-tool <input>
```

来源:https://github.com/networkx/networkx @ 7530809bfa1ea7ed6fdf918a4d1431488953cb1f(license: BSD);
验证证据见 `evidence/`(harness 写入)。
