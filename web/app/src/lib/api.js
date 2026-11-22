// Talks to the local server (python -m web.serve) when it is there; otherwise
// the page is the static online demo and reads pre-computed reports.

let status; // undefined = not checked yet, null = static demo

export async function getStatus() {
  if (status !== undefined) return status;
  try {
    const res = await fetch("api/status");
    status = res.ok && (res.headers.get("content-type") || "").includes("json") ? await res.json() : null;
  } catch {
    status = null;
  }
  return status;
}

async function post(url, body) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

export async function staticIndex() {
  const res = await fetch("data/reports/index.json");
  if (!res.ok) throw new Error("找不到预先生成的报告（data/reports/index.json）");
  return res.json();
}

export async function staticReport(id) {
  const res = await fetch(`data/reports/${encodeURIComponent(id)}.json`);
  if (!res.ok) throw new Error(`找不到报告 ${id}`);
  return res.json();
}

// body: {file} or {trajectory}; ai / zh: run the investigator / translation.
export const liveReport = (body, { ai = false, zh = false } = {}) => post("api/report", { ...body, ai, zh });
export const liveSamples = async () => (await (await fetch("api/samples")).json()).samples;

const STORE = "tracecheck.human_review";

// Human review of the AI judgement: results/human_review.jsonl locally, browser storage online.
export async function saveReview(entry) {
  const st = await getStatus();
  if (st) return { where: "results/human_review.jsonl", ...(await post("api/review", entry)) };
  try {
    const all = JSON.parse(localStorage.getItem(STORE) || "[]");
    all.push(entry);
    localStorage.setItem(STORE, JSON.stringify(all));
    return { where: "browser" };
  } catch {
    throw new Error("浏览器禁止了本地存储，复核结果没有保存");
  }
}

export function lastReview(reportId) {
  try {
    const all = JSON.parse(localStorage.getItem(STORE) || "[]");
    return all.filter((e) => e.report_id === reportId).pop() || null;
  } catch {
    return null;
  }
}
