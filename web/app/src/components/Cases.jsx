import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { Tag } from "@/components/Report";

const DECISION = { accept: ["已确认", "pass"], modify: ["已修改", "ai"], reject: ["判为不对", "fail"] };

function aiCell(a) {
  if (!a) return <span className="text-ink3">未运行</span>;
  if (a.abstain) return <Tag tone="check">拿不准</Tag>;
  return <span>第 {a.critical_step} 步 · <b className="font-medium">{a.confidence?.toFixed(2)}</b></span>;
}

function reviewCell(rv) {
  if (!rv) return <span className="text-ink3">未复核</span>;
  const [t, tone] = DECISION[rv.decision] || ["已复核", "pass"];
  return <Tag tone={tone}>{t}</Tag>;
}

// Page 2: every pre-analysed run, filterable by failure type and review status.
export default function Cases({ index, reviews, onOpen }) {
  const [kind, setKind] = useState("");
  const [state, setState] = useState("");
  const kinds = useMemo(() => [...new Set(index.map((x) => x.kind))], [index]);
  const rows = index.filter((x) => (!kind || x.kind === kind)
    && (!state || (state === "todo" ? !reviews[x.id] : state === "done" ? reviews[x.id] : x.ai?.abstain)));
  const done = index.filter((x) => reviews[x.id]).length;
  const sel = "rounded-md border border-line bg-sheet px-2 py-1.5 text-sm";
  return (
    <>
      <h1 className="text-2xl font-black tracking-tight">案例库</h1>
      <p className="mt-1 max-w-[80ch] text-[13.5px] text-ink2">
        TraceCheck 预先分析好的 {index.length} 条失败运行：v1 客服 agent 每个失败任务各取 1 条规则没能解释的记录，
        加上复核队列里的几条代表性记录。点任意一行打开诊断报告。已复核 {done} / {index.length}。
      </p>
      <div className="my-4 flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-2">失败类型
          <select value={kind} onChange={(e) => setKind(e.target.value)} className={sel}>
            <option value="">全部</option>
            {kinds.map((k) => <option key={k}>{k}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2">复核状态
          <select value={state} onChange={(e) => setState(e.target.value)} className={sel}>
            <option value="">全部</option><option value="todo">未复核</option><option value="done">已复核</option>
            <option value="unsure">AI 拿不准</option>
          </select>
        </label>
        <span className="text-ink3">{rows.length} 条</span>
      </div>

      <div className="hidden overflow-hidden rounded-[14px] border border-line bg-sheet md:block">
        <table className="w-full text-sm">
          <thead className="bg-paper2 text-left text-xs text-ink2">
            <tr>{["任务", "第几次运行", "版本", "结果", "失败类型", "一句话", "AI 定位 · 置信度", "人工复核"].map((h) =>
              <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((x) => (
              <tr key={x.id} onClick={() => onOpen(x.id)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpen(x.id)}
                  className="cursor-pointer border-t border-line hover:bg-paper focus:bg-paper">
                <td className="px-3 py-2.5 font-medium">任务 {x.task_id}</td>
                <td className="px-3 py-2.5">第 {x.trial} 次</td>
                <td className="px-3 py-2.5 text-ink2">{x.version}</td>
                <td className="px-3 py-2.5">{x.success ? <Tag tone="pass">成功</Tag> : <Tag tone="fail">失败</Tag>}</td>
                <td className="px-3 py-2.5"><Tag tone={x.kind === "假成功" || x.kind === "违反政策" ? "fail" : "check"}>{x.kind}</Tag></td>
                <td className="max-w-[320px] px-3 py-2.5 text-ink2"><span className="line-clamp-2">{x.short}</span></td>
                <td className="px-3 py-2.5 whitespace-nowrap">{aiCell(x.ai)}</td>
                <td className="px-3 py-2.5">{reviewCell(reviews[x.id])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-2 md:hidden">
        {rows.map((x) => (
          <button key={x.id} onClick={() => onOpen(x.id)} className="rounded-xl border border-line bg-sheet p-3 text-left">
            <div className="flex items-center justify-between gap-2 text-[13.5px] font-medium">
              <span>任务 {x.task_id} · 第 {x.trial} 次 <span className="font-normal text-ink3">{x.version}</span></span>
              {reviewCell(reviews[x.id])}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-ink2">
              <Tag tone={x.kind === "假成功" || x.kind === "违反政策" ? "fail" : "check"}>{x.kind}</Tag>
              <span className={cn("text-xs")}>AI：{aiCell(x.ai)}</span>
            </div>
            <div className="mt-1 line-clamp-2 text-[12.5px] text-ink2">{x.short}</div>
          </button>
        ))}
      </div>
    </>
  );
}
