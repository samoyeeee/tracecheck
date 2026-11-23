import { Fragment, useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import Markdown from "@/components/Markdown";
import InfoTip from "@/components/InfoTip";

export const REPO = "https://github.com/samoyeeee/tracecheck/blob/main/";

export function Source({ path, label = "来源", className }) {
  if (!path) return null;
  return <a href={REPO + path} target="_blank" rel="noopener" title={path}
            className={cn("text-ink3 underline-offset-2 hover:text-ai hover:underline", className)}>{label}</a>;
}

export const Tag = ({ tone = "fail", className, children }) => (
  <span className={cn("inline-block rounded-full px-2 text-xs font-medium leading-relaxed whitespace-nowrap", {
    fail: "bg-fail-soft text-fail", ai: "bg-ai-soft text-ai", check: "bg-check-soft text-check", pass: "bg-pass-soft text-pass",
  }[tone], className)}>{children}</span>
);

const StepBtn = ({ step, onJump, className }) => step === null || step === undefined ? null : (
  <button onClick={() => onJump(step)}
          className={cn("mr-1.5 rounded bg-paper px-1.5 font-mono text-[11.5px] text-ink2 hover:text-ai cursor-pointer", className)}>{step}</button>
);

const Panel = ({ className, ...p }) => <section className={cn("rounded-[14px] border border-line bg-sheet px-5 py-5 sm:px-[22px]", className)} {...p} />;

// --- verdict ----------------------------------------------------------------------------------------

function Verdict({ r }) {
  const [orig, setOrig] = useState(false);
  const v = r.verdict;
  const version = r.file.split("/").slice(-2, -1)[0];
  return (
    <>
      <div className="mb-2 flex flex-wrap gap-x-3.5 gap-y-1 text-[13px] text-ink3">
        <span>任务 {r.task_id} · 第 {r.trial} 次运行</span>
        <span>Agent 版本：{version}</span>
        <Source path={r.file} label={r.file.split("/").pop()} className="font-mono text-[12.5px]" />
      </div>
      <h1 className="mb-2.5 max-w-[34ch] text-[23px] leading-[1.3] font-black tracking-[-0.015em] sm:text-[30px]">
        <span className={cn("mr-2.5 inline-block -rotate-2 rounded-md border-[2.5px] px-2.5 align-[4px] text-[18px] sm:text-[22px]",
                            v.tone === "good" ? "border-pass text-pass" : "border-fail text-fail")}>{v.kind}</span>
        {v.headline}
      </h1>
      {v.sub && <p className="mb-1.5 max-w-[72ch] text-ink2">{v.sub}</p>}
      <p className="mt-2.5 max-w-[80ch] text-[13.5px] text-ink2">
        用户想做的事：{r.goal.zh || r.goal.original}
        {r.goal.zh && <button onClick={() => setOrig(!orig)} aria-expanded={orig} className="ml-1.5 text-[13px] text-ai cursor-pointer">{orig ? "收起原文" : "看原文"}</button>}
        {orig && <span className="mt-1.5 block text-[13px] text-ink3">{r.goal.original}</span>}
      </p>
    </>
  );
}

// --- tape: the whole run at a glance ------------------------------------------------------------------

function Tape({ r, onJump, active }) {
  const color = { user: "var(--color-usr)", agent: "var(--color-ink)", tool: "var(--color-tool)" };
  const height = { tool: "55%", agent: "80%", user: "100%" };
  return (
    <section aria-label="运行记录概览" className="mt-6 mb-7">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="flex items-center gap-1 text-sm font-bold">整次运行 · {r.tape.length} 步<InfoTip text="每一格是一步，点任意一格跳到那一步。红框是 AI 判定的根源。" /></h3>
        <div className="flex gap-3 text-xs text-ink3">
          {[["用户", color.user], ["Agent 回复", color.agent], ["工具调用", color.tool], ["出错", "var(--color-fail)"]].map(([l, c]) => (
            <span key={l} className="inline-flex items-center gap-1"><i className="inline-block h-[9px] w-[9px] rounded-[2px]" style={{ background: c }} />{l}</span>
          ))}
        </div>
      </div>
      <div className="flex h-[46px] items-end gap-[3px]">
        {r.tape.map((t) => (
          <button key={t.step} onClick={() => onJump(t.step)} aria-label={`第 ${t.step} 步`}
                  className={cn("relative min-w-[4px] flex-1 rounded-t-[3px] transition-opacity hover:opacity-100 cursor-pointer",
                                t.key || active === t.step ? "opacity-100" : "opacity-45",
                                t.crit && "outline-2 outline-offset-2 outline-fail")}
                  style={{ background: t.error ? "var(--color-fail)" : color[t.kind], height: height[t.kind] }}>
            {t.crit && <span className="absolute bottom-[calc(100%+6px)] left-1/2 -translate-x-1/2 text-[11px] font-bold whitespace-nowrap text-fail">根源 {t.step}</span>}
          </button>
        ))}
      </div>
    </section>
  );
}

// --- what differs ---------------------------------------------------------------------------------------

const ITEM_STATUS = {
  ok: { box: "bg-paper", ic: "bg-pass-soft text-pass", mark: "✓", r: "text-ink2" },
  missing: { box: "bg-fail-soft", ic: "bg-fail text-white", mark: "!", r: "font-medium text-fail" },
  extra: { box: "bg-fail-soft", ic: "bg-fail text-white", mark: "+", r: "font-medium text-fail" },
};

function Diff({ r }) {
  const rows = r.comparison;
  const groups = useMemo(() => {
    const g = {};
    rows.forEach((x) => (g[x.entity] ||= []).push(x));
    return Object.entries(g);
  }, [rows]);
  return (
    <Panel aria-labelledby="diffH">
      <h3 id="diffH" className="mb-3 flex items-center gap-1 text-base font-bold">差在哪<InfoTip text="标准答案里的数据库 vs 运行结束时的数据库，只列本任务相关的字段。橙色“待核实”：不一致，但 Agent 没写过这条记录，原因查不清。" /></h3>
      {rows.length === 0 && <p className="text-sm text-ink2">这个任务不需要改数据库，Agent 也没有改动任何记录。</p>}
      {groups.map(([entity, list]) => (
        <div key={entity} className="mb-3 last:mb-0">
          <div className="mb-1.5 text-xs font-medium text-ink3">{entity}</div>
          {list.filter((x) => x.items).map((x) => (
            <div key={x.field} className="mb-2">
              <div className="mb-1 text-[12.5px] text-ink2">{x.field_zh}</div>
              <div className="grid gap-2">
                {x.items.map((it) => {
                  const s = ITEM_STATUS[it.status];
                  return (
                    <div key={it.id} className={cn("grid grid-cols-[22px_1fr_auto] items-center gap-2.5 rounded-[10px] px-3 py-2.5", s.box)}>
                      <span className={cn("grid h-[22px] w-[22px] place-items-center rounded-full text-[13px] font-bold", s.ic)}>{s.mark}</span>
                      <div><div className="font-medium">{it.name}</div>{it.options && <div className="text-[12.5px] text-ink2">{it.options}</div>}</div>
                      <span className={cn("text-right text-[12.5px]", s.r)}>{{ ok: "一致", missing: "缺少", extra: "多出" }[it.status]}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
          {list.filter((x) => !x.items).map((x) => (
            <div key={x.field} className={cn("mt-2 flex flex-wrap justify-between gap-x-3 border-t border-line px-0.5 py-2 text-[13.5px] text-ink2",
                                             x.status !== "ok" && "rounded-md border-t-0 px-2", x.status === "bad" && "bg-fail-soft", x.status === "check" && "bg-check-soft")}>
              <span>{x.field_zh}</span>
              <b className="text-right font-medium text-ink">
                {x.match ? x.actual : <>实际「{x.actual}」<span className="font-normal text-ink2"> · 应为「{x.expected}」</span></>}
                <Tag tone={{ ok: "pass", bad: "fail", check: "check" }[x.status]} className="ml-1.5">{{ ok: "一致", bad: "不一致", check: "待核实" }[x.status]}</Tag>
              </b>
            </div>
          ))}
        </div>
      ))}
    </Panel>
  );
}

// --- how it went wrong -------------------------------------------------------------------------------------

function Chain({ r, onJump, pendingAi }) {
  const chain = r.chain || [];
  const crit = r.ai && !r.ai.abstain ? r.ai.critical_step : null;
  return (
    <Panel aria-labelledby="chainH">
      <h3 id="chainH" className="mb-3 flex items-center gap-1 text-base font-bold">怎么错的<InfoTip text="调查 agent 给出的因果链：从最早的错误到最后的结果。虚线圆点是 AI 推断，实心是记录里能看到的。" /></h3>
      {chain.length === 0 && <p className="text-sm text-ink2">{pendingAi ? "调查 agent 运行中…" : r.ai ? "调查 agent 没有给出因果链。" : "没有运行调查 agent。"}</p>}
      <ol className="relative">
        {chain.map((l, i) => {
          const root = l.step !== null && l.step === crit;
          return (
            <li key={i} className="relative pb-4 pl-[30px] last:pb-0">
              {i < chain.length - 1 && <span className="absolute top-[22px] bottom-0 left-[9px] w-0.5 bg-line" />}
              <span className={cn("absolute top-[3px] left-0 h-5 w-5 rounded-full border-2 bg-sheet",
                                  root ? "border-fail bg-fail" : l.inferred ? "border-dashed border-ai" : "border-ink3")} />
              {l.step !== null
                ? <button onClick={() => onJump(l.step)} className={cn("text-[12.5px] font-medium underline underline-offset-[3px] cursor-pointer", root ? "text-fail" : "text-ink2")}>
                    第 {l.step} 步{root && " · 根源"}</button>
                : <span className="text-[12.5px] text-ink2">结果</span>}
              {l.inferred && <span className="ml-1.5 text-xs text-ai">AI 推断</span>}
              <p className="mt-px text-sm">{l.text}</p>
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}

// --- evidence in three kinds ---------------------------------------------------------------------------------

function Col({ color, dashed, title, tip, children }) {
  return (
    <div className="border-b border-line px-5 py-[18px] last:border-0 md:border-r md:border-b-0">
      <h4 className="mb-0.5 flex items-center gap-2 text-sm font-bold">
        <i className={cn("inline-block rounded-[2px]", dashed ? "h-2 w-2 border-2 border-dashed" : "h-2.5 w-2.5")}
           style={dashed ? { borderColor: color } : { background: color }} />{title}<InfoTip text={tip} />
      </h4>
      <div className="mb-3" />
      {children}
    </div>
  );
}

function Evidence({ r, onJump, pendingAi }) {
  const a = r.ai;
  const li = "text-[13.5px] leading-[1.55]";
  return (
    <>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-base font-bold">证据</h3>
      </div>
      <section aria-label="证据" className="mb-7 grid overflow-hidden rounded-[14px] border border-line bg-sheet md:grid-cols-3">
        <Col color="var(--color-ink)" title="记录里能看到的" tip="来自数据库核验和规则检查，是确定的。">
          <ul className="grid gap-2.5">
            <li className={li}>{r.tau2.reward === 1 ? "τ² 判定成功。" : `τ² 判定失败：${r.tau2.db_match ? "数据库正确，但回复内容不达标" : "数据库最终状态与标准答案不一致"}。`}</li>
            {r.facts.map((f) => f.items.map((x, i) => (
              <li key={`${f.step}-${i}`} className={li}><StepBtn step={i === 0 ? f.step : null} onJump={onJump} />
                {i > 0 && <span className="mr-1.5 inline-block w-[22px]" />}
                <span className={x.severity === "violation" ? "text-fail" : ""}>{x.text}</span>
                {x.severity !== "violation" && <span className="ml-1 text-xs text-ink3">{{ warning: "提醒", info: "观察" }[x.severity]}</span>}
              </li>
            )))}
          </ul>
        </Col>
        <Col color="var(--color-ai)" dashed title="AI 的判断" tip="调查 agent 给出，可能出错。3 格投票条是 3 次独立分析的结果，一致不等于正确。">
          {!a ? <p className="text-sm text-ink2">{pendingAi ? "调查 agent 运行中…" : "没有运行调查 agent。"}</p> : (
            <>
              <ul className="grid gap-2.5">
                <li className={li}><StepBtn step={a.critical_step} onJump={onJump} />
                  {a.abstain ? "拿不准。" : "根源："}{a.category_zh}；责任方：{a.failed_agent_zh}</li>
                {a.summary && <li className={li}>{a.summary}</li>}
                {a.inference.map((s, i) => <li key={i} className={li}>{s}</li>)}
                {a.evidence.map((e, i) => (
                  <li key={"e" + i} className={cn(li, "text-ink2")}><StepBtn step={e.step} onJump={onJump} />“{e.quote.length > 120 ? e.quote.slice(0, 120) + "…" : e.quote}”</li>
                ))}
              </ul>
              <div className="mt-3.5 border-t border-line pt-3 text-[13px] text-ink2">
                {a.samples.filter((s) => s.agrees).length}/3 次指向{a.critical_step !== null ? `第 ${a.critical_step} 步` : "同一结论"}{a.abstain && "，已弃权"}
                <div className="my-1.5 flex gap-1">
                  {a.samples.map((s, i) => (
                    <span key={i} title={`第 ${s.step} 步 · ${s.category_zh}`}
                          className={cn("h-2 w-[26px] rounded-[2px]", s.agrees ? "bg-ai" : "bg-line")} />
                  ))}
                </div>
              </div>
            </>
          )}
        </Col>
        <Col color="var(--color-check)" title="还不确定的" tip="程序和模型都给不出答案的地方。">
          {r.checks.length === 0 ? <p className="text-sm text-ink2">{pendingAi ? "等待调查 agent…" : "没有。"}</p> : (
            <ul className="grid gap-2.5">
              {r.checks.map((c, i) => <li key={i} className={li}><StepBtn step={c.step} onJump={onJump} />{c.text}</li>)}
            </ul>
          )}
        </Col>
      </section>
    </>
  );
}

// --- conversation and tool calls ----------------------------------------------------------------------------------

const CLAIM_ZH = {
  executed_but_differs: "声称已完成，但与数据库不符", not_executed: "声称已完成，但没有执行",
  unrequested_change: "改了用户没要求的内容", wrong_action: "操作类型不对",
  claimed_before_executed: "先声称、后执行", unverifiable: "声称已完成，无法核验",
  partial_disclosed: "部分完成，已如实告知", partial_undisclosed: "部分完成，未告知用户",
};

function LongText({ text, className }) {
  const [more, setMore] = useState(false);
  const long = text.length > 260 || text.split("\n").length > 7;
  return (
    <div className={className}>
      <div className={cn("relative", long && !more && "max-h-32 overflow-hidden")}>
        <Markdown text={text} />
        {long && !more && <div className="absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-[var(--fade)]" />}
      </div>
      {long && <button onClick={() => setMore(!more)} className="text-[12px] text-ai cursor-pointer">{more ? "收起" : "展开全文"}</button>}
    </div>
  );
}

// Raw JSON is not in the page at all until asked for.
function RawData({ raw }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="mt-1 text-[12.5px] text-ai cursor-pointer">
        {open ? "收起原始数据" : "看原始数据"}</button>
      {open && <pre className="mt-1.5 max-h-[220px] overflow-auto rounded-md bg-paper p-2.5 font-mono text-[11.5px] whitespace-pre-wrap">{raw}</pre>}
    </>
  );
}

function Msg({ e, crit }) {
  const user = e.role === "user";
  return (
    <div id={`s${e.step}`} className="grid scroll-mt-24 grid-cols-[34px_1fr] items-start gap-3 rounded-xl p-1 sm:grid-cols-[54px_1fr]">
      <span className="pt-3 text-right font-mono text-[11.5px] text-ink3">{e.step}</span>
      <div className="grid gap-2">
        {e.text && (
          <div style={{ "--fade": user ? "#e9ece7" : "#fff" }}
               className={cn("max-w-[70ch] rounded-xl px-3.5 py-[11px]", user ? "bg-[#e9ece7]" : "border border-line bg-sheet",
                             e.claim && "shadow-[inset_0_0_0_1px_var(--color-fail)]")}>
            <div className="mb-0.5 flex flex-wrap items-center gap-2 text-xs text-ink3">
              {user ? "用户（模拟）" : "Agent"}
              {e.claim && <Tag tone={e.claim === "unverifiable" ? "check" : e.claim === "partial_disclosed" ? "pass" : "fail"}>{CLAIM_ZH[e.claim]}</Tag>}
              {e.rules.map((x) => <Tag key={x} tone="check">{x}</Tag>)}
            </div>
            <LongText text={e.text} />
            {e.zh && <LongText text={e.zh} className="mt-1.5 border-t border-dashed border-line pt-1.5 text-[12.5px] text-ink2" />}
            {e.zh && <span className="text-[11.5px] text-ink3">机器翻译</span>}
          </div>
        )}
        {e.calls.map((c, i) => (
          <div key={i} className={cn("max-w-[70ch] rounded-lg border border-line border-l-[3px] border-l-tool px-3.5 py-2.5",
                                     crit && "border-2 border-l-[5px] border-fail border-l-fail")}>
            <div className="mb-0.5 flex flex-wrap items-center gap-2 text-xs text-ink3">
              工具 · <span className="font-mono">{c.name}</span>
              {crit && <Tag tone="fail">AI 判定的根源</Tag>}
              {!e.text && e.rules.map((x) => <Tag key={x} tone="check">{x}</Tag>)}
            </div>
            <div className="text-[13.5px]"><b className="font-medium">{c.name_zh}</b>：{c.summary}</div>
            <div className={cn("text-[13.5px]", c.ok ? "text-ink2" : "font-medium text-fail")}>
              {c.result_step !== null && <span className="mr-1 font-mono text-[11.5px] text-ink3">{c.result_step}</span>}→ {c.result}
            </div>
            <RawData raw={c.raw} />
          </div>
        ))}
      </div>
    </div>
  );
}

function Timeline({ r, keyOnly, setKeyOnly }) {
  const keys = new Set(r.key_steps);
  const crit = r.ai && !r.ai.abstain ? r.ai.critical_step : null;
  const items = [];
  let hidden = [];
  const flush = () => { if (hidden.length) items.push({ gap: true, from: hidden[0], to: hidden.at(-1) }); hidden = []; };
  for (const e of r.timeline) {
    if (keyOnly && keys.size && !keys.has(e.step)) hidden.push(e.step);
    else { flush(); items.push(e); }
  }
  flush();
  const seg = (on) => cn("rounded-md px-3 py-1 text-[13px] cursor-pointer", on ? "bg-sheet font-medium text-ink shadow-[0_1px_2px_rgba(24,32,43,.08)]" : "text-ink2");
  return (
    <section aria-labelledby="tlH">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h3 id="tlH" className="text-base font-bold">对话和工具调用</h3>
        <div role="group" aria-label="显示范围" className="inline-flex rounded-lg bg-[#e4e7e2] p-[3px]">
          <button aria-pressed={keyOnly} className={seg(keyOnly)} onClick={() => setKeyOnly(true)}>只看关键步骤</button>
          <button aria-pressed={!keyOnly} className={seg(!keyOnly)} onClick={() => setKeyOnly(false)}>完整记录</button>
        </div>
      </div>
      <div className="grid gap-2.5">
        {items.map((e) => e.gap ? (
          <div key={`g${e.from}`} className="rounded-lg border border-dashed border-line p-1 text-center text-[12.5px] text-ink3">
            省略了第 {e.from}–{e.to} 步 · <button onClick={() => setKeyOnly(false)} className="text-ai cursor-pointer">展开完整记录</button>
          </div>
        ) : <Msg key={e.step} e={e} crit={e.step === crit} />)}
      </div>
    </section>
  );
}

function Footer({ r }) {
  const f = r.footer, n = f.new_calls || {};
  return (
    <footer className="mt-8 space-y-1 text-xs text-ink3">
      <div>调查 agent：{f.investigator ? `${f.investigator}，prompt ${f.prompt_version}，3 次采样投票` : "未运行"} ·
        翻译：{f.translator || "未运行"} · 生成本报告时新调用：调查 {n.investigator_web ?? 0} 次、翻译 {n.translate_web ?? 0} 次（其余来自缓存） ·
        花费 ${(f.billed_usd ?? 0).toFixed(2)}，免费档 <Source path={f.cost_log} label="cost_log.csv" /></div>
      <div>原始记录 <Source path={r.file} label={r.file} />{f.investigator_cache && <> · 调查 agent 原始回复 {f.investigator_cache}</>}
        {f.generated_at && <> · 生成于 {f.generated_at}</>}</div>
    </footer>
  );
}

// --- page --------------------------------------------------------------------------------------------------------------

export default function Report({ report: r, pendingAi }) {
  const [keyOnly, setKeyOnly] = useState(true);
  const [active, setActive] = useState(null);
  useEffect(() => { setKeyOnly(true); setActive(null); }, [r.id]);
  // a tool result is shown inside its call's card: jump to the call
  const target = useMemo(() => {
    const m = {};
    r.timeline.forEach((e) => e.calls.forEach((c) => { if (c.result_step !== null) m[c.result_step] = e.step; }));
    return m;
  }, [r]);

  function jump(step) {
    const t = target[step] ?? step;
    setActive(step);
    const go = () => {
      const el = document.getElementById(`s${t}`);
      if (!el) return;
      el.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
      el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
    };
    if (keyOnly && !r.key_steps.includes(t)) { setKeyOnly(false); setTimeout(go, 60); } else go();
  }

  return (
    <div className="flex flex-col">
      {/* on phones the database diff comes before the run overview, so it is on the first screen */}
      <div className="order-2"><Verdict r={r} /></div>
      <div className="order-4 md:order-3"><Tape r={r} onJump={jump} active={active} /></div>
      <div className="order-3 mt-5 mb-2 grid gap-5 md:order-4 md:mt-0 md:mb-7 md:grid-cols-[1.15fr_1fr]">
        <Diff r={r} />
        <Chain r={r} onJump={jump} pendingAi={pendingAi} />
      </div>
      <div className="order-5"><Evidence r={r} onJump={jump} pendingAi={pendingAi} /></div>
      <div className="order-6"><Timeline r={r} keyOnly={keyOnly} setKeyOnly={setKeyOnly} /></div>
      <div className="order-7"><Footer r={r} /></div>
    </div>
  );
}
