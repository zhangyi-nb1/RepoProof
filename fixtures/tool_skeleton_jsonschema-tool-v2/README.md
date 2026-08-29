# jsonschema-tool

校验同一 JSON 文档中的 JSON Schema 与数据，收集全部错误并以稳定的 JSON 指针路径输出，仅允许文档内引用。

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
