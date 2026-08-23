# humanize-tool

将每行一个的整数字节数转换为人类可读大小文本。

## 用法

```
humanize-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/humanize-tool <input>
```

来源:https://github.com/python-humanize/humanize @ 3c577d7650508d52aa2982e930b0e744c343082f(license: MIT);
验证证据见 `evidence/`(harness 写入)。
