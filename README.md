# TraceCheck

Agent 失败复盘 + 回归验证工具（开发中）。测试环境：τ²-bench retail。

当前进度：阶段 0（环境与摸底）完成。

## 安装与试跑

```bash
./scripts/setup.sh                      # 克隆并安装 tau2-bench / AgentRx 到 vendor/
cp .env.example .env                    # 填入 GEMINI_API_KEY，然后 export 到环境
vendor/tau2-bench/.venv/bin/python -m pytest tests -q
vendor/tau2-bench/.venv/bin/python -m runner.run_batch --tag smoke --task-ids 0 1 2 --k 1
```

同一条 `run_batch` 命令可以反复执行：已完成的 (任务, 轮次) 会跳过，当日免费额度用完会自动停下，第二天接着跑。
每次模型调用记录在 `results/cost_log.csv`。
