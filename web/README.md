# TraceCheck 网页

| 页面 | 作用 |
|---|---|
| `index.html` 分析一条记录 | 上传 / 粘贴 / 选一条 agent 运行记录，TraceCheck 当场跑三层：规则检查 → 数据库核验 → 调查 agent |
| `audit.html` 案例库 | 预先分析好的 69 条 v1 失败记录，可逐条接受 / 驳回调查 agent 的结论（只存在本浏览器） |
| `overview.html` 评测总览 | TraceCheck 在 τ²-bench retail 上的评测结果 |
| `regression.html` 回归对比 | v1 / v2 / 埋 bug 版本的对比与发布建议 |

## 本地交互版（能分析新记录）

```bash
# 用 tau2 的 venv；不设 key 时只跑前两层
GEMINI_API_KEY=你的key vendor/tau2-bench/.venv/bin/python -m web.serve
# 打开 http://127.0.0.1:8000
```

- 只监听 127.0.0.1。调查 agent 用你本机的 key，调用记入 `results/cost_log.csv`。
- 上传的记录存在 `results/uploads/`（已 git-ignore）。
- 输入格式：τ²-bench retail 的单次运行记录（`results/runs/<版本>/task_<id>__trial_<n>.json` 那种），需要 `task_id` 和 `messages`；数据库核验要用任务的初始数据库和标准答案重放。

## 线上展示版（静态，不调用模型）

把 `web/` 作为静态站点发布即可（Netlify / Vercel / GitHub Pages，无需构建）。
没有后端时页面自动切换为展示模式：只能看预先运行的结果，并明确标注。

```bash
python -m web.export                 # 从 results/ 重新导出 web/data/*.json
python -m http.server -d web 8000    # 本地预览展示模式
```

每个数字旁的“来源”链接指向 GitHub 上的结果文件（`assets/common.js` 里的 `REPO`）。
