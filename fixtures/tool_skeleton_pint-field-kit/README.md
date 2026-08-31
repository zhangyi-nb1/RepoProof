# pint-field-kit

将实验耗材 TSV 按组数与目标单位换算为可离线打开、逐行保留成功和稳定错误状态的现场准备单。

## 用法

```
pint-field-kit <input> [--out FILE]
```

退出码:0=成功;1=用户错误(输入不存在/格式坏);2=内部错误。

## 安装

```
./build.sh
./bin/pint-field-kit <input>
```

来源:https://github.com/hgrecco/pint @ 5e79411e1be2dc39c52a536168338773b49fd512(license: BSD);
验证证据见 `evidence/`(harness 写入)。
