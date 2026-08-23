# pyspellchecker-tool

将英文纯文本中的拼写可疑词提取为确定性的离线 JSON 报告。

## 用法

```
pyspellchecker-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/pyspellchecker-tool <input>
```

来源:https://github.com/barrust/pyspellchecker @ f72172c4ddb3d1c3464cf500cc2420a4831a2b55(license: MIT);
验证证据见 `evidence/`(harness 写入)。
