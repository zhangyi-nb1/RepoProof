# biopython-tool

将单份原始 FASTQ 测序读段文件离线解析为自包含 HTML 质量概览报告。

## 用法

```
biopython-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/biopython-tool <input>
```

来源:https://github.com/biopython/biopython @ d7e4b8b19399668b09442a5b35765d9186b5f665(license: BSD);
验证证据见 `evidence/`(harness 写入)。
