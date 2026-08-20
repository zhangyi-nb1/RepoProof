负控 nc_regression_break:answer patch + 一行窄破坏(sabotage.patch,
靶远离 delta 路径)。期望:delta 全绿 + 回归红 → verdict FAIL,
J3 落 REGRESSION_BROKEN。apply.patch 为物化件(含答案,不入 git);
sabotage.patch 不含答案,入 git。
