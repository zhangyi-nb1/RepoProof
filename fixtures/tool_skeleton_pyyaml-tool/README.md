# pyyaml-tool

安全解析 YAML 文件并输出语义等价、确定性的 JSON 文本

## 用法

```
pyyaml-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/pyyaml-tool <input>
```

来源:https://github.com/yaml/pyyaml @ 49790e73684bebad1df05ef8d828fa12f685bffb(license: MIT);
验证证据见 `evidence/`(harness 写入)。
