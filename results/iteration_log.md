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

## 小结（调参集只有 9 条）

- 同一个 v2 prompt 连跑两次，C 组的「类别命中」是 3/9 和 4/9，「步骤完全命中」是 3/9 和 2/9。也就是说，**两次运行之间的随机波动（±1–2 条）和各次 prompt 改动带来的变化一样大**，单看调参集分数无法判断改动是否有效。
- 唯一与噪声无关、可以直接判断的问题是置信度：模型自报的置信度在大多数答错的案例上也是 0.9–1.0，不能用来决定是否弃权。
- 因此 v3 改为自洽投票：同一问题采样 3 次（温度 0.7），3 次都给出相同的步骤和类别、且引用原文能在该步骤里找到，才输出结论，否则弃权。调参集上：作答 4 条，其中 2 条全对；如果不弃权全部作答，9 条中只有 2 条全对。
- 「必须 3/3 一致」这个门槛是在调参集上选的。之后冻结为 v3，测试集只跑了一次（结果见 `results/eval_investigator.json`）。
