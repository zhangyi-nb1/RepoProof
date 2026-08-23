# filetype-tool

将 filetype 的本地文件真实类型嗅探能力封装为离线 CLI，输出扩展名与 MIME。

## 用法

```
filetype-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/filetype-tool <input>
```

来源:https://github.com/h2non/filetype.py @ 3eae5cedad2dc65076a501a9374abafb1d700602(license: MIT);
验证证据见 `evidence/`(harness 写入)。
