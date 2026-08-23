# tomli-tool

把本地 TOML 配置文件离线、确定性地解析并规范化为 JSON。

## 用法

```
tomli-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/tomli-tool <input>
```

来源:https://github.com/hukkin/tomli @ 5a77b12a7a9f052ce5a20c335d2825658f6aea52(license: MIT);
验证证据见 `evidence/`(harness 写入)。
