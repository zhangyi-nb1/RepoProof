# ftfy-tool

修复文本文件中的 mojibake 乱码，输出修复后文本

## 用法

```
ftfy-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/ftfy-tool <input>
```

来源:https://github.com/LuminosoInsight/python-ftfy @ 5340af6746ff655a9cd7cb2b50c2fd0b35bb91d3(license: Apache-2.0);
验证证据见 `evidence/`(harness 写入)。
