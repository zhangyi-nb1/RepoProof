# markdown-tool

将本地 Markdown 文件离线、确定性地渲染为 HTML 字符串。

## 用法

```
markdown-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/markdown-tool <input>
```

来源:https://github.com/Python-Markdown/markdown @ f39cf84a24124526c1a0efbe52219fa9950774f6(license: BSD);
验证证据见 `evidence/`(harness 写入)。
