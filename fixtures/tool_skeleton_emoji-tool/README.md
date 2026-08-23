# emoji-tool

将 UTF-8 文本文档中的 emoji 离线转换为 :name: 形式的别名。

## 用法

```
emoji-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/emoji-tool <input>
```

来源:https://github.com/carpedm20/emoji @ d26c675190a6b6c0edee959d7b896721a9c3641d(license: BSD);
验证证据见 `evidence/`(harness 写入)。
