# jieba-tool

将 UTF-8 中文纯文本按输入行逐行使用 jieba 分词，并以单个空格连接词元输出。

## 用法

```
jieba-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/jieba-tool <input>
```

来源:https://github.com/fxsjy/jieba @ 67fa2e36e72f69d9134b8a1037b83fbb070b9775(license: MIT);
验证证据见 `evidence/`(harness 写入)。
