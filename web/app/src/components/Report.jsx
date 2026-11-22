import { Fragment, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, Bot, Check, ChevronDown, CircleHelp, ExternalLink, Sparkles, User, Wrench, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import ReviewBar from "@/components/ReviewBar";
import Markdown from "@/components/Markdown";

export const REPO = "https://github.com/samoyeeee/tracecheck/blob/main/";

export function Source({ path, label = "来源" }) {
  if (!path) return null;
  return (
    <a href={REPO + path} target="_blank" rel="noopener" title={path}
       className="inline-flex items-center gap-0.5 text-xs text-zinc-400 hover:text-ai">
      {label}<ExternalLink size={11} />
    </a>
  );
}

function StepLink({ step, onJump, className }) {
  if (step === null || step === undefined) return null;
  return (
    <button onClick={() => onJump(step)}
            className={cn("shrink-0 rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[11px] text-zinc-600 hover:bg-ai-soft hover:text-ai cursor-pointer", className)}>
      步骤 {step}
    </button>
  );
}

// ① conclusion ---------------------------------------------------------------------------

function Label({ caption, label }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] text-zinc-500">{caption}</div>
      <Badge tone={label.tone} className="mt-0.5 px-2.5 py-1 text-sm">{label.text}</Badge>
    </div>
  );
}

function Conclusion({ r }) {
  const [showGoal, setShowGoal] = useState(false);
  const L = r.verdict.labels;
  return (
    <Card className={cn("border-l-4", r.tau2.reward === 1 ? "border-l-pass" : "border-l-fail")}>
      <CardContent className="pt-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
          <span>任务 {r.task_id} · 第 {r.trial} 次运行</span>
          <Source path={r.file} label={r.file} />
        </div>
        <p className="mt-2 text-lg font-semibold leading-snug sm:text-xl">{r.verdict.sentence}</p>
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
          <Label caption="任务结果" label={L.task} />
          <Label caption="失败类型" label={L.kind} />
          <Label caption="AI 定位" label={L.ai} />
        </div>
        <div className="mt-3 text-sm text-zinc-700">
          <span className="text-zinc-500">用户目标：</span>
          {r.goal.zh || r.goal.original}
          {r.goal.zh && (
            <button onClick={() => setShowGoal(!showGoal)} className="ml-2 text-xs text-zinc-400 hover:text-ai cursor-pointer">
              {showGoal ? "收起原文" : "原文"}
            </button>
          )}
          {showGoal && <div className="mt-1 text-xs text-zinc-500">{r.goal.original}</div>}
        </div>
      </CardContent>
    </Card>
  );
}

// ② expected vs actual -----------------------------------------------------------------------

const ROW_TONE = {
  ok: { row: "", tag: <Badge tone="good"><Check size={12} />一致</Badge> },
  bad: { row: "bg-fail-soft/60", tag: <Badge tone="bad"><X size={12} />不一致</Badge> },
  check: { row: "bg-check-soft/60", tag: <Badge tone="warn"><CircleHelp size={12} />待核实</Badge> },
};

