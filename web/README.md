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

## 在线部署

- **只读展示版**（免费、不休眠）：Hugging Face 静态 Space，https://huggingface.co/spaces/ray12138888/tracecheck 。
  更新：`HF_TOKEN=… deploy/hf_static.sh ray12138888/tracecheck`。
- **能导入记录的在线版**：Render 免费套餐，https://tracecheck-uf75.onrender.com ，用仓库根目录的 `Dockerfile` 和 `render.yaml`
  （`autoDeploy: false`：推送新代码后在 Render 后台点 Manual Deploy → Deploy latest commit）。
  公开模式（`PUBLIC_MODE=1`）下：每人每天 3 次 AI 诊断、全站每天 40 次、同时只跑一个；复核只存在访客浏览器；
  不能读取服务器上的运行记录。限额见 `web/limits.py`，可用环境变量改。
  Hugging Face 的 Docker Space 从 2026 年起需要 PRO 订阅，所以没用它。

重新生成页面数据：

```bash
vendor/tau2-bench/.venv/bin/python -m web.export   # 再 cd web/app && npm run build
```
