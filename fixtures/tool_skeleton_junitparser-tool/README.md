# junitparser-tool

合并 ZIP 中的多份测试报告，并可按通过、失败、错误或跳过状态筛选后输出确定性 JSON 汇总。

## 用法

```
junitparser-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/junitparser-tool <input>
```

来源:https://github.com/weiwei/junitparser @ d98bdb70fbde4d08e191df17bd51576102c19d6a(license: Apache-2.0);
验证证据见 `evidence/`(harness 写入)。
