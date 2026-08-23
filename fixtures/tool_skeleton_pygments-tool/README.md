# pygments-tool

将单个源代码文件高亮为自包含 HTML 文档。

## 用法

```
pygments-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/pygments-tool <input>
```

来源:https://github.com/pygments/pygments @ a43b45dcf081b6010c6ab4428f149f7f6d2499c4(license: BSD-2-Clause);
验证证据见 `evidence/`(harness 写入)。
