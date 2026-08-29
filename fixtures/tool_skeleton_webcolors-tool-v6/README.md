# webcolors-tool

将网页中的命名颜色与十六进制颜色规范化为可供小车识别的确定性颜色调色板 JSON。

## 用法

```
webcolors-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/webcolors-tool <input>
```

来源:https://github.com/ubernostrum/webcolors @ e6392ba6eeba81b02e666eb3ed02ef2e006344c0(license: BSD);
验证证据见 `evidence/`(harness 写入)。
