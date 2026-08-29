# jsonschema-tool

检查单个 JSON 中的 JSON Schema 与待验证数据，一次返回全部稳定排序的问题；支持显式提供的本地引用，绝不联网获取规则。

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
