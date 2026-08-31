# rispy-tool

将本地 UTF-8 RIS 文献去除完全重复项后导出为可导回文献软件的 RIS 文件，不联网补全资料。

## 用法

```
rispy-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/rispy-tool <input>
```

来源:https://github.com/MrTango/rispy @ b7aae3b2069ced3fb75287711300f2edf0bcac21(license: MIT);
验证证据见 `evidence/`(harness 写入)。