function Comparison({ r }) {
  const rows = r.comparison;
  const groups = useMemo(() => {
    const g = {};
    rows.forEach((x) => (g[x.entity] ||= []).push(x));
    return Object.entries(g);
  }, [rows]);
  const bad = rows.filter((x) => !x.match).length;
  return (
    <Card>
      <CardHeader>
        <CardTitle>期望 vs 实际</CardTitle>
        <span className="text-xs text-zinc-500">
          标准答案的数据库状态与运行结束时的数据库对比，只列本任务相关字段 · {bad ? `${bad} 处不一致` : "全部一致"}
        </span>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-zinc-500">这个任务不需要改数据库，Agent 也没有改动任何记录。</p>
        ) : (
          <>
          <div className="space-y-2 md:hidden">
            {groups.map(([entity, list]) => (
              <div key={entity}>
                <div className="mb-1 text-xs font-medium text-zinc-500">{entity}</div>
                {list.map((x) => (
                  <div key={x.field} className={cn("mb-2 rounded-lg border border-zinc-200 p-3 text-sm", ROW_TONE[x.status].row)}>
                    <div className="flex items-center justify-between font-medium">{x.field_zh}{ROW_TONE[x.status].tag}</div>
                    <div className="mt-1.5 text-xs text-zinc-500">用户要求 / 期望</div><div>{x.expected}</div>
                    <div className="mt-1.5 text-xs text-zinc-500">数据库实际</div><div>{x.actual}</div>
                    {x.missing?.length > 0 && <div className="mt-0.5 text-xs text-fail">缺少：{x.missing.join("、")}</div>}
                    {x.extra?.length > 0 && <div className="mt-0.5 text-xs text-fail">多出：{x.extra.join("、")}</div>}
                  </div>
                ))}
              </div>
            ))}
          </div>
          <div className="hidden md:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-zinc-500">
                  <th className="px-2 py-1.5 font-medium">字段</th>
                  <th className="px-2 py-1.5 font-medium">用户要求 / 期望状态</th>
                  <th className="px-2 py-1.5 font-medium">数据库实际状态</th>
                  <th className="px-2 py-1.5 font-medium">是否一致</th>
                </tr>
              </thead>
              <tbody>
                {groups.map(([entity, list]) => (
                  <Fragment key={entity}>
                    <tr><td colSpan={4} className="px-2 pt-2 text-xs font-medium text-zinc-500">{entity}</td></tr>
                    {list.map((x) => (
                      <tr key={entity + x.field} className={cn("border-t border-zinc-100 align-top", ROW_TONE[x.status].row)}>
                        <td className="px-2 py-2 font-medium whitespace-nowrap">{x.field_zh}</td>
                        <td className="px-2 py-2">{x.expected}</td>
                        <td className="px-2 py-2">
                          {x.actual}
                          {x.missing?.length > 0 && <div className="mt-0.5 text-xs text-fail">缺少：{x.missing.join("、")}</div>}
                          {x.extra?.length > 0 && <div className="mt-0.5 text-xs text-fail">多出：{x.extra.join("、")}</div>}
                        </td>
                        <td className="px-2 py-2">{ROW_TONE[x.status].tag}</td>
                      </tr>
                    ))}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ③ causal chain --------------------------------------------------------------------------------

function Chain({ r, onJump, pendingAi }) {
  const chain = r.chain || [];
  return (
    <Card>
      <CardHeader>
        <CardTitle>因果链</CardTitle>
        <span className="text-xs text-zinc-500">调查 agent 给出的“从哪一步错，到最后结果”的链条；虚线框是推断</span>
      </CardHeader>
      <CardContent>
        {chain.length === 0 ? (
          <p className="text-sm text-zinc-500">{pendingAi ? "调查 agent 运行中…" : r.ai ? "调查 agent 没有给出因果链。" : "没有运行调查 agent。"}</p>
        ) : (
          <ol className="flex flex-col gap-2 md:flex-row md:items-stretch">
            {chain.map((link, i) => (
              <li key={i} className="flex flex-col gap-2 md:flex-1 md:flex-row md:items-center">
                <button
                  onClick={() => link.step !== null && onJump(link.step)}
                  disabled={link.step === null}
                  className={cn(
                    "flex-1 rounded-lg border p-3 text-left text-sm transition-colors",
                    link.inferred ? "border-dashed border-ai/50 bg-white" : "border-zinc-200 bg-zinc-50",
                    link.step === r.ai?.critical_step && "border-fail/60 bg-fail-soft/50",
                    link.step !== null && "hover:border-ai cursor-pointer",
                  )}
                >
                  <div className="mb-1 flex items-center gap-1.5 text-xs">
                    <span className="font-mono text-zinc-500">{link.step !== null ? `步骤 ${link.step}` : "最终结果"}</span>
                    {link.inferred && <Badge tone="ai">推断</Badge>}
                  </div>
                  <div className="leading-snug">{link.text}</div>
                </button>
                {i < chain.length - 1 && <ArrowRight size={16} className="mx-auto shrink-0 rotate-90 text-zinc-400 md:rotate-0" />}
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

// ④ three columns ---------------------------------------------------------------------------------

function Column({ tone, icon, title, hint, children }) {
  const border = { fact: "border-t-zinc-700", ai: "border-t-ai", check: "border-t-check" }[tone];
  return (
    <Card className={cn("flex flex-col border-t-4", border)}>
      <CardHeader className="pb-1">
        <CardTitle className="flex items-center gap-1.5">{icon}{title}</CardTitle>
        <span className="text-xs text-zinc-500">{hint}</span>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col">{children}</CardContent>
    </Card>
  );
}

function Line({ step, onJump, children, tone }) {
  return (
    <li className="flex items-start gap-2 py-1.5 text-sm">
      <StepLink step={step} onJump={onJump} className="mt-0.5" />
      <span className={cn("line-clamp-2", tone === "violation" && "text-fail")} title={typeof children === "string" ? children : undefined}>
        {children}
      </span>
    </li>
  );
}

const SEV = { violation: "违规", warning: "提醒", info: "观察" };

function Facts({ r, onJump }) {
  const t = r.tau2;
  return (
    <ul className="divide-y divide-zinc-100">
      <Line step={null} onJump={onJump} tone={t.reward === 1 ? "" : "violation"}>
        {t.reward === 1 ? "τ² 判定成功" : `τ² 判定失败：${t.db_match ? "数据库正确，但回复内容不达标" : "数据库最终状态与标准答案不一致"}`}
      </Line>
      {r.facts.map((f) => (
        <li key={f.step} className="flex items-start gap-2 py-1.5 text-sm">
          <StepLink step={f.step} onJump={onJump} className="mt-0.5" />
          <div className="min-w-0 space-y-0.5">
            {f.items.map((x, i) => (
              <div key={i} className={cn("line-clamp-2", x.severity === "violation" && "text-fail")}>
                {x.text}<span className="ml-1 text-xs text-zinc-400">{SEV[x.severity]}</span>
              </div>
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}

function AiColumn({ r, onJump, pendingAi }) {
  const a = r.ai;
  if (!a) return <p className="text-sm text-zinc-500">{pendingAi ? "调查 agent 运行中…" : "没有运行调查 agent。"}</p>;
  return (
    <>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
        {a.abstain ? <Badge tone="warn">拿不准，已弃权</Badge> : <Badge tone="ai">作答</Badge>}
        <span>置信度 <b>{a.confidence !== null ? a.confidence.toFixed(2) : "—"}</b></span>
        <span className="text-xs text-zinc-500">（3 次独立判断中 {a.agree} 一致）</span>
      </div>
      <ul className="divide-y divide-zinc-100">
        <Line step={a.critical_step} onJump={onJump}>关键失败：{a.category_zh}；责任方：{a.failed_agent_zh}</Line>
        {a.summary && <Line step={null} onJump={onJump}>{a.summary}</Line>}
        {a.inference.map((s, i) => <Line key={i} step={null} onJump={onJump}>{s}</Line>)}
        {a.evidence.map((e, i) => (
          <Line key={"e" + i} step={e.step} onJump={onJump}>
            <span className="text-zinc-500">证据（已逐字核对）：</span>“{e.quote}”
          </Line>
        ))}
      </ul>
      <div className="mt-auto pt-3"><ReviewBar r={r} /></div>
    </>
  );
}

function Checks({ r, onJump, pendingAi }) {
  if (!r.checks.length)
    return <p className="text-sm text-zinc-500">{pendingAi ? "等待调查 agent…" : "没有需要额外核实的地方。"}</p>;
  return (
    <ul className="divide-y divide-zinc-100">
      {r.checks.map((c, i) => <Line key={i} step={c.step} onJump={onJump}>{c.text}</Line>)}
    </ul>
  );
}

// ⑤ timeline ---------------------------------------------------------------------------------------

const CLAIM_ZH = {
  executed_but_differs: "声称已完成 · 结果不符", not_executed: "声称已完成 · 未执行",
  unrequested_change: "改了没要求的内容", wrong_action: "操作类型不对",
  claimed_before_executed: "先声称后执行", unverifiable: "声称已完成 · 无法核验",
};

function ToolCard({ c }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={cn("rounded-lg border bg-white text-sm", c.ok ? "border-zinc-200" : "border-fail/40")}>
      <button onClick={() => setOpen(!open)} className="flex w-full items-start gap-2 px-3 py-2 text-left cursor-pointer">
        <Wrench size={14} className={cn("mt-0.5 shrink-0", c.write ? "text-zinc-900" : "text-zinc-400")} />
        <span className="min-w-0 flex-1">
          <b className="font-medium">调用 {c.name_zh}</b>：{c.summary}
          <span className={cn("ml-1", c.ok ? "text-pass" : "text-fail")}>→ {c.result}</span>
        </span>
        <ChevronDown size={15} className={cn("mt-0.5 shrink-0 text-zinc-400 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <pre className="max-h-80 overflow-auto border-t border-zinc-100 bg-zinc-50 px-3 py-2 font-mono text-[11px] leading-relaxed text-zinc-600">
          {c.raw}
        </pre>
      )}
    </div>
  );
}

function Bubble({ e }) {
  const [orig, setOrig] = useState(false);
  const [more, setMore] = useState(false);
  const isUser = e.role === "user";
  if (!e.text) return null;
  const text = orig || !e.zh ? e.text : e.zh;
  const long = text.length > 220 || text.split("\n").length > 6;
  const link = isUser ? "text-zinc-400 hover:text-white" : "text-zinc-400 hover:text-ai";
  return (
    <div className={cn("max-w-[92%] rounded-2xl px-3.5 py-2 text-sm sm:max-w-[80%]",
                       isUser ? "ml-auto rounded-tr-sm bg-zinc-800 text-zinc-50" : "rounded-tl-sm bg-white ring-1 ring-zinc-200")}>
      <div className={cn("relative", long && !more && "max-h-28 overflow-hidden")}>
        <Markdown text={text} />
        {long && !more && <div className={cn("absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t", isUser ? "from-zinc-800" : "from-white")} />}
      </div>
      <div className="mt-1 flex gap-3 text-[11px]">
        {long && <button onClick={() => setMore(!more)} className={cn("cursor-pointer", link)}>{more ? "收起" : "展开全文"}</button>}
        {e.zh && <button onClick={() => setOrig(!orig)} className={cn("cursor-pointer", link)}>{orig ? "看中文（机器翻译）" : "机器翻译 · 看原文"}</button>}
      </div>
    </div>
  );
}

function Step({ e, critical }) {
  const isUser = e.role === "user";
  const label = { user: "用户", assistant: "Agent", tool: "工具", system: "系统" }[e.role] || e.role;
  return (
    <div id={`step-${e.step}`} className={cn("scroll-mt-20 rounded-xl p-2", critical && "bg-fail-soft/60 ring-2 ring-fail")}>
      <div className={cn("mb-1 flex flex-wrap items-center gap-1.5 text-xs text-zinc-500", isUser && "justify-end")}>
        {isUser ? <User size={13} /> : <Bot size={13} />}
        <span>{label}</span>
        <span className="font-mono">步骤 {e.step}</span>
        {critical && <Badge tone="bad">关键失败步骤</Badge>}
        {e.claim && <Badge tone={e.claim === "unverifiable" ? "warn" : "bad"}>{CLAIM_ZH[e.claim]}</Badge>}
        {e.rules.map((x) => <Badge key={x} tone="warn"><AlertTriangle size={11} />{x}</Badge>)}
      </div>
      <div className="space-y-1.5">
        <Bubble e={e} />
        {e.calls.map((c, i) => <ToolCard key={i} c={c} />)}
      </div>
    </div>
  );
}

function Timeline({ r, keyOnly, setKeyOnly }) {
  const keys = new Set(r.key_steps);
  const crit = r.ai && !r.ai.abstain ? r.ai.critical_step : null;
  const items = [];
  let hidden = [];
  const flush = () => {
    if (hidden.length) items.push({ gap: hidden.length, from: hidden[0], to: hidden[hidden.length - 1] });
    hidden = [];
  };
  for (const e of r.timeline) {
    if (keyOnly && keys.size && !keys.has(e.step)) hidden.push(e.step);
    else { flush(); items.push(e); }
  }
  flush();
  return (
    <Card>
      <CardHeader>
        <CardTitle>时间线</CardTitle>
        <Switch id="key-only" checked={keyOnly} onCheckedChange={setKeyOnly} label={keyOnly ? "只看关键步骤" : "看完整记录"} />
      </CardHeader>
      <CardContent className="space-y-1">
        {items.map((e) => e.gap ? (
          <button key={`gap-${e.from}`} onClick={() => setKeyOnly(false)}
                  className="w-full rounded-md py-1.5 text-center text-xs text-zinc-400 hover:bg-zinc-100 cursor-pointer">
            ⋯ 省略步骤 {e.from}–{e.to}（{e.gap} 条），点此看完整记录 ⋯
          </button>
        ) : <Step key={e.step} e={e} critical={e.step === crit} />)}
      </CardContent>
    </Card>
  );
}

// ⑥ footer -------------------------------------------------------------------------------------------

function Footer({ r }) {
  const f = r.footer;
  const calls = f.new_calls || {};
  return (
    <footer className="mt-2 space-y-1 border-t border-zinc-200 pt-4 text-xs text-zinc-500">
      <div>
        调查 agent：{f.investigator ? `${f.investigator}（prompt ${f.prompt_version}，3 次采样投票）` : "未运行"} ·
        翻译：{f.translator || "未运行"} ·
        生成本报告时新产生的调用：调查 {calls.investigator_web ?? 0} 次、翻译 {calls.translate_web ?? 0} 次（其余来自缓存） ·
        花费 ${(f.billed_usd ?? 0).toFixed(2)}（免费档） <Source path={f.cost_log} />
      </div>
      <div>原始记录：<Source path={r.file} label={r.file} />{f.investigator_cache && <> · 调查 agent 原始回复：{f.investigator_cache}</>}
        {f.generated_at && <> · 生成于 {f.generated_at}</>}</div>
    </footer>
  );
}

// page ----------------------------------------------------------------------------------------------------

export default function Report({ report: r, pendingAi }) {
  const [keyOnly, setKeyOnly] = useState(true);
  // tool results are folded into their call's card: jump to the call instead
  const stepTarget = useMemo(() => {
    const m = {};
    r.timeline.forEach((e) => e.calls.forEach((c) => { if (c.result_step !== null) m[c.result_step] = e.step; }));
    return m;
  }, [r]);

  function jump(step) {
    const target = stepTarget[step] ?? step;
    const go = () => {
      const el = document.getElementById(`step-${target}`);
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
    };
    if (keyOnly && !r.key_steps.includes(target)) { setKeyOnly(false); setTimeout(go, 60); } else go();
  }

  return (
    <div className="space-y-4">
      <Conclusion r={r} />
      <Comparison r={r} />
      <Chain r={r} onJump={jump} pendingAi={pendingAi} />
      <div className="grid gap-4 lg:grid-cols-3">
        <Column tone="fact" icon={<Check size={16} />} title="已观察事实" hint="规则检查和数据库核验的结果，确定">
          <Facts r={r} onJump={jump} />
        </Column>
        <Column tone="ai" icon={<Sparkles size={16} className="text-ai" />} title="AI 推断" hint="调查 agent 的判断，可能出错">
          <AiColumn r={r} onJump={jump} pendingAi={pendingAi} />
        </Column>
        <Column tone="check" icon={<CircleHelp size={16} className="text-check" />} title="仍需核实" hint="程序和模型都不能确定的地方">
          <Checks r={r} onJump={jump} pendingAi={pendingAi} />
        </Column>
      </div>
      <Timeline r={r} keyOnly={keyOnly} setKeyOnly={setKeyOnly} />
      <Footer r={r} />
    </div>
  );
}
