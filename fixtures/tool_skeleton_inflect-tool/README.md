# inflect-tool

将纯文本文件中每行一个的英文名词转换为复数形式。

## 用法

```
inflect-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/inflect-tool <input>
```

来源:https://github.com/jazzband/inflect @ 262a247d2d99a47a520cdb2d46adb90df88b4326(license: MIT);
验证证据见 `evidence/`(harness 写入)。
