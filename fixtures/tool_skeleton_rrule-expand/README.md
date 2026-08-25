# rrule-expand

把 DTSTART+RRULE 两行文本展开为前 10 次发生时间

## 用法

```
rrule-expand <input.txt> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/rrule-expand <input>
```

来源:https://github.com/dateutil/dateutil @ 48bd1af97e71baf8e96fce5b663d589caac8f147(license: Apache-2.0);
验证证据见 `evidence/`(harness 写入)。
