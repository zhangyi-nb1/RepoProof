# tabulate-tool

把 CSV 文件渲染为 GitHub 风格 Markdown 表格的本地离线 CLI 能力。

## 用法

```
tabulate-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/tabulate-tool <input>
```

来源:https://github.com/astanin/python-tabulate @ 3b4cd509820e4c45cd2aaba833aa585ea6308b94(license: MIT);
验证证据见 `evidence/`(harness 写入)。
