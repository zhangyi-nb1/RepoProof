# num2words-tool

把纯文本中每行一个的整数转换为英文文字。

## 用法

```
num2words-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/num2words-tool <input>
```

来源:https://github.com/savoirfairelinux/num2words @ 07814cb114157f582c40a00119c2e9faba8dcee2(license: GPL-3.0);
验证证据见 `evidence/`(harness 写入)。
