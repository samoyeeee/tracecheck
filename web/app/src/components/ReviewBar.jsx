import { useEffect, useState } from "react";
import { Check, Pencil, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getStatus, lastReview, saveReview } from "@/lib/api";

const DECISION_ZH = { accept: "接受", reject: "驳回", modify: "修改" };

// Accept / reject / modify the investigator's judgement. Locally the result is
// appended to results/human_review.jsonl (time, original, human judgement).
export default function ReviewBar({ r }) {
  const a = r.ai;
  const [editing, setEditing] = useState(false);
  const [category, setCategory] = useState(a.category || "");
  const [step, setStep] = useState(a.critical_step ?? "");
  const [note, setNote] = useState("");
  const [saved, setSaved] = useState(null);
  const [err, setErr] = useState("");
  const [local, setLocal] = useState(false);

  useEffect(() => {
    setSaved(lastReview(r.id));
    setEditing(false);
    setCategory(a.category || "");
    setStep(a.critical_step ?? "");
    getStatus().then((s) => setLocal(Boolean(s)));
  }, [r.id, a.category, a.critical_step]);

  async function submit(decision) {
    setErr("");
    const entry = {
      time: new Date().toISOString(),
      report_id: r.id, file: r.file,
      original: { category: a.category, critical_step: a.critical_step, abstain: a.abstain, confidence: a.confidence,
                  model: a.model, prompt_version: a.prompt_version },
      decision,
      human: decision === "modify" ? { category, critical_step: step === "" ? null : Number(step) }
           : decision === "accept" ? { category: a.category, critical_step: a.critical_step } : null,
      note,
    };
    try {
      const res = await saveReview(entry);
      const record = { ...entry, where: res.where };
      try {  // remember the latest decision for this report in the browser too
        const all = JSON.parse(localStorage.getItem("tracecheck.human_review") || "[]");
        if (res.where !== "browser") localStorage.setItem("tracecheck.human_review", JSON.stringify([...all, record]));
      } catch { /* display only */ }
      setSaved(record);
      setEditing(false);
    } catch (e) {
      setErr(e.message);
    }
  }

  const stepOptions = r.timeline.map((e) => e.step);
  return (
    <div className="rounded-lg border border-ai/20 bg-ai-soft/40 p-3">
      <div className="text-xs font-medium text-zinc-600">你同意这个判断吗？</div>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button size="sm" variant="pass" onClick={() => submit("accept")}><Check size={14} />接受</Button>
        <Button size="sm" variant="fail" onClick={() => submit("reject")}><X size={14} />驳回</Button>
        <Button size="sm" variant="outline" onClick={() => setEditing(!editing)}><Pencil size={14} />修改</Button>
      </div>
      {editing && (
        <div className="mt-3 space-y-2 text-sm">
          <label className="block">
            <span className="text-xs text-zinc-500">失败类别</span>
            <select value={category} onChange={(e) => setCategory(e.target.value)}
                    className="mt-0.5 w-full rounded-md border border-zinc-300 bg-white p-1.5">
              {r.categories.map((c) => <option key={c.value} value={c.value}>{c.zh}（{c.value}）</option>)}
            </select>
          </label>
          <label className="block">
            <span className="text-xs text-zinc-500">关键步骤</span>
            <select value={step} onChange={(e) => setStep(e.target.value)}
                    className="mt-0.5 w-full rounded-md border border-zinc-300 bg-white p-1.5">
              {stepOptions.map((s) => <option key={s} value={s}>步骤 {s}</option>)}
            </select>
          </label>
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="理由（可选）"
                 className="w-full rounded-md border border-zinc-300 bg-white p-1.5" />
          <Button size="sm" variant="ai" onClick={() => submit("modify")}>保存修改</Button>
        </div>
      )}
      {err && <p className="mt-2 text-xs text-fail">{err}</p>}
      <p className="mt-2 text-xs text-zinc-500">
        {saved
          ? <>已{DECISION_ZH[saved.decision]}（{saved.time.slice(0, 16).replace("T", " ")}）
              {saved.human && saved.decision === "modify" && `：改为步骤 ${saved.human.critical_step} · ${saved.human.category}`}
              ，保存在 {saved.where === "browser" ? "本浏览器" : "results/human_review.jsonl"}</>
          : local ? "结果会写入 results/human_review.jsonl，记录时间、原判断和你的判断。"
                  : "线上展示版只保存在本浏览器；本地运行时会写入 results/human_review.jsonl。"}
      </p>
    </div>
  );
}
