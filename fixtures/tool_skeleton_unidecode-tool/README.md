# unidecode-tool

将 UTF-8 Unicode 文本文件离线转写为确定性的 ASCII 近似文本。

## 用法

```
unidecode-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/unidecode-tool <input>
```

来源:https://github.com/avian2/unidecode @ 8d83b7c70c39678c2b95cb0caf3d3c4425cb2cc2(license: GPL-3.0);
验证证据见 `evidence/`(harness 写入)。
