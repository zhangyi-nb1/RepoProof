# python-docx-tool

读取 DOCX 文档并按正文顺序输出段落、标题层级和表格的确定性 JSON。

## 用法

```
python-docx-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/python-docx-tool <input>
```

来源:https://github.com/python-openxml/python-docx @ e45454602b53e8e572b179ccf1c91093ec9f4ed7(license: MIT);
验证证据见 `evidence/`(harness 写入)。
