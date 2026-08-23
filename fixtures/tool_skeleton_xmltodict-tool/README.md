# xmltodict-tool

将本地 XML 文件离线转换为规范化 JSON 文本。

## 用法

```
xmltodict-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/xmltodict-tool <input>
```

来源:https://github.com/martinblech/xmltodict @ 6e29fba282e68631034dd2722a413b4e35276584(license: MIT);
验证证据见 `evidence/`(harness 写入)。
