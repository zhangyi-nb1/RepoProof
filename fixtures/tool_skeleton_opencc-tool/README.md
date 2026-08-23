# opencc-tool

将简体中文纯文本文件离线、确定性地转换为繁体中文文本。

## 用法

```
opencc-python-reimplemented-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/opencc-tool <input>
```

来源:https://github.com/yichen0831/opencc-python @ b85452e384a3650109809fe5fefacb2ae4fe89d2(license: Apache-2.0);
验证证据见 `evidence/`(harness 写入)。
