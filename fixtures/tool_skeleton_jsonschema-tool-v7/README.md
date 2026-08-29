# jsonschema-tool

将 UTF-8 JSON Schema Draft 2020-12 验证结果导出为确定性的紧凑 JSON 错误报告。

## 用法

```
jsonschema-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/jsonschema-tool <input>
```

来源:https://github.com/python-jsonschema/jsonschema @ 331c38425519b69118d22ebe467ad230fb83a010(license: MIT);
验证证据见 `evidence/`(harness 写入)。
