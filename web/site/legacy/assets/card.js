// The audit card: one agent run, with TraceCheck's three layers.
// Used by index.html (live analysis) and audit.html (pre-computed examples).

const ROLE_ZH = { assistant: "Agent", user: "用户", tool: "工具结果", system: "系统" };

function stepLink(s) { return s === null || s === undefined ? "" : `<button class="steplink" data-step="${s}">步骤 ${s}</button>`; }

function renderTimeline(c) {
  const d = c.diagnosis || {};
  const flagged = new Set(c.findings.map((f) => f.step).concat(c.claims.map((x) => x.step)));
  return c.timeline.map((m) => {
    const isCrit = c.diagnosis && m.step === d.critical_step;
    const cls = ["step", m.role === "tool" ? "tool" : "", isCrit && !d.abstain ? "critical" : "", flagged.has(m.step) ? "flagged" : ""].join(" ");
    const marks = [
      isCrit ? `<span class="tag ${d.abstain ? "warn" : "bad"}">${d.abstain ? "候选关键步（已弃权）" : "AI 判定的关键失败步"}</span>` : "",
      m.error ? `<span class="tag bad">工具报错</span>` : "",
      ...c.findings.filter((f) => f.step === m.step).map((f) => `<span class="tag ${f.severity === "violation" ? "bad" : "warn"}">${esc(zhRule(f.rule))}</span>`),
      ...c.claims.filter((x) => x.step === m.step).map((x) => `<span class="tag bad">${esc(CLAIM_ZH[x.status] || x.status)}</span>`),
    ].join(" ");
    const calls = m.calls.map((k) => `<div class="call">→ ${esc(k.name)}(${esc(JSON.stringify(k.args))})</div>`).join("");
    return `<div class="${cls}" id="step-${m.step}">
      <div class="head"><span>步骤 ${m.step}</span><span class="role">${ROLE_ZH[m.role] || esc(m.role)}</span>${marks}</div>
      ${m.text ? `<div class="body">${esc(m.text)}</div>` : ""}${calls}</div>`;
  }).join("");
}

function renderFacts(c) {
  const t = c.tau2, items = [];
  items.push(`τ² 判定：reward = ${t.reward}，结束方式 ${esc(t.termination)}，数据库${t.db_match ? "一致" : "<b>不一致</b>"}。`);
  if (t.false_success) items.push(`<b>假成功：</b>agent 告诉用户已办好，但数据库不支持这个说法。`);
  for (const x of c.claims) items.push(`${stepLink(x.step)} 声明“${esc(x.sentence)}” → <b>${esc(CLAIM_ZH[x.status] || x.status)}</b>。<div class="note">${esc(x.reason)}</div>`);
  // claim_* findings repeat the claims listed just above
  for (const f of c.findings.filter((f) => !f.rule.startsWith("claim_"))) items.push(`${stepLink(f.step)} 规则 <b>${esc(zhRule(f.rule))}</b>（${f.severity === "violation" ? "违规" : f.severity === "info" ? "观察" : "提醒"}）：${esc(f.message)}`
    + (f.policy ? `<div class="quote">政策原文：${esc(f.policy)}</div>` : ""));
  for (const d of c.db_diff.slice(0, 4)) items.push(`数据库差异：${esc(d.table)} ${esc(d.id)}：` + (d.fields || []).slice(0, 4).map((f) =>
    `<code>${esc(f.path)}</code> 实际 ${esc(JSON.stringify(f.final))}，应为 ${esc(JSON.stringify(f.expected))}`).join("；"));
  for (const e of (c.diagnosis && c.diagnosis.evidence) || []) if (e.valid) items.push(`${stepLink(e.step)} 调查 agent 引用的原文（已逐字核对）：<div class="quote">${esc(e.quote)}</div>`);
  return items;
}

function renderInfer(c, pending) {
  const d = c.diagnosis, items = [];
  if (!d) return [pending || `<span class="note">调查 agent 没有运行。</span>`];
  if (d.error) items.push(`<span class="tag warn">3 次采样中有回复无法解析</span> <span class="note">${esc(d.error)}</span>`);
  items.push(`类别：${zhCat(d.category)}`);
  items.push(`关键步骤：${stepLink(d.critical_step) || "—"}；责任方：${esc(d.failed_agent || "—")}`);
  items.push(`置信度（3 次采样一致率）：<b>${d.confidence === null || d.confidence === undefined ? "—" : pct(d.confidence, 0)}</b> ${d.abstain ? '<span class="tag warn">已弃权</span>' : '<span class="tag good">作答</span>'}`);
  if (d.summary) items.push(`摘要：${esc(d.summary)}`);
  for (const s of d.inference || []) items.push(esc(s));
  if ((d.observed_facts || []).length) items.push(`<span class="note">调查 agent 自述的“事实”（模型生成，未逐条程序核验）：</span><ul class="tight">${d.observed_facts.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>`);
  return items;
}

function renderCheck(c) {
  const d = c.diagnosis, items = [];
  if (d && d.abstain) items.push(`<b>弃权原因：</b>${esc(d.abstain_reason)}`);
  for (const e of (d && d.evidence) || []) if (!e.valid) items.push(`${stepLink(e.step)} 这条引用在原文中找不到，不能当证据：<div class="quote">${esc(e.quote)}</div>`);
  for (const s of (d && d.needs_verification) || []) items.push(esc(s));
  for (const x of c.claims) if (x.status === "unverifiable") items.push(`${stepLink(x.step)} 这句声明无法用数据库核验：“${esc(x.sentence)}”`);
  if (!items.length) items.push(`<span class="note">无</span>`);
  return items;
}

function col(cls, title, items) {
  return `<div class="panel col ${cls}"><h3>${title} <span class="count">${items.length}</span></h3>
    ${items.map((s) => `<div class="item">${s}</div>`).join("")}</div>`;
}

// Whole card. `extra` goes under the three columns (e.g. accept / reject buttons).
function renderCard(c, { pending = "", extra = "", header = "" } = {}) {
  return `${header}
    <div class="audit">
      <div class="panel timeline" id="tl">${renderTimeline(c)}</div>
      <div><div class="cols">
        ${col("fact", "已观察事实 <span class=note>规则 + 数据库核验，确定性</span>", renderFacts(c))}
        ${col("infer", "AI 推断 <span class=note>调查 agent</span>", renderInfer(c, pending))}
        ${col("check", "仍需核实", renderCheck(c))}
      </div>${extra}</div>
    </div>`;
}

function jumpToStep(step) {
  const el = document.getElementById(`step-${step}`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1400);
}

function scrollTimelineTo(step) {
  const tl = document.getElementById("tl"), el = document.getElementById(`step-${step}`);
  if (tl && el) tl.scrollTop = el.offsetTop - tl.offsetTop - 40;
}

document.addEventListener("click", (e) => { const s = e.target.closest(".steplink"); if (s) jumpToStep(s.dataset.step); });
