# TraceCheck 网页

- `web/app/`：前端源码（Vite + React + Tailwind，组件按 shadcn/ui 的写法基于 Radix）。
- `web/site/`：构建结果（已提交），本地服务和静态托管都直接用它。
- 第 1 页“诊断报告”是新版；案例库 / 评测总览 / 回归对比暂时还是旧版（`web/app/public/legacy/`），之后重做。

## 本地交互版（能导入新记录）

```bash
cd web/app && npm install && npm run build && cd ../..          # 改了前端才需要
GEMINI_API_KEY=… ZHIPU_API_KEY=… vendor/tau2-bench/.venv/bin/python -m web.serve
# 打开 http://127.0.0.1:8000，右上角“导入记录”
```

- 只监听 127.0.0.1；调查 agent（Gemini）和翻译（智谱 glm-4-flash）用你本机的 key，调用记入 `results/cost_log.csv`。
- 调查 agent 用 v4 prompt（v3 + 因果链 + 中文说明），结果缓存在 `results/investigator/web/`；翻译缓存在 `results/translations/`。
- 对 AI 判断的“接受 / 驳回 / 修改”写入 `results/human_review.jsonl`（时间、原判断、人工判断）。
- 上传的记录存在 `results/uploads/`（git-ignore）。

## 线上展示版（静态）

把 `web/site/` 当静态站点发布。没有后端时只能打开预先生成的报告（`web/export.py` 里的 `DEMO_RUNS`），复核结果只存在浏览器里。

```bash
vendor/tau2-bench/.venv/bin/python -m web.export   # 重新生成 web/app/public/data/ 下的数据，然后再 npm run build
```
