import { useEffect, useState } from "react";
import { staticData } from "@/lib/api";
import { Source, Tag } from "@/components/Report";
import InfoTip from "@/components/InfoTip";

const pct = (x, d = 1) => (x === null || x === undefined ? "未测" : `${(x * 100).toFixed(d)}%`);
const nof = (o) => (o && o.of ? `${o.n}/${o.of}` : "未测");

// One metric: number, what it measures, sample size, source file. Not run -> "未测".
function Metric({ value, label, what, sample, src, tone }) {
  const missing = value === "未测";
  return (
    <div className="flex flex-col rounded-[14px] border border-line bg-sheet px-5 py-4">
      <div className="flex items-center gap-1 text-[13px] text-ink2">{label}<InfoTip text={what} /></div>
      <div className={`mt-0.5 text-[28px] font-black tracking-tight tabular-nums ${missing ? "text-check" : tone === "fail" ? "text-fail" : tone === "pass" ? "text-pass" : ""}`}>{value}</div>
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-1.5 text-xs text-ink3">
        <span>{sample}</span><Source path={src} />
      </div>
    </div>
  );
}

function Section({ title, desc, children }) {
  return (
    <section className="mt-8">
      <h2 className="mb-3 flex items-center gap-1 text-base font-bold">{title}<InfoTip text={desc} /></h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{children}</div>
    </section>
  );
}

const ARMS = [
  ["A", "只用大模型", "只给对话记录"],
  ["B", "加规则", "再给规则检查和数据库核验的结果"],
  ["C", "加证据和弃权（v3）", "必须引用原文；3 次采样不一致就弃权"],
  ["v4", "C + 因果链和中文说明（网页用）", "同 C，多写因果链"],
];

