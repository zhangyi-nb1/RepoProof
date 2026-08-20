# tobymao/sqlglot PR #8042: fix(lineage)!: trace columns through chained (UN)PIVOT operators

merged_at: 2026-08-06T10:47:17Z
merge_commit: cb4a8214605bf038c185a6b09d2541ff39475650
base: c164cce9341eae08dcf3d4a43fc53e49fb69d59e

## PR 正文

Lineage only handled a single pivot per source. This folds the whole (UN)PIVOT chain when mapping output columns back to their sources, matching how the optimizer resolves chains since #8032.

