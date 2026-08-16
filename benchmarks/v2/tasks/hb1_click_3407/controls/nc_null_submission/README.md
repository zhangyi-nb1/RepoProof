负控 nc_null_submission:惰性提交(只创建一个与题无关的标记文件)。
期望:delta 节点全红 → verdict FAIL,J3 落 IMPL_INCOMPLETE 侧;
回归保持绿;不得 BLOCKED(附录一第 6 条:零字节 patch 会撞冻结/重放
边界,产生与判据无关的噪声,故用惰性提交)。