export default function Overview() {
  const [o, setO] = useState(null);
  const [r, setR] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    Promise.all([staticData("overview"), staticData("regression")]).then(([a, b]) => { setO(a); setR(b); }).catch((e) => setErr(e.message));
  }, []);
  if (err) return <p className="text-fail">{err}</p>;
  if (!o) return <p className="text-sm text-ink3">加载中…</p>;
  const b = o.baseline, v = o.verify, c = o.categories, cost = o.cost.v;
  const arms = c.arms.v, v4 = c.v4.v, st = c.stability.v, sum = r.summary.v;
  const armRow = (k) => (k === "v4" ? { all: v4.all, abstain: v4.abstain } : arms[k]);
  return (
    <>
      <h1 className="text-2xl font-black tracking-tight">评测总览</h1>

      <Section title="被测的客服 agent" desc={`被测的是 ${o.models.agent}，在 τ²-bench retail 114 个任务上各跑 ${b.k.v} 次。这是“病人”的情况，不是 TraceCheck 的成绩。每个数字都来自真实运行。`}>
        <Metric label="一次跑成功（pass^1）" value={pct(b.pass1.v)} what="随机抽一次运行，任务成功的概率。" sample={`${b.runs.v} 次运行`} src={b.pass1.src} />
        <Metric label="4 次全成功（pass^4）" value={pct(b.pass4.v)} what="同一任务连跑 4 次都成功的比例，衡量稳定性。" sample={`${b.tasks.v} 个任务`} src={b.pass4.src} />
        <Metric label="失败运行" value={String(b.failed_runs.v)} what="τ² 判定 reward < 1 的运行，TraceCheck 要分析的对象。" sample={`共 ${b.runs.v} 次`} src={b.failed_runs.src} />
        <Metric label="花费" value={`$${cost.billed_usd.toFixed(2)}`} what="整个项目的实际账单，全部用免费档。" sample={`${cost.calls.toLocaleString()} 次模型调用`} src={o.cost.src} tone="pass" />
      </Section>

      <Section title="第 ① ② 层：规则检查和数据库核验" desc="确定性的程序，不用模型。">
        <Metric label="失败里有异常信号" value={pct(v.any_signal.v.rate)} what="失败的运行里，TraceCheck 至少报出一个问题（数据库不符、假成功或违规）的比例。" sample={`${nof(v.any_signal.v)} 次失败`} src={v.any_signal.src} tone="pass" />
        <Metric label="能指出具体哪一步" value={pct(v.step_level.v.rate)} what="失败里能定位到一个具体步骤（假成功或违规）的比例；只知道数据库不对不算。" sample={`${nof(v.step_level.v)} 次失败`} src={v.step_level.src} />
        <Metric label="成功运行被误报" value={pct(v.any_signal.v.flagged_passing_runs.rate)} what="τ² 判成功的运行，被 TraceCheck 报了问题的比例。越低越好。" sample={`${nof(v.any_signal.v.flagged_passing_runs)} 次成功`} src={v.any_signal.src} tone="pass" />
        <Metric label="假成功（说法与执行矛盾）" value={String(v.false_success.v.n)} what="当前规则 v3：Agent 说办好了，但它自己成功执行的操作里没有这一项。照用户确认的做了、只是和标准答案不同的不算。" sample={`占失败 ${pct(v.false_success.v.rate)}`} src={v.false_success.src} tone="fail" />
        <Metric label="声称完成，但结果与任务不符" value={String(o.fs_rule1.v.n)} what="旧规则 v1 的信号：Agent 说办好了，而数据库结果和任务标准答案不一致。它不等于 Agent 说谎（常见原因是用户中途改了要求），但正是这个信号在回归测试里检出了代码 bug。" sample={`占失败 ${pct(o.fs_rule1.v.rate)}`} src={o.fs_rule1.src} />
        <Metric label="假成功判断的准确率（v3）" value={o.fs_precision.v.sample_B.rule_v3.precision === null ? "未测" : pct(o.fs_precision.v.sample_B.rule_v3.precision)}
                what="按 v3 抽出、没参与规则设计的样本 B，由项目作者逐条人工核对，判对的比例。在“人工核验”页标注。"
                sample={`已核验 ${o.fs_precision.v.sample_B.rule_v3.cases - o.fs_precision.v.sample_B.rule_v3.unlabelled}/${o.fs_precision.v.sample_B.rule_v3.cases}`} src={o.fs_precision.src} />
        <Metric label="旧规则 v1 的准确率（AI 辅助候选）" value={o.fs_precision.v.sample_A.ai_assisted_rule_v1.precision === null ? "未测" : pct(o.fs_precision.v.sample_A.ai_assisted_rule_v1.precision)}
                what="另一个 AI 助手读样本 A 原始记录给出的建议标签算出的比例，不是人工标注。大部分被它判为误报的，是 Agent 照用户确认的做了、和标准答案不同。"
                sample="样本 A 20 条 · 非人工" src="results/ai_assisted_review/false_success_audit.csv" tone="fail" />
        <Metric label="数据库重放和 τ² 一致" value={nof(v.replay_sanity.v)} what="我们自己重放出的数据库结论，与 τ² 官方判定一致的比例，用来确认核验本身没算错。" sample="可重放的运行" src={v.replay_sanity.src} tone="pass" />
      </Section>

      <section className="mt-8">
        <h2 className="mb-3 flex items-center gap-1 text-base font-bold">第 ③ 层：调查 agent 的三组对照
          <InfoTip text="用 AgentRx 的人工标注做标准答案（τ-bench retail 失败轨迹，预留的测试集 20 条），比较调查 agent 能否找对根源步骤和失败类别。弃权算没答对。样本只有 20 条，组间差 1–2 条在噪声范围内。" /></h2>
        <div className="overflow-x-auto rounded-[14px] border border-line bg-sheet">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="bg-paper2 text-left text-xs text-ink2">
              <tr>{["组", "输入", "根源步骤完全对", "差 1 步以内", "类别对", "步骤和类别都对", "弃权"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody>
              {ARMS.map(([k, name, desc]) => {
                const m = armRow(k);
                return (
                  <tr key={k} className="border-t border-line">
                    <td className="px-3 py-2.5 font-medium whitespace-nowrap">{k} · {name}</td>
                    <td className="px-3 py-2.5 text-ink2">{desc}</td>
                    {["step_exact", "step_within_1", "category", "step_and_category"].map((f) => (
                      <td key={f} className="px-3 py-2.5 tabular-nums">{nof(m.all[f])}</td>
                    ))}
                    <td className="px-3 py-2.5 tabular-nums">{nof(m.abstain)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="mt-2 flex flex-wrap gap-x-4 text-xs text-ink3"><Source path={c.arms.src} label="A/B/C 来源" /><Source path={c.v4.src} label="v4 来源" /></div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="作答时步骤差 1 步以内" value={nof(arms.C.answered.step_within_1)} what="C 组没有弃权的那些案例里，根源步骤差 1 步以内的比例。" sample={`作答 ${arms.C.answered.step_within_1.of} 条`} src={c.arms.src} />
          <Metric label="作答时类别对" value={nof(arms.C.answered.category)} what="C 组作答的案例里，失败类别和人工标注一致的比例。类别是弱项。" sample={`作答 ${arms.C.answered.category.of} 条`} src={c.arms.src} tone="fail" />
          <Metric label="类别对不上：选错步骤" value={`${(o.confusion.v.v3_C.other_step || 0) + (o.confusion.v.v3_C.other_annotated_failure_other_category || 0)}/${14 - o.confusion.v.v3_C.match}`}
                  what="C 组作答但类别不对的案例里，模型选的根源步骤本身就和标注不同的数量。其余是步骤对、叫法不同。两边用的是同一套 AgentRx 分类。最常见的分歧：标注认为是用户信息不足，模型判为 Agent 未遵循流程。"
                  sample="C 组作答 14 条" src={o.confusion.src} />
          <Metric label="重跑后结论不变" value={`${st.answered_in_both_same_category_and_step}/${st.answered_in_both}`} what="同一批记录让调查 agent 重跑一次，两次都作答的案例里，步骤和类别都相同的数量。" sample={`两次都作答 ${st.answered_in_both} 条`} src={c.stability.src} tone="pass" />
          <Metric label="重跑后“答不答”不变" value={`${st.abstain_decision_same}/${st.without_parse_errors_in_either}`} what="同上，但看的是“作答还是弃权”这个决定，两次一致的数量。不稳定主要在这里。" sample="两次都能解析的案例" src={c.stability.src} />
        </div>
      </section>

      <Section title="回归检测：埋已知 bug，看能不能发现" desc="检验方法在运行前登记好。详细结果见“回归对比”。">
        <Metric label="只改提示词的 bug" value={sum.phase4.bugs_detected} what="4 个改提示词的 bug 有几个被检出。其中两个几乎没改变 agent 行为，加上 20 个指标一起校正太严，所以没检出。" sample="每个 20 任务 × 4 次" src="results/eval_regression.json" tone="fail" />
        <Metric label="改代码的 bug" value={sum.phase4b.bugs_detected} what="2 个改工具调用代码的 bug，每个只检验一个事先指定的指标（假成功率），都检出并定位到被改的字段。" sample="每个 20 任务 × 4 次" src="results/eval_regression_4b.json" tone="pass" />
        <Metric label="提示词 bug 真让 agent 变差的"
                value={`${Object.entries(o.bug_effect.v).filter(([k, b]) => ["bug_auth", "bug_transfer", "bug_noconfirm", "bug_param"].includes(k) && b.agent_measurably_worse).length}/4`}
                what="4 个改提示词的 bug 里，τ² 成功率的下降超出 v1 自身噪声区间的个数。只有删掉“先验证身份”这一个真的让 agent 变差了，而它没被检出；其余 3 个没检出是因为 bug 本身没起作用。"
                sample="每个 20 任务 × 4 次" src={o.bug_effect.src} tone="fail" />
        <Metric label="同版本重跑的误报" value={String(r.false_alarms.v.phase4 + r.false_alarms.v.phase4b)} what="v1 自己重跑一遍再和 v1 比，被误判为“有变化”的次数。" sample="全部 114 任务" src="results/eval_regression.json" tone="pass" />
        <Metric label="v2 发布建议" value={r.release.v.verdict} what={`按事先定好的规则给出。总成功率 ${pct(r.success.v.v1)} → ${pct(r.success.v.v2)}，变化不显著。`} sample="114 任务 × 4 次" src={r.release.src} />
      </Section>
    </>
  );
}
