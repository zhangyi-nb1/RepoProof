# jsonschema-tool

离线校验本地 JSON Schema 与数据，稳定返回全部可定位的校验问题及组合关键字的子错误。

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
