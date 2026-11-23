import { useEffect, useRef, useState } from "react";
import { lastReview, saveReview } from "@/lib/api";

// Fixed bottom bar: is the investigator's judgement right? Locally each answer is
// appended to results/human_review.jsonl (time, original judgement, human judgement).
export default function DecisionBar({ r, onDone, onSay }) {
  const a = r.ai;
  const [mode, setMode] = useState(null); // null | "modify" | "reject"
  const [step, setStep] = useState(a.critical_step ?? "");
  const [category, setCategory] = useState(a.category || "");
  const [note, setNote] = useState("");
  const stepRef = useRef(null);
  const prev = lastReview(r.id);

  useEffect(() => { setMode(null); setStep(a.critical_step ?? ""); setCategory(a.category || ""); setNote(""); }, [r.id]);

  async function save(decision) {
    const entry = {
      time: new Date().toISOString(), report_id: r.id, file: r.file,
      original: { category: a.category, critical_step: a.critical_step, abstain: a.abstain, confidence: a.confidence,
                  model: a.model, prompt_version: a.prompt_version },
      decision,
      human: decision === "accept" ? { category: a.category, critical_step: a.critical_step }
           : { category: category || null, critical_step: step === "" ? null : Number(step) },
      note,
    };
    try {
      const res = await saveReview(entry);
      if (res.where !== "browser") {  // keep a copy in the browser so the queue can show "已复核"
        try {
          const all = JSON.parse(localStorage.getItem("tracecheck.human_review") || "[]");
          localStorage.setItem("tracecheck.human_review", JSON.stringify([...all, { ...entry, where: res.where }]));
        } catch { /* display only */ }
      }
      setMode(null);
      const where = res.where === "browser" ? "（保存在本浏览器）" : "（已写入 results/human_review.jsonl）";
      onDone({ accept: "已确认 AI 的判断", modify: `已保存修改：第 ${step} 步`, reject: "已记录：AI 判断不对" }[decision] + where);
    } catch (e) {
      onSay(e.message);
    }
  }

  function act(k) {
    if (k === "accept") return a.abstain ? (setMode("modify"), onSay("AI 弃权了，请直接写下你的判断")) : save("accept");
    setMode(k);
    if (k === "reject") onSay("请写下你认为的根源，再保存");
    setTimeout(() => stepRef.current?.focus(), 0);
  }

  useEffect(() => {
    const onKey = (e) => {
      if (["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName) || e.metaKey || e.ctrlKey) return;
      const k = { a: "accept", e: "modify", r: "reject" }[e.key.toLowerCase()];
      if (k) act(k);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const question = a.abstain
    ? "AI 拿不准根源在哪一步。你来判断？"
    : `AI 说根源在第 ${a.critical_step} 步：${a.category_zh}。对吗？`;
  const btn = "inline-flex flex-1 items-center justify-center gap-2 rounded-lg border px-2 py-1.5 text-sm font-medium whitespace-nowrap sm:flex-none sm:px-3 sm:py-2";
  const kbd = "hidden rounded border border-current px-1 font-mono text-[11px] opacity-60 sm:inline";
  return (
    <div role="region" aria-label="你的判断"
         className="fixed inset-x-0 bottom-0 z-30 flex flex-wrap items-center gap-2 bg-ink px-3 py-2 text-white sm:gap-4 sm:px-9 sm:py-3.5 lg:left-[280px]">
      <div className="min-w-full flex-1 sm:min-w-[240px]">
        <b className="text-[13.5px] sm:text-[15px]">{question}</b>
        {prev && <span className="hidden text-[12.5px] text-[#b9c1cb] sm:block">
          上次：{{ accept: "确认", modify: "修改", reject: "不对" }[prev.decision]}（{prev.time.slice(0, 16).replace("T", " ")}）</span>}
      </div>
      {!a.abstain && <button className={`${btn} border-white bg-white text-ink`} onClick={() => act("accept")}>对<span className="hidden sm:inline">，确认</span> <kbd className={kbd}>A</kbd></button>}
      <button className={`${btn} border-[#4a5563]`} onClick={() => act("modify")}>{a.abstain ? "我来判断" : <><span className="sm:hidden">部分对</span><span className="hidden sm:inline">部分对，我来改</span></>} <kbd className={kbd}>E</kbd></button>
      {!a.abstain && <button className={`${btn} border-[#4a5563]`} onClick={() => act("reject")}>不对 <kbd className={kbd}>R</kbd></button>}
      {mode && (
        <div className="flex w-full flex-wrap items-end gap-3 border-t border-[#333d49] pt-2">
          <label className="grid gap-1 text-[12.5px] text-[#b9c1cb]">根源在第几步
            <select ref={stepRef} value={step} onChange={(e) => setStep(e.target.value)}
                    className="rounded-md border border-[#4a5563] bg-[#222b36] px-2 py-1.5 text-sm text-white">
              <option value="">不确定</option>
              {r.timeline.map((e) => <option key={e.step} value={e.step}>第 {e.step} 步</option>)}
            </select>
          </label>
          <label className="grid gap-1 text-[12.5px] text-[#b9c1cb]">失败类型
            <select value={category} onChange={(e) => setCategory(e.target.value)}
                    className="rounded-md border border-[#4a5563] bg-[#222b36] px-2 py-1.5 text-sm text-white">
              <option value="">不确定</option>
              {r.categories.map((c) => <option key={c.value} value={c.value}>{c.zh}</option>)}
            </select>
          </label>
          <label className="grid min-w-[200px] flex-1 gap-1 text-[12.5px] text-[#b9c1cb]">补充说明（可选）
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder=""
                   className="rounded-md border border-[#4a5563] bg-[#222b36] px-2 py-1.5 text-sm text-white" />
          </label>
          <button className={`${btn} border-white bg-white text-ink`} onClick={() => save(mode)}>保存{mode === "reject" ? "（记为不对）" : "修改"}</button>
        </div>
      )}
    </div>
  );
}
