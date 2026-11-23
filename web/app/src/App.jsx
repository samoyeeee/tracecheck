import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { allReviews, getStatus, liveReport, staticIndex, staticReport } from "@/lib/api";
import Cases from "@/components/Cases";
import Overview from "@/components/Overview";
import Regression from "@/components/Regression";
import Verify from "@/components/Verify";
import ImportDialog from "@/components/ImportDialog";
import Report from "@/components/Report";
import DecisionBar from "@/components/DecisionBar";

const NAV = [
  { page: "review", href: "#/", label: "复核" },
  { page: "cases", href: "#/cases", label: "案例库" },
  { page: "overview", href: "#/overview", label: "评测总览" },
  { page: "regression", href: "#/regression", label: "回归对比" },
  { page: "verify", href: "#/verify", label: "人工核验" },
];

function route() {
  const h = location.hash;
  if (h.startsWith("#/cases")) return { page: "cases" };
  if (h.startsWith("#/overview")) return { page: "overview" };
  if (h.startsWith("#/regression")) return { page: "regression" };
  if (h.startsWith("#/verify")) return { page: "verify" };
  const m = h.match(/^#\/report\/(.+)$/);
  return { page: "review", id: m ? decodeURIComponent(m[1]) : null };
}
const TAG = { bad: "bg-fail-soft text-fail", warn: "bg-check-soft text-check", good: "bg-pass-soft text-pass" };


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
            <span className={`mr-1 inline-block rounded-full px-2 text-xs font-medium leading-relaxed ${TAG[x.tone] || TAG.bad}`}>{x.queue_kind || x.kind}</span>
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
  const [where, setWhere] = useState(route());
  const [report, setReport] = useState(null);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState("");
  const [reviews, setReviews] = useState({});
  const [toast, setToast] = useState(null);

  const refreshReviews = useCallback(async () => setReviews(await allReviews()), []);

  const open = useCallback(async (id) => {
    setError("");
    try { setReport(await staticReport(id)); window.scrollTo(0, 0); } catch (e) { setError(e.message); }
  }, []);

  useEffect(() => {
    (async () => {
      setStatus(await getStatus());
      refreshReviews();
      try {
        const items = await staticIndex();
        setIndex(items);
        const w = route();
        if (w.page === "review") await open(w.id || items.find((x) => x.queue)?.id || items[0]?.id);
      } catch (e) { setError(e.message); }
    })();
    const onHash = () => {
      const w = route();
      setWhere(w);
      if (w.page === "review" && w.id) open(w.id);
      if (w.page !== "review") window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [open, refreshReviews]);

  function pick(id) { location.hash = `#/report/${encodeURIComponent(id)}`; }

  function say(text, tone = "ink") { setToast({ text, tone }); setTimeout(() => setToast(null), 2400); }

  // the queue: items marked for review, plus the one open now if it came from the case library
  const queue = index.filter((x) => x.queue || x.id === report?.id);
  const reviewed = Object.fromEntries(index.map((x) => [x.id, Boolean(reviews[x.id])]));

  // After a decision: refresh, then move on to the next queue item still waiting.
  async function decided(msg) {
    const latest = await allReviews();
    setReviews(latest);
    const order = queue.map((x) => x.id);
    const inQueue = order.includes(report.id);
    const next = order.slice(order.indexOf(report.id) + 1).concat(order).find((id) => id !== report.id && !latest[id]);
    say(next && inQueue ? `${msg}，已打开下一条` : msg, "pass");
    if (next && inQueue) setTimeout(() => pick(next), 600);
  }

  // Live analysis (local server): layers 1-2 first, then the investigator + translation.
  async function analyse(body) {
    setError("");
    if (where.page !== "review") { history.replaceState(null, "", "#/live"); setWhere({ page: "review" }); }
    setProgress("规则检查和数据库核验…");
    try {
      const first = await liveReport(body);
      setReport(first);
      history.replaceState(null, "", "#/live");
      setProgress("调查 agent 正在阅读整条记录，并翻译对话（约 10–60 秒）…");
      const aiLeft = !status?.public || Math.min(status.remaining?.ai_you ?? 0, status.remaining?.ai_today ?? 0) > 0;
      setReport(await liveReport({ file: first.file }, { ai: Boolean(status?.investigator) && aiLeft, zh: aiLeft }));
    } catch (e) { setError(e.message); }
    setProgress(null);
  }

  const review = where.page === "review";
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 flex items-center gap-5 border-b border-line bg-sheet px-4 py-3 sm:px-6">
        <a href="#/" className="text-[17px] font-black tracking-tight">Trace<i className="not-italic text-fail">Check</i></a>
        <nav aria-label="主导航" className="hidden gap-1 md:flex">
          {NAV.map((n) => (
            <a key={n.page} href={n.href} aria-current={where.page === n.page ? "page" : undefined}
               className={`rounded-md px-3 py-1.5 text-sm ${where.page === n.page ? "bg-paper font-medium text-ink" : "text-ink2 hover:bg-paper"}`}>
              {n.label}
            </a>
          ))}
        </nav>
        <div className="flex-1" />
        <ImportDialog status={status} index={index} onAnalyse={analyse} onOpen={pick} />
      </header>
      <nav aria-label="主导航（手机）" className="flex gap-1 overflow-x-auto border-b border-line bg-sheet px-3 py-1.5 md:hidden">
        {NAV.map((n) => (
          <a key={n.page} href={n.href} className={`whitespace-nowrap rounded-md px-3 py-1 text-[13px] ${where.page === n.page ? "bg-paper font-medium" : "text-ink2"}`}>{n.label}</a>
        ))}
      </nav>

      {review ? (
        <div className="lg:grid lg:min-h-[calc(100vh-57px)] lg:grid-cols-[280px_1fr]">
          <Queue items={queue} current={report?.id} reviewed={reviewed} onPick={pick} />
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
      ) : (
        <main className="mx-auto w-full max-w-[1180px] px-4 pt-5 pb-16 sm:px-9 sm:pt-8">
          {where.page === "cases" && <Cases index={index} reviews={reviews} onOpen={pick} />}
          {where.page === "overview" && <Overview />}
          {where.page === "regression" && <Regression />}
          {where.page === "verify" && <Verify onOpen={pick} />}
        </main>
      )}

      {review && report?.ai && <DecisionBar r={report} onDone={decided} onSay={say} />}
      {toast && (
        <div role="status"
             className={`fixed bottom-28 left-1/2 z-40 -translate-x-1/2 rounded-lg px-4 py-2 text-sm text-white ${toast.tone === "pass" ? "bg-pass" : "bg-ink"}`}>
          {toast.text}
        </div>
      )}
    </div>
  );
}
