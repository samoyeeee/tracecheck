import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { getStatus, lastReview, liveReport, staticIndex, staticReport } from "@/lib/api";
import ImportDialog from "@/components/ImportDialog";
import Report from "@/components/Report";
import DecisionBar from "@/components/DecisionBar";

// Pages 2-4 are still the earlier version until they are redone.
const NAV = [
  { href: "#/", label: "复核", on: true },
  { href: "legacy/audit.html", label: "案例库" },
  { href: "legacy/overview.html", label: "评测总览" },
  { href: "legacy/regression.html", label: "回归对比" },
];
const TAG = { bad: "bg-fail-soft text-fail", warn: "bg-check-soft text-check", good: "bg-pass-soft text-pass" };

function idFromHash() {
  const m = location.hash.match(/^#\/report\/(.+)$/);
  return m ? decodeURIComponent(m[1]) : null;
}

function Queue({ items, current, reviewed, onPick }) {
  const left = items.filter((x) => !reviewed[x.id]).length;
  return (
    <aside aria-label="待复核列表"
           className="flex gap-2 overflow-x-auto border-b border-line bg-paper2 p-2 lg:sticky lg:top-[57px] lg:block lg:h-[calc(100vh-57px)] lg:overflow-y-auto lg:border-r lg:border-b-0 lg:px-3.5 lg:py-5">
      <h2 className="hidden px-2 pb-2.5 text-[13px] font-medium text-ink2 lg:block"><b className="text-[15px] text-ink">{left}</b> 条等你复核</h2>
      {items.map((x) => (
        <button key={x.id} onClick={() => onPick(x.id)} aria-current={x.id === current}
                className={`block min-w-[210px] shrink-0 rounded-[10px] border px-3 py-2 text-left lg:p-3 lg:mb-1.5 lg:w-full lg:min-w-0
                  ${x.id === current ? "border-line bg-sheet shadow-[0_1px_0_var(--color-line)]" : "border-transparent hover:bg-white/60"}
                  ${x.id !== current && reviewed[x.id] ? "opacity-55" : ""}`}>
          <span className="flex justify-between gap-2 text-[13.5px] font-medium">
            <span>任务 {x.task_id} · 第 {x.trial} 次</span>
            {reviewed[x.id] && <span className="text-[11.5px] text-pass">已复核</span>}
          </span>
          <span className="mt-0.5 block text-[12.5px] leading-snug text-ink2">
            <span className={`mr-1 inline-block rounded-full px-2 text-xs font-medium leading-relaxed ${TAG[x.tone] || TAG.bad}`}>{x.kind}</span>
            {x.short}
          </span>
          <span className="mt-0.5 hidden text-[11.5px] text-ink3 lg:block">{x.version}</span>
        </button>
      ))}
    </aside>
  );
}

export default function App() {
  const [status, setStatus] = useState(undefined);
  const [index, setIndex] = useState([]);
  const [report, setReport] = useState(null);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState("");
  const [reviewed, setReviewed] = useState({});
  const [toast, setToast] = useState(null);

  const refreshReviewed = useCallback((items) => {
    setReviewed(Object.fromEntries(items.map((x) => [x.id, Boolean(lastReview(x.id))])));
  }, []);

  const open = useCallback(async (id) => {
    setError("");
    try { setReport(await staticReport(id)); window.scrollTo(0, 0); } catch (e) { setError(e.message); }
  }, []);

  useEffect(() => {
    (async () => {
      setStatus(await getStatus());
      try {
        const items = await staticIndex();
        setIndex(items);
        refreshReviewed(items);
        await open(idFromHash() || items[0]?.id);
      } catch (e) { setError(e.message); }
    })();
    const onHash = () => { const id = idFromHash(); if (id) open(id); };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [open, refreshReviewed]);

  function pick(id) { location.hash = `#/report/${encodeURIComponent(id)}`; }

  function say(text, tone = "ink") { setToast({ text, tone }); setTimeout(() => setToast(null), 2400); }

  // After a decision: mark it, then move on to the next item still waiting.
  function decided(msg) {
    refreshReviewed(index);
    const live = !index.some((x) => x.id === report.id);
    const order = index.map((x) => x.id);
    const next = order.slice(order.indexOf(report.id) + 1).concat(order).find((id) => id !== report.id && !lastReview(id));
    say(next && !live ? `${msg}，已打开下一条` : msg, "pass");
    if (next && !live) setTimeout(() => pick(next), 600);
  }

  // Live analysis (local server): layers 1-2 first, then the investigator + translation.
  async function analyse(body) {
    setError("");
    setProgress("规则检查和数据库核验…");
    try {
      const first = await liveReport(body);
      setReport(first);
      history.replaceState(null, "", "#/live");
      setProgress("调查 agent 正在阅读整条记录，并翻译对话（约 10–60 秒）…");
      setReport(await liveReport({ file: first.file }, { ai: Boolean(status?.investigator), zh: true }));
    } catch (e) { setError(e.message); }
    setProgress(null);
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 flex items-center gap-5 border-b border-line bg-sheet px-4 py-3 sm:px-6">
        <a href="#/" className="text-[17px] font-black tracking-tight">Trace<i className="not-italic text-fail">Check</i></a>
        <nav aria-label="主导航" className="hidden gap-1 md:flex">
          {NAV.map((n) => (
            <a key={n.href} href={n.href} aria-current={n.on ? "page" : undefined}
               className={`rounded-md px-3 py-1.5 text-sm ${n.on ? "bg-paper font-medium text-ink" : "text-ink2 hover:bg-paper"}`}>
              {n.label}{!n.on && <span className="ml-1 text-[10px] text-ink3">旧版</span>}
            </a>
          ))}
        </nav>
        <div className="flex-1" />
        <ImportDialog status={status} index={index} onAnalyse={analyse} onOpen={pick} />
      </header>

      <div className="lg:grid lg:min-h-[calc(100vh-57px)] lg:grid-cols-[280px_1fr]">
        <Queue items={index} current={report?.id} reviewed={reviewed} onPick={pick} />
        <main className="w-full max-w-[1120px] px-4 pt-4 pb-56 sm:px-9 sm:pt-7 sm:pb-36">
          {progress && (
            <div className="mb-4 flex items-center gap-2 rounded-lg border border-ai/30 bg-ai-soft px-4 py-2.5 text-sm text-ai">
              <Loader2 size={16} className="animate-spin" /> {progress}
            </div>
          )}
          {error && <div className="mb-4 rounded-lg border border-fail/30 bg-fail-soft px-4 py-3 text-sm text-fail">{error}</div>}
          {report ? <Report report={report} pendingAi={Boolean(progress)} /> : !error && <p className="text-sm text-ink3">加载中…</p>}
        </main>
      </div>

      {report?.ai && <DecisionBar r={report} onDone={decided} onSay={say} />}
      {toast && (
        <div role="status"
             className={`fixed bottom-28 left-1/2 z-40 -translate-x-1/2 rounded-lg px-4 py-2 text-sm text-white ${toast.tone === "pass" ? "bg-pass" : "bg-ink"}`}>
          {toast.text}
        </div>
      )}
    </div>
  );
}
