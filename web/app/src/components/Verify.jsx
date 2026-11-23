import { useEffect, useState } from "react";
import { getStatus, staticData } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Source, Tag } from "@/components/Report";
import InfoTip from "@/components/InfoTip";

const STATUS_ZH = {
  executed_but_differs: "已执行但结果不符", not_executed: "声称完成但没执行", partial_undisclosed: "部分完成，没告诉用户",
  partial_disclosed: "部分完成，已如实告知", unrequested_change: "改了没要求的内容", wrong_action: "操作类型不对",
  claimed_before_executed: "先声称后执行", unverifiable: "无法核验",
  claim_contradicts_execution: "说法与实际执行矛盾", done_not_goal: "属实，但不是任务要的",
};
const FALSE = new Set(["not_executed", "claim_contradicts_execution", "executed_but_differs"]);
const LABEL = { correct: ["是假成功", "fail"], incorrect: ["不是，规则误判", "pass"], unsure: ["说不清", "check"] };
const TONE = { fail: "border-fail bg-fail-soft text-fail", pass: "border-pass bg-pass-soft text-pass", check: "border-check bg-check-soft text-check" };

function Claims({ claims }) {
  if (!claims.length) return <span className="text-ink3">—</span>;
  return (
    <ul className="grid gap-1">
      {claims.map((c, i) => (
        <li key={i} className="text-[13px]">
          <span className="mr-1.5 rounded bg-paper px-1.5 font-mono text-[11.5px] text-ink2">{c.step}</span>
          <Tag tone={FALSE.has(c.status) ? "fail" : c.status === "partial_disclosed" ? "pass" : "check"}>{STATUS_ZH[c.status] || c.status}</Tag>
          <span className="ml-1.5 text-ink2">“{c.sentence}”</span>
        </li>
      ))}
    </ul>
  );
}

const pct = (p) => (!p || p.precision === null || p.precision === undefined ? "未测"
  : `${(p.precision * 100).toFixed(0)}%（${p.correct}/${p.correct + p.incorrect}）`);

function Card({ label, tip, value, sub }) {
  return (
    <div className="rounded-[14px] border border-line bg-sheet px-5 py-4">
      <div className="flex items-center gap-1 text-[13px] text-ink2">{label}<InfoTip text={tip} /></div>
      <div className={cn("text-[26px] font-black tabular-nums", value === "未测" && "text-check")}>{value}</div>
      {sub && <div className="text-xs text-ink3">{sub}</div>}
    </div>
  );
}

