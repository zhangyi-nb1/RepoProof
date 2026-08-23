# python-dateutil-tool

将每行一个的自由格式日期解析并规范化为 ISO 8601 输出。

## 用法

```
python-dateutil-tool <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/python-dateutil-tool <input>
```

来源:https://github.com/dateutil/dateutil @ 1ae807774053c071acc9e7d3d27778fba0a7773e(license: Apache-2.0);
验证证据见 `evidence/`(harness 写入)。
