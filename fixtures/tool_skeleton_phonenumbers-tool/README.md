# phonenumbers-tool

把纯文本中每行一个的国际电话号码离线、确定性地规范为 E.164 格式。

## 用法

```
tool-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/phonenumbers-tool <input>
```

来源:https://github.com/daviddrysdale/python-phonenumbers @ e605afeba7572cfe1821f1015f29b24f1d7602b5(license: Apache-2.0);
验证证据见 `evidence/`(harness 写入)。
