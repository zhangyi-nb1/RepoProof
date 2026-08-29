# webcolors-tool

将 CSS3 颜色名称或十六进制颜色识别为 RGB，并确定性转换为适配 MSP432 灰度识别接口的 3 位灰度模式。

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
