# json5-tool

将 JSON5 文件规范化为严格 JSON 文本输出。

## 用法

```
json5-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/json5-tool <input>
```

来源:https://github.com/dpranke/pyjson5 @ 1f7f8062a76d5899288674b938e73b7bcadf63c3(license: Apache-2.0);
验证证据见 `evidence/`(harness 写入)。
