# python-docx-tool

将本地 DOCX 的正文段落、标题级别和表格按真实文档顺序提取为稳定 JSON，并保留合并与空单元格语义。

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
