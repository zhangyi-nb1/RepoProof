# html2md

将单个 HTML 文件离线转换为干净、稳定的 Markdown 文本。

## 用法

```
html2md <input.html> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/html2md <input>
```

来源:https://github.com/matthewwithanm/python-markdownify @ 93418550746de58c9180c4cc6fda7520581b03cb(license: MIT);
验证证据见 `evidence/`(harness 写入)。
