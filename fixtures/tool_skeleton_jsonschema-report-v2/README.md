# jsonschema-report

用文件内嵌 schema 校验 data 并输出结构化 JSON 错误报告

## 用法

```
jsonschema-report <input.json> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/jsonschema-report <input>
```

来源:https://github.com/python-jsonschema/jsonschema @ b37f7be6dc7966a1f1a67557976041ffe0826cb3(license: MIT);
验证证据见 `evidence/`(harness 写入)。
