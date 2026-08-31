# rispy-tool

离线整理一份 UTF-8 RIS 文献导出文件，去除明确重复记录并输出可重新导入的 RIS 文献文件。

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
