# 简历项目描述（草稿，作者确认后使用）

每个数字都能在 `report/report.md` 和 `results/` 里找到出处。面试前请确认你能说清每个数字是怎么来的。

## 中文版

**TraceCheck — Agent 失败诊断与回归验证工具**（个人项目，τ²-bench retail，[在线 Demo](https://huggingface.co/spaces/ray12138888/tracecheck)）

- 为 Agent 开发团队解决“失败太多、难以得到可信结论”的问题：设计三层诊断（规则检查 → 数据库重放核验 → 证据约束的 LLM 调查 agent），确定性核验与官方判定 449/449 一致，模型拿不准时弃权并交给人工复核台。
- 关键判断：用事先登记的统计检验和“同版本重跑”噪声基线判断修复是否有效；埋入 6 个已知 bug 验证检测能力——代码级 bug 2/2 检出并定位到字段、零误报，提示词 bug 0/4，事后分析区分出 1 个漏检和 3 个“bug 本身未生效”。
- 自建人工核验流程，发现“假成功”指标定义有误：AI 辅助核验显示约 1/19 为真；重新定义并在独立样本上人工复核，准确率仍只有 1/12，因此停用该指标、拆分为“说法是否属实”与“结果是否达成任务”两个信号，并如实报告。
- 把单条失败转成回归用例，用新版本真实重放并重新核验数据库；全栈实现（Python + React），全部使用免费模型，总成本 $0。

## English

**TraceCheck — failure diagnosis and regression testing for LLM agents** (personal project on τ²-bench retail, [live demo](https://huggingface.co/spaces/ray12138888/tracecheck))

- Built a three-layer diagnosis pipeline for agent teams drowning in failed runs: deterministic rules, database replay against the reference state (449/449 agreement with the benchmark's own verdict), and an evidence-constrained LLM investigator that abstains and hands off to a human review desk when its samples disagree.
- Judged fixes with pre-registered statistical tests and a same-version re-run noise baseline; planted 6 known bugs: code-level bugs detected and localised 2/2 with zero false alarms, prompt-level bugs 0/4 — post-hoc analysis separated one genuine miss from three bugs that never changed agent behaviour.
- Ran a human audit that overturned my own "false success" metric (AI-assisted review: ~1/19 true positives; redefined rule, independent human-labelled sample: 1/12); retired the metric and split it into "is the claim true" vs "was the task achieved", reported as-is.
- Turned single failures into regression cases replayed for real against a new agent version with database re-verification; full stack (Python, React), free-tier models only, total cost $0.

## 说明
- “AI 辅助核验约 1/19”是另一个 AI 的建议标签，不是人工标注；“1/12”是作者本人在独立样本 B 上的人工判断。面试时要区分清楚。
- 如果篇幅只允许 3 行，删第 4 条。
