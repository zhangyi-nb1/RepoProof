# chardet-tool

将 chardet 的字符编码检测能力封装为本地离线 CLI，输出编码名与置信度报告。

## 用法

```
chardet-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/chardet-tool <input>
```

来源:https://github.com/chardet/chardet @ fa905b359cbcaba93a35fd6429ba9ec4b156c1c1(license: LGPL-2.1);
验证证据见 `evidence/`(harness 写入)。
