# feedparser-tool

将本地 RSS 或 Atom 字节文件用固定版本 feedparser 6.0.14 离线解析为确定性的规范化 JSON。

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
