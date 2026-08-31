# rispy-screening-table

把 UTF-8 RIS 按 rispy 解析顺序且不去重地整理为固定列的团队筛选 CSV，并标出 title、authors、year、doi 的空项。

## 用法

```
rispy-screening-table <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/rispy-screening-table <input>
```

来源:https://github.com/MrTango/rispy @ b7aae3b2069ced3fb75287711300f2edf0bcac21(license: MIT);
验证证据见 `evidence/`(harness 写入)。
