import { useEffect, useState } from "react";
import { staticData } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Source, Tag } from "@/components/Report";
import InfoTip from "@/components/InfoTip";

const pct = (x, d = 1) => (x === null || x === undefined ? "未测" : `${(x * 100).toFixed(d)}%`);
const pp = (x) => `${x > 0 ? "+" : ""}${(x * 100).toFixed(1)}`;
const TYPE_ZH = {
  all: "全部任务", cancel: "取消订单", exchange: "换货", modify_items: "修改商品", modify_order_address: "改订单地址",
  modify_payment: "改支付方式", modify_user_address: "改用户地址", no_write: "只查询不写库", return: "退货",
};
const VERDICT = { 可以上线: "pass", 需要再查: "check", 不建议上线: "fail" };
const BUG_ZH = {
  bug_auth: "删掉“先验证用户身份”的政策",
  bug_transfer: "把“转人工”工具说明改模糊",
  bug_noconfirm: "删掉“写库前要用户确认”的政策",
  bug_param: "把修改商品的参数说明写错",
  bug_addr2: "工具调用代码清空地址第二行",
  bug_dropitem: "工具调用代码漏掉最后一件商品",
};

// The release facts are stored in English in results/eval_regression.json.
function factsZh(facts) {
  return facts.map((f) => {
    let m;
    if ((m = f.match(/overall success ([\d.]+) -> ([\d.]+) \(p_holm=([\d.]+)\)/)))
      return `总成功率 ${pct(+m[1])} → ${pct(+m[2])}，变化不显著（校正后 p = ${(+m[3]).toFixed(2)}）`;
    if ((m = f.match(/(\d+) better, (\d+) worse \(v1 vs v1 itself: (\d+) beyond/)))
      return `超出单任务噪声的任务：${m[1]} 个变好、${m[2]} 个变差；作为对照，v1 自己重跑也有 ${m[3]} 个超出`;
    if (/significantly worse rule metrics: none/.test(f)) return "没有任何规则指标显著变差";
    return f;
  });
}

function Change({ row }) {
  const v = row.verdict;
  if (v === "noise") return <span className="text-ink3">无显著变化</span>;
  return <Tag tone={v === "better" ? "pass" : "fail"}>{v === "better" ? "超出噪声 · 改善" : "超出噪声 · 退化"}</Tag>;
}

export default function Regression() {
  const [r, setR] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { staticData("regression").then(setR).catch((e) => setErr(e.message)); }, []);
  if (err) return <p className="text-fail">{err}</p>;
  if (!r) return <p className="text-sm text-ink3">加载中…</p>;
  const rel = r.release.v, bands = r.by_type_bands.v, s = r.success.v;
  const types = Object.entries(bands.by_type);
  const tone = VERDICT[rel.verdict] || "check";
  const worse = types.filter(([k, row]) => k !== "all" && row.pass1.verdict === "worse").map(([k]) => k);
  return (
    <>
      <h1 className="text-2xl font-black tracking-tight">回归对比</h1>

      <section className={cn("mt-5 rounded-[14px] border px-5 py-4", {
        pass: "border-pass/30 bg-pass-soft", check: "border-check/30 bg-check-soft", fail: "border-fail/30 bg-fail-soft" }[tone])}>
        <div className="flex items-center gap-1.5 text-[13px] text-ink2">v2 发布建议
          <InfoTip text="v2 在 v1 的指令上加了三条规则（自己查订单、记住每个请求、少转人工）。判定规则在运行前定好：成功率显著提升且没有规则指标显著变差 → 可以上线；成功率显著下降，或规则指标变差而成功率没提升 → 不建议上线；其他 → 需要再查。" />
          <Source path={r.release.src} /></div>
        <div className={cn("mt-0.5 text-[26px] font-black", { pass: "text-pass", check: "text-check", fail: "text-fail" }[tone])}>{rel.verdict}</div>
        <p className="mt-1 max-w-[80ch]">
          理由：v2 的总成功率从 {pct(s.v1)} 变成 {pct(s.v2)}，{bands.by_type.all.pass1.verdict === "noise" ? "这个变化在噪声范围内" : "这个变化超出了噪声范围"}
          {worse.length > 0 ? `；但${worse.map((k) => `“${TYPE_ZH[k] || k}”`).join("和")}${worse.length > 1 ? "两类" : "这类"}任务的退化超出了噪声区间，上线前要先查清楚。` : "，没有哪类任务超出噪声。"}
        </p>
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-[13.5px] text-ink2">{factsZh(rel.facts).map((f) => <li key={f}>{f}</li>)}</ul>
      </section>

      <section className="mt-8">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="flex items-center gap-1 text-base font-bold">按任务类型<InfoTip text={`事后分析，不在预先登记的方案里。噪声区间：每个任务把 v1 和 v1 重跑的 8 次结果随机分成两组各 4 次，重复 ${bands.draws.toLocaleString()} 次，取两组差值的 2.5%–97.5% 范围。一个任务若包含多种写操作，会在每种类型下各算一次。同时比较 8 种类型，可能碰巧有一种越界，所以“退化”是线索，不是定论。`} /></h2>
          <Source path={r.by_type_bands.src} className="text-xs" />
        </div>
        <div className="grid gap-2 md:hidden">
          {types.map(([k, row]) => (
            <div key={k} className={cn("rounded-xl border border-line bg-sheet p-3 text-sm", row.pass1.verdict === "worse" && "bg-fail-soft/60", row.pass1.verdict === "better" && "bg-pass-soft/60")}>
              <div className="flex items-center justify-between font-medium">{TYPE_ZH[k] || k}<span className="text-xs font-normal text-ink3">{row.tasks} 个任务</span></div>
              <div className="mt-1 tabular-nums">pass^1：{pct(row.pass1.v1)} → {pct(row.pass1.v2)}（{pp(row.pass1.diff)}）</div>
              <div className="text-xs text-ink3">噪声区间 {pp(row.pass1.noise_band[0])} ~ {pp(row.pass1.noise_band[1])} · pass^4 {pct(row.pass4.v1)} → {pct(row.pass4.v2)}</div>
              <div className="mt-1"><Change row={row.pass1} /></div>
            </div>
          ))}
        </div>
        <div className="hidden overflow-x-auto rounded-[14px] border border-line bg-sheet md:block">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-paper2 text-left text-xs text-ink2">
              <tr>
                <th className="px-3 py-2 font-medium">任务类型</th><th className="px-3 py-2 font-medium">任务数</th>
                <th className="px-3 py-2 font-medium">旧版 v1 pass^1</th><th className="px-3 py-2 font-medium">新版 v2 pass^1</th>
                <th className="px-3 py-2 font-medium">变化（百分点）</th><th className="px-3 py-2 font-medium">噪声区间</th>
                <th className="px-3 py-2 font-medium">判断</th><th className="px-3 py-2 font-medium">pass^4 v1 → v2</th>
              </tr>
            </thead>
            <tbody>
              {types.map(([k, row]) => {
                const p1 = row.pass1, p4 = row.pass4;
                return (
                  <tr key={k} className={cn("border-t border-line", p1.verdict === "worse" && "bg-fail-soft/60", p1.verdict === "better" && "bg-pass-soft/60", k === "all" && "font-medium")}>
                    <td className="px-3 py-2.5">{TYPE_ZH[k] || k}</td>
                    <td className="px-3 py-2.5 tabular-nums">{row.tasks}</td>
                    <td className="px-3 py-2.5 tabular-nums">{pct(p1.v1)}</td>
                    <td className="px-3 py-2.5 tabular-nums">{pct(p1.v2)}</td>
                    <td className={cn("px-3 py-2.5 tabular-nums", p1.verdict === "worse" && "text-fail", p1.verdict === "better" && "text-pass", p1.verdict === "noise" && "text-ink3")}>{pp(p1.diff)}</td>
                    <td className="px-3 py-2.5 tabular-nums text-ink3">{pp(p1.noise_band[0])} ~ {pp(p1.noise_band[1])}</td>
                    <td className="px-3 py-2.5"><Change row={p1} /></td>
                    <td className="px-3 py-2.5 tabular-nums text-ink2">{pct(p4.v1)} → {pct(p4.v2)} {p4.verdict !== "noise" && <Change row={p4} />}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-8">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="flex items-center gap-1 text-base font-bold">埋已知 bug：TraceCheck 能不能发现
            <InfoTip text={`检验方法都在运行前提交。第一轮没检出：事后核对发现两个 bug 几乎没改变 agent 的行为，加上每次比较要对 20 个指标一起做多重校正，影响只集中在少数任务时不可能显著。补实验改为只检验一个事先指定的指标（旧规则 v1 的“声称完成但结果与任务不符”率）。按后来的规则 v3（说法与执行矛盾）重算，两个代码 bug 都不显著（校正后 p = 0.07）：v3 只核对商品、不核对地址内容。同版本重跑的误报：${r.false_alarms.v.phase4 + r.false_alarms.v.phase4b} 次。`} /></h2>
          <span className="text-xs text-ink3">
            <Source path={r.plans[0]} label="第一轮方案" /> · <Source path={r.plans[1]} label="补实验方案" /> · <Source path={r.mechanism_src} label="事后核对" />
          </span>
        </div>
        <div className="grid gap-2 md:hidden">
          {r.bugs.map((b) => (
            <div key={b.name} className="rounded-xl border border-line bg-sheet p-3 text-sm">
              <div className="flex items-start justify-between gap-2"><b className="font-medium">{BUG_ZH[b.name] || b.name}</b>
                {b.detected ? <Tag tone="pass">检出{b.localised ? " · 定位到" : ""}</Tag> : <Tag tone="fail">未检出</Tag>}</div>
              <div className="mt-1 text-xs text-ink3">{b.round === "4" ? "第一轮 · 改提示词" : "补实验 · 改代码"} · {pct(b.base_rate)} → {pct(b.other_rate)} · 校正后 p {b.p_holm < 0.001 ? "<0.001" : b.p_holm.toFixed(3)}</div>
            </div>
          ))}
        </div>
        <div className="hidden overflow-x-auto rounded-[14px] border border-line bg-sheet md:block">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="bg-paper2 text-left text-xs text-ink2">
              <tr>{["埋的 bug", "轮次", "检验指标：v1 → bug 版", "校正后 p", "检出", "定位"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody>
              {r.bugs.map((b) => (
                <tr key={b.name} className="border-t border-line">
                  <td className="px-3 py-2.5"><b className="font-medium">{BUG_ZH[b.name] || b.name}</b><div className="font-mono text-[11.5px] text-ink3">{b.name}</div></td>
                  <td className="px-3 py-2.5 text-ink2">{b.round === "4" ? "第一轮 · 改提示词" : "补实验 · 改代码"}</td>
                  <td className="px-3 py-2.5 tabular-nums">{pct(b.base_rate)} → {pct(b.other_rate)}</td>
                  <td className="px-3 py-2.5 tabular-nums">{b.p_holm < 0.001 ? "<0.001" : b.p_holm.toFixed(3)}</td>
                  <td className="px-3 py-2.5">{b.detected ? <Tag tone="pass">检出</Tag> : <Tag tone="fail">未检出</Tag>}</td>
                  <td className="px-3 py-2.5">{b.detected && b.localised ? <Tag tone="pass">定位到</Tag> : <span className="text-ink3">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