// Human check of the false-success detector: the owner labels each case. AI suggestions are only suggestions.
export default function Verify({ onOpen }) {
  const [data, setData] = useState(null);
  const [sample, setSample] = useState("B");
  const [editable, setEditable] = useState(false);
  const [notes, setNotes] = useState({});
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      const st = await getStatus();
      const local = Boolean(st && !st.public);
      setEditable(local);
      try { setData(local ? await (await fetch("api/fs-review")).json() : await staticData("fs_review")); }
      catch (e) { setErr(e.message); }
    })();
  }, []);

  async function label(c, value, note) {
    setErr("");
    try {
      const res = await fetch("api/fs-review", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sample, case: c.case, label: value, note: note ?? notes[`${sample}${c.case}`] ?? c.human_note ?? "" }) });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error);
      setData((d) => ({ precision: body.precision, cases: { ...d.cases,
        [sample]: d.cases[sample].map((x) => (x.case === c.case ? { ...x, human_label: value, human_note: note ?? notes[`${sample}${c.case}`] ?? x.human_note } : x)) } }));
    } catch (e) { setErr(e.message); }
  }

  if (err && !data) return <p className="text-fail">{err}</p>;
  if (!data) return <p className="text-sm text-ink3">加载中…</p>;
  const p = data.precision, list = data.cases[sample] || [];
  const done = (s) => (data.cases[s] || []).filter((c) => c.human_label).length;
  const seg = (on) => cn("rounded-md px-3 py-1 text-[13px] cursor-pointer", on ? "bg-sheet font-medium shadow-[0_1px_2px_rgba(24,32,43,.08)]" : "text-ink2");
  return (
    <>
      <h1 className="flex items-center gap-1.5 text-2xl font-black tracking-tight">人工核验 · 假成功
        <InfoTip text="假成功（当前规则 v3）：Agent 说办好了，但它自己成功执行的操作里没有这一项。照用户确认的做了、如实说了、只是和任务标准答案不同的，不算假成功。" />
      </h1>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card label="当前规则 v3 准确率" value={pct(p.sample_B.rule_v3)} sub={`样本 B · 已判 ${done("B")}/${(data.cases.B || []).length}`}
              tip="样本 B 是按 v3 规则抽的、没参与任何规则设计的记录，这是 v3 的真实准确率。" />
        <Card label="旧规则 v1 准确率" value={pct(p.sample_A.rule_v1)} sub={`样本 A · 已判 ${done("A")}/${(data.cases.A || []).length}`}
              tip="样本 A 是按旧规则 v1 随机抽的 20 条（加 1 条补充案例，单独统计）。" />
        <Card label="v3 在样本 A 上" value={pct(p.sample_A.rule_v3)} sub="有偏：v3 是看过样本 A 后设计的"
              tip="v3 是读完样本 A 之后设计的，在 A 上的结果会偏好，不能当作准确率。" />
        <Card label="AI 辅助候选（非人工）" value={pct(p.sample_A.ai_assisted_rule_v1)} sub="另一个 AI 对样本 A 的建议标签"
              tip="由另一个 AI 助手读原始记录给出的建议标签，不是人工标注。只有你逐条确认后才算人工标签。" />
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <div role="group" className="inline-flex rounded-lg bg-[#e4e7e2] p-[3px]">
          <button className={seg(sample === "B")} onClick={() => setSample("B")}>样本 B（新规则 · {(data.cases.B || []).length} 条）</button>
          <button className={seg(sample === "A")} onClick={() => setSample("A")}>样本 A（旧规则 · {(data.cases.A || []).length} 条）</button>
        </div>
        {!editable && <span className="text-[13px] text-check">只读：标注只能在本地运行时由项目作者填写</span>}
      </div>
      {err && <p className="mt-3 text-sm text-fail">{err}</p>}
      <div className="mt-4 grid gap-3">
        {list.map((c) => {
          const key = `${sample}${c.case}`, ai = c.ai_suggestion;
          return (
            <section key={key} className={cn("rounded-[14px] border bg-sheet p-4 sm:p-5", c.extra ? "border-ai/40" : "border-line")}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <b className="font-bold">#{c.case}</b><span>任务 {c.task_id} · 第 {c.trial} 次</span>
                  {c.extra && <Tag tone="ai">补充案例</Tag>}
                  <Source path={c.file} label={c.file.split("/").slice(-2).join("/")} className="font-mono text-xs" />
                </div>
                <button onClick={() => onOpen(`${c.file.split("/").slice(-2, -1)[0]}__${c.file.split("/").pop().replace(".json", "")}`)}
                        className="text-[13px] text-ai cursor-pointer">打开完整报告 →</button>
              </div>
              <p className="mt-2 text-[13.5px] text-ink2">任务要求：{c.user_goal}</p>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <div><div className="mb-1 text-xs text-ink3">旧规则 v1 {c.flagged_v1 ? <Tag>判为假成功</Tag> : <Tag tone="pass">不是</Tag>}</div><Claims claims={c.claims_v1} /></div>
                <div><div className="mb-1 text-xs text-ink3">当前规则 v3 {c.flagged_v3 ? <Tag>判为假成功</Tag> : <Tag tone="pass">不是</Tag>}</div><Claims claims={c.claims_v3} /></div>
              </div>
              {ai && (
                <div className="mt-3 rounded-lg bg-ai-soft/60 px-3 py-2 text-[13px]">
                  <span className="font-medium text-ai">AI 助手建议（非人工）：{LABEL[ai.label]?.[0] || ai.label}</span>
                  <span className="ml-1.5 text-ink2">步骤 {ai.evidence_steps} · {ai.reason}</span>
                </div>
              )}
              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
                <span className="text-[13px] text-ink2">你的判断：</span>
                {Object.entries(LABEL).map(([k, [t, tone]]) => (
                  <button key={k} disabled={!editable} onClick={() => label(c, k)}
                          className={cn("rounded-lg border px-3 py-1 text-[13px] disabled:cursor-not-allowed cursor-pointer",
                                        c.human_label === k ? TONE[tone] : "border-line hover:bg-paper", !editable && c.human_label !== k && "opacity-50")}>{t}</button>
                ))}
                {editable && ai && !c.human_label && (
                  <button onClick={() => label(c, ai.label, `采纳 AI 建议：${ai.reason}`.slice(0, 500))}
                          className="rounded-lg border border-ai/40 px-3 py-1 text-[13px] text-ai cursor-pointer">读过原文，采纳 AI 建议</button>
                )}
                {editable && (
                  <input value={notes[key] ?? c.human_note ?? ""} onChange={(e) => setNotes({ ...notes, [key]: e.target.value })}
                         placeholder="理由（可选）" className="min-w-[180px] flex-1 rounded-md border border-line px-2 py-1 text-[13px]" />
                )}
              </div>
            </section>
          );
        })}
      </div>
    </>
  );
}
