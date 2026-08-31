# networkx-dependency-risk

将任务依赖 CSV 转成可粘贴到表格软件的确定性 TSV 风险清单，标出直接依赖、直接后继、下游影响、可开工状态与循环。

## 用法

```
networkx-dependency-risk <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/networkx-dependency-risk <input>
```

来源:https://github.com/networkx/networkx @ 7530809bfa1ea7ed6fdf918a4d1431488953cb1f(license: BSD);
验证证据见 `evidence/`(harness 写入)。
