# biopython-fasta-shortlist

使用 Biopython 离线筛选多记录 FASTA，并生成可直接用于会议的确定性 Markdown 通过/未通过报告。

## 用法

```
biopython-fasta-shortlist <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/biopython-fasta-shortlist <input>
```

来源:https://github.com/biopython/biopython @ d7e4b8b19399668b09442a5b35765d9186b5f665(license: BSD);
验证证据见 `evidence/`(harness 写入)。
