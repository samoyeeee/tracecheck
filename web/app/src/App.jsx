import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { getStatus, liveReport, staticIndex, staticReport } from "@/lib/api";
import ImportDialog from "@/components/ImportDialog";
import Report from "@/components/Report";

export const DEFAULT_REPORT = "bug_dropitem__task_2__trial_1";

// Pages 2-4 are still the earlier version until they are redone.
const NAV = [
  { href: "#/", label: "诊断报告" },
  { href: "legacy/audit.html", label: "案例库", old: true },
  { href: "legacy/overview.html", label: "评测总览", old: true },
  { href: "legacy/regression.html", label: "回归对比", old: true },
];

function reportIdFromHash() {
  const m = location.hash.match(/^#\/report\/(.+)$/);
  return m ? decodeURIComponent(m[1]) : DEFAULT_REPORT;
}

export default function App() {
  const [status, setStatus] = useState(undefined);
  const [report, setReport] = useState(null);
  const [progress, setProgress] = useState(null); // {stage, note}
  const [error, setError] = useState("");
  const [index, setIndex] = useState([]);

  // Initial load: a pre-computed report (static demo and local both have them).
  useEffect(() => {
    (async () => {
      setStatus(await getStatus());
      try {
        setIndex(await staticIndex());
        setReport(await staticReport(reportIdFromHash()));
      } catch (e) {
        setError(e.message);
      }
    })();
    const onHash = () => staticReport(reportIdFromHash()).then(setReport).catch((e) => setError(e.message));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // Live analysis: layers 1-2 first (instant), then the investigator + translation.
  async function analyse(body) {
    setError("");
    setProgress({ stage: "rules", note: "规则检查和数据库核验…" });
    try {
      const first = await liveReport(body);
      setReport(first);
      history.replaceState(null, "", "#/live");
      setProgress({ stage: "ai", note: "调查 agent 正在阅读整条记录，并翻译对话（约 10–60 秒）…" });
      const full = await liveReport({ file: first.file }, { ai: Boolean(status?.investigator), zh: true });
      setReport(full);
      setProgress(null);
    } catch (e) {
      setProgress(null);
      setError(e.message);
    }
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-zinc-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2.5">
          <a href="#/" className="font-semibold tracking-tight">TraceCheck</a>
          <nav className="flex min-w-0 flex-1 gap-1 overflow-x-auto text-sm">
            {NAV.map((n) => (
              <a key={n.href} href={n.href}
                 className={`whitespace-nowrap rounded-md px-2.5 py-1 ${n.old ? "text-zinc-500 hover:bg-zinc-100" : "bg-zinc-100 font-medium"}`}>
                {n.label}{n.old && <span className="ml-1 text-[10px] text-zinc-400">旧版</span>}
              </a>
            ))}
          </nav>
          <ImportDialog status={status} index={index} onAnalyse={analyse}
                        onOpen={(id) => { location.hash = `#/report/${encodeURIComponent(id)}`; }} />
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 pb-16 pt-5">
        {progress && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-ai/30 bg-ai-soft px-4 py-2.5 text-sm text-ai">
            <Loader2 size={16} className="animate-spin" /> {progress.note}
          </div>
        )}
        {error && <div className="mb-4 rounded-lg border border-fail/30 bg-fail-soft px-4 py-3 text-sm text-fail">{error}</div>}
        {report ? <Report report={report} status={status} pendingAi={progress?.stage === "ai"} />
                : !error && <p className="text-sm text-zinc-500">加载中…</p>}
      </main>
    </div>
  );
}
