# post_tests/ 是判卷材料,不是本目录的测试 —— 外层 pytest
# 若直接收集它们,会在缺 conftest 的语境下炸出与判据无关的红。
collect_ignore = ["post_tests"]
