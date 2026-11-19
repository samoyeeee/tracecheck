# TraceCheck 网页

静态页面，只读 `web/data/*.json`，打开时不调用任何模型。

```bash
python -m web.export                 # 从 results/ 重新导出数据（用 tau2 的 venv）
python -m http.server -d web 8000    # 本地预览 http://localhost:8000
```

- `index.html` 总览，`audit.html` 问题审计卡，`regression.html` 回归对比。
- 每个数字旁的“来源”链接指向 GitHub 上的结果文件（`assets/common.js` 里的 `REPO`）。
- 审计卡的“接受 / 驳回”只存在浏览器 localStorage 里，可用“导出我的判断”下载。
- 部署：把 `web/` 目录作为静态站点发布即可（Netlify / Vercel / GitHub Pages 均可，无需构建）。
