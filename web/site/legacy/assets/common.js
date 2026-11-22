// Shared helpers for the three pages. The pages only read web/data/*.json
// (made by `python -m web.export`); nothing here calls a model.

const REPO = "https://github.com/samoyeeee/tracecheck/blob/main/";

async function loadData(name) {
  const res = await fetch(`data/${name}.json`);
  if (!res.ok) throw new Error(`data/${name}.json: ${res.status}`);
  return res.json();
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// "来源" link(s) for a repo path, or several joined by " · ".
function src(path) {
  if (!path) return "";
  return String(path).split(" · ").map((p) =>
    `<a class="src" href="${REPO}${esc(p)}" target="_blank" rel="noopener" title="${esc(p)}">来源</a>`).join("");
}

function pct(x, digits = 1) {
  return x === null || x === undefined ? "未测" : `${(x * 100).toFixed(digits)}%`;
}

function nOf(o) {  // {n, of, rate} -> "281/299 (94.0%)"
  return o && o.of ? `${o.n}/${o.of}（${pct(o.rate)}）` : "未测";
}

const CATEGORY_ZH = {
  "Instruction/Plan Adherence Failure": "未遵循指令/计划",
  "Invention of New Information": "编造信息",
  "Invalid Invocation": "无效调用",
  "Misinterpretation of Tool Output": "误读工具输出",
  "Intent-Plan Misalignment": "意图与计划不一致",
  "Underspecified User Intent": "用户意图不明确",
  "Intent Not Supported": "意图不受支持",
  "Guardrails Triggered": "触发护栏",
  "System Failure": "系统故障",
  "Inconclusive": "无法判断",
};

const RULE_ZH = {
  tool_error: "工具报错", repeated_call: "重复调用", abnormal_termination: "异常终止",
  policy_one_action_per_turn: "一回合多动作", policy_authenticate_first: "未先验证身份",
  policy_other_users_order: "操作他人订单", policy_check_status_first: "未先查订单状态",
  policy_wrong_order_status: "订单状态不符", policy_once_per_order: "同一订单重复操作",
  policy_cancel_reason: "取消原因不符", policy_return_refund_method: "退款方式不符",
  policy_payment_must_differ: "支付方式须不同", policy_confirm_before_write: "写库前未确认",
  policy_list_details_before_write: "写库前未列明细", policy_transfer_message: "转人工话术",
  transfer_to_human: "转人工", false_success: "假成功",
  claim_not_executed: "声称完成但未执行", claim_executed_but_differs: "已执行但结果不符",
  claim_unrequested_change: "未被要求的改动", claim_wrong_action: "动作类型不符",
  claim_claimed_before_executed: "先声称后执行", claim_unverifiable: "无法核验",
};

const CLAIM_ZH = {
  verified: "已核实", not_executed: "声称完成但未执行", executed_but_differs: "已执行但结果不符",
  unrequested_change: "未被要求的改动", wrong_action: "动作类型不符",
  claimed_before_executed: "先声称后执行", unverifiable: "无法核验",
};

function zhCat(c) { return c ? `${CATEGORY_ZH[c] || c} <span class="note">${esc(c)}</span>` : "—"; }
function zhRule(r) { return RULE_ZH[r] || r; }

function markNav() {
  const here = location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll("header.top nav a").forEach((a) => {
    if (a.getAttribute("href") === here) a.classList.add("on");
  });
}

function fail(el, err) {
  el.innerHTML = `<div class="banner bad">数据加载失败：${esc(err.message)}。请用本地服务器打开（见 README：
    <code>python -m http.server -d web</code>），直接双击 HTML 文件时浏览器会拦截读取。</div>`;
}

document.addEventListener("DOMContentLoaded", markNav);
