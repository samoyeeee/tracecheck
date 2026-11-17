# 调查 Agent 调参记录（只用调参集，测试集不参与）

调参集：AgentRx tau-bench 29 条中按种子 7 抽出的 9 条 (2, 12, 20, 34, 38, 39, 59, 72, 105)。每行指标均为调参集上的结果。

| 时间 | prompt 版本 | 组 | 改动 | 步骤完全命中 | ±1 步 | 类别 | 步骤+类别 | 弃权率 |
|---|---|---|---|---|---|---|---|---|
| 2026-11-17 09:07 UTC | v1 | A | baseline prompt v1 | 3/9 | 4/9 | 3/9 | 2/9 | 0/9 |
| 2026-11-17 09:07 UTC | v1 | B | baseline prompt v1 | 4/9 | 5/9 | 4/9 | 3/9 | 0/9 |
| 2026-11-17 09:07 UTC | v1 | C | baseline prompt v1 | 4/9 | 4/9 | 2/9 | 2/9 | 2/9 |
| 2026-11-17 09:10 UTC | v2 | A | v2: root-cause = first unrecovered mistake; category conventions; calibration guidance; JSON mode | 5/9 | 5/9 | 4/9 | 3/9 | 0/9 |
| 2026-11-17 09:10 UTC | v2 | B | v2: root-cause = first unrecovered mistake; category conventions; calibration guidance; JSON mode | 3/9 | 4/9 | 4/9 | 2/9 | 0/9 |
| 2026-11-17 09:10 UTC | v2 | C | v2: root-cause = first unrecovered mistake; category conventions; calibration guidance; JSON mode | 2/9 | 3/9 | 2/9 | 1/9 | 3/9 |
| 2026-11-17 09:10 UTC | v2 | C | v2 re-scored from cache with bracket repair (0 new calls) | 3/9 | 4/9 | 3/9 | 2/9 | 1/9 |
| 2026-11-17 09:13 UTC | v2 (重复 1) | B | same v2 prompt, second run: run-to-run noise | 3/9 | 3/9 | 4/9 | 2/9 | 0/9 |
| 2026-11-17 09:13 UTC | v2 (重复 1) | C | same v2 prompt, second run: run-to-run noise | 2/9 | 3/9 | 4/9 | 2/9 | 1/9 |
| 2026-11-17 09:16 UTC | v3 | C | v3: arm C = 3 samples at T=0.7, vote; abstain unless 2/3 agree + verbatim evidence (prompt text = v2) | 4/9 | 4/9 | 4/9 | 2/9 | 0/9 |
| 2026-11-17 09:16 UTC | v3 | C | v3 with abstain unless 3/3 agree (re-scored from cache, 0 new calls). FROZEN for test. | 2/9 | 2/9 | 2/9 | 2/9 | 5/9 |
