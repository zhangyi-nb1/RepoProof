# pdf-table

从 PDF 提取全部表格,输出 GitHub-flavored Markdown

## 用法

```
pdf-table <input.pdf> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/pdf-table <input>
```

来源:https://github.com/jsvine/pdfplumber @ 7d4f2f582f2d99f9e60ba522fdf7afd2f6d54c62(license: MIT);
验证证据见 `evidence/`(harness 写入)。
