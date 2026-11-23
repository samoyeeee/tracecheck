import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Play } from "lucide-react";
import { getStatus, staticData } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Source, Tag } from "@/components/Report";
import InfoTip from "@/components/InfoTip";

const STATUS = { passed: ["用例字段正确", "pass"], failed: ["用例字段不对", "fail"], error: ["没能完成", "check"] };
const ERROR_KIND = {
  quota: "模型额度不足", rate_limited: "被限流", run_failed: "运行失败", reset_failed: "环境重置失败",
  unverifiable: "无法核验", bad_version: "版本不存在", internal: "内部错误",
};

// One failed run turned into a regression test: replay chosen versions for real and check the database.
export default function RegressionCase({ id, onOpenReplay }) {
  const [data, setData] = useState(null);
  const [live, setLive] = useState(false);
  const [versions, setVersions] = useState([]);
  const [version, setVersion] = useState("v1");
  const [n, setN] = useState(1);
  const [job, setJob] = useState(null);
  const [err, setErr] = useState("");
  const timer = useRef(null);

  const load = useCallback(async () => {
    const st = await getStatus();
    const isLive = Boolean(st && !st.public);
    setLive(isLive);
    if (isLive) {
      const res = await fetch(`api/rcase/${encodeURIComponent(id)}`);
      const body = await res.json();
      if (!res.ok) throw new Error(body.error);
      setData(body);
      if (body.job) setJob(body.job);
    } else {
      setData(await staticData(`rcases/${id}`));
    }
  }, [id]);

  useEffect(() => {
    load().catch((e) => setErr(e.message));
    getStatus().then((st) => {
      if (st && !st.public) fetch("api/versions").then((r) => r.json()).then((b) => setVersions(b.versions)).catch(() => {});
    });
    return () => clearTimeout(timer.current);
  }, [load]);

  useEffect(() => {
    if (!job || job.state !== "running") return;
    timer.current = setTimeout(async () => {
      try {
        const j = await (await fetch(`api/job/${job.id}`)).json();
        setJob(j);
        if (j.state !== "running") load();
      } catch (e) { setErr(e.message); }
    }, 3000);
    return () => clearTimeout(timer.current);
  }, [job, load]);

  async function run() {
    setErr("");
    try {
      const res = await fetch("api/rcase-run", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case: id, version, n }) });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error);
      setJob(body);
    } catch (e) { setErr(e.message); }
  }

  if (err && !data) return <p className="text-fail">{err}</p>;
  if (!data) return <p className="text-sm text-ink3">加载中…</p>;
  const c = data.case, est = c.estimated_calls_per_replay, running = job?.state === "running";
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-2xl font-black tracking-tight">回归用例</h1>
        {!live && <Tag tone="check">预先运行的结果</Tag>}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 text-[13px] text-ink3">
        <span>任务 {c.task_id}</span><span>来自 {c.source_version || "上传的记录"} 的一次失败</span>
        <Source path={c.source_file} label={c.source_file.split("/").slice(-2).join("/")} className="font-mono" />
        <span className="font-mono" title="初始数据库哈希">DB {c.initial_db_hash.slice(0, 10)}</span>
      </div>

      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <section className="rounded-[14px] border border-line bg-sheet p-5">
          <h2 className="mb-2 flex items-center gap-1 text-base font-bold">原来的失败
            <InfoTip text="创建用例时保存的失败证据：τ² 判定、数据库里和标准答案不一致的字段。" /></h2>
          <p className="font-medium">{c.failure.verdict}</p>
          <ul className="mt-2 grid gap-1 text-[13.5px] text-ink2">
            {c.failure.rows.map((r) => <li key={r.field}><Tag tone="fail">{r.field_zh}</Tag> 实际「{r.actual}」</li>)}
          </ul>
        </section>
        <section className="rounded-[14px] border border-line bg-sheet p-5">
          <h2 className="mb-2 flex items-center gap-1 text-base font-bold">要核对的结果
            <InfoTip text="每次重放结束后，逐项检查这些字段是否等于标准答案。每次重放都从同一个初始数据库开始（运行前会核对哈希）。" /></h2>
          <ul className="grid gap-1 text-[13.5px]">
            {c.expected.map((e) => <li key={e.field}><span className="text-ink2">{e.field_zh}：</span>{e.expected}</li>)}
          </ul>
        </section>
      </div>

      {live && (
        <section className="mt-5 rounded-[14px] border border-line bg-sheet p-5">
          <div className="flex flex-wrap items-end gap-3">
            <label className="grid gap-1 text-[13px] text-ink2">Agent 版本
              <select value={version} onChange={(e) => setVersion(e.target.value)} disabled={running}
                      className="rounded-md border border-line bg-sheet px-2 py-1.5 text-sm">
                {(versions.length ? versions : [{ name: "v1" }]).map((v) => <option key={v.name} value={v.name} title={v.description}>{v.name}</option>)}
              </select>
            </label>
            <label className="grid gap-1 text-[13px] text-ink2">次数
              <select value={n} onChange={(e) => setN(Number(e.target.value))} disabled={running}
                      className="rounded-md border border-line bg-sheet px-2 py-1.5 text-sm">
                {[1, 3, 5].map((k) => <option key={k} value={k}>{k} 次</option>)}
              </select>
            </label>
            <div className="text-[13px] text-ink2">
              预计约 <b className="text-ink">{est.total * n}</b> 次模型调用
              <InfoTip className="ml-1" text={`按原始记录的轮数估算：每次约 ${est.agent} 次被测 agent、${est.user} 次用户模拟器、${est.judge} 次评委调用。实际可能更多或更少，全部记入 results/cost_log.csv。`} />
            </div>
            <button onClick={run} disabled={running}
                    className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white disabled:opacity-50 cursor-pointer">
              {running ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}{running ? "运行中" : "真实重放"}
            </button>
          </div>
          {running && <p className="mt-3 text-sm text-ai">第 {job.done + 1}/{job.n} 次 · {job.message}</p>}
          {job && job.state !== "running" && job.message && job.records.some((r) => r.status === "error") &&
            <p className="mt-3 text-sm text-check">{job.message}</p>}
          {err && <p className="mt-3 text-sm text-fail">{err}</p>}
        </section>
      )}

      <section className="mt-5">
        <h2 className="mb-2 text-base font-bold">重放结果</h2>
        {Object.keys(data.summary).length === 0 && <p className="text-sm text-ink3">还没有重放。</p>}
        <div className="grid gap-2 sm:grid-cols-2">
          {Object.entries(data.summary).map(([v, s]) => (
            <div key={v} className="rounded-[14px] border border-line bg-sheet px-5 py-3">
              <div className="flex items-center justify-between"><b className="font-mono">{v}</b>
                <span className="text-sm tabular-nums">用例 {s.passed}/{s.passed + s.failed} · 整个任务 {s.task_passed}/{s.passed + s.failed}{s.errors ? ` · ${s.errors} 次没跑完` : ""}</span></div>
              <p className="mt-1 text-[13px] text-ink2">{s.statement}</p>
            </div>
          ))}
        </div>
        <div className="mt-3 overflow-x-auto rounded-[14px] border border-line bg-sheet">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="bg-paper2 text-left text-xs text-ink2">
              <tr>{["#", "版本", "用例结果", "核对的字段", "整个任务（τ²）", "调用", "用时", ""].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody>
              {c.replays.map((r) => {
                const [t, tone] = STATUS[r.status] || STATUS.error;
                return (
                  <tr key={r.n} className="border-t border-line align-top">
                    <td className="px-3 py-2.5 tabular-nums">{r.n}</td>
                    <td className="px-3 py-2.5 font-mono">{r.version}</td>
                    <td className="px-3 py-2.5"><Tag tone={tone}>{t}</Tag>
                      {r.error && <div className="mt-1 max-w-[260px] text-xs text-ink2">{ERROR_KIND[r.error_kind] || r.error_kind}：{r.error}</div>}</td>
                    <td className="px-3 py-2.5 text-[13px]">
                      {(r.checks || []).map((k) => (
                        <div key={k.field} className={cn(!k.ok && "text-fail")}>{k.ok ? "✓" : "✗"} {k.field_zh}{!k.ok && `：实际「${k.actual}」`}</div>
                      ))}
                    </td>
                    <td className="px-3 py-2.5">{r.tau2_reward === undefined || r.tau2_reward === null ? "—" : r.tau2_reward === 1 ? <Tag tone="pass">通过</Tag> : <><Tag tone="fail">未通过</Tag>{r.kind && <div className="mt-1 text-xs text-ink2">{r.kind}</div>}</>}</td>
                    <td className="px-3 py-2.5 tabular-nums">{r.model_calls ?? "—"}</td>
                    <td className="px-3 py-2.5 tabular-nums">{r.seconds}s</td>
                    <td className="px-3 py-2.5">{r.file && <button onClick={() => onOpenReplay(r.file)} className="text-[13px] text-ai cursor-pointer">看记录 →</button>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
