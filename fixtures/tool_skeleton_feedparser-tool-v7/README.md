# feedparser-tool

将本地 RSS 或 Atom XML 文件离线整理为顺序稳定、字段规范化的订阅文章清单，并报告可恢复的解析警告。

## 用法

```
feedparser-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/feedparser-tool <input>
```

来源:https://github.com/kurtmckee/feedparser @ 14425f6851790184fbf7bbd8076de237d5f444f9(license: BSD-2-Clause);
验证证据见 `evidence/`(harness 写入)。
