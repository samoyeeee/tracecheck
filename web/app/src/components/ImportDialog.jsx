import { useEffect, useState } from "react";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogTrigger } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { liveSamples } from "@/lib/api";

// "导入记录": upload / paste a run (local server only) or open a pre-computed report.
export default function ImportDialog({ status, index, onAnalyse, onOpen }) {
  const local = Boolean(status);
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState(local ? "upload" : "sample");
  const [samples, setSamples] = useState([]);
  const [text, setText] = useState("");
  const [file, setFile] = useState(null);
  const [choice, setChoice] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    if (local && open && !samples.length) liveSamples().then(setSamples).catch(() => {});
    setTab(local ? "upload" : "sample");
  }, [local, open]);

  async function submit() {
    setErr("");
    try {
      if (tab === "sample") {
        if (!choice) throw new Error("请选择一条记录");
        if (choice.startsWith("results/")) onAnalyse({ file: choice });
        else onOpen(choice);
      } else {
        const raw = tab === "upload" ? (file ? await file.text() : "") : text.trim();
        if (!raw) throw new Error(tab === "upload" ? "请选择一个 JSON 文件" : "请粘贴一条运行记录");
        let trajectory;
        try { trajectory = JSON.parse(raw); } catch (e) { throw new Error(`不是合法的 JSON：${e.message}`); }
        onAnalyse({ trajectory });
      }
      setOpen(false);
    } catch (e) {
      setErr(e.message);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm"><Upload size={15} />导入记录</Button>
      </DialogTrigger>
      <DialogContent
        title="导入一条 agent 运行记录"
        description={local
          ? "TraceCheck 会当场检查：规则 → 数据库核验 → 调查 agent。"
          : "这是线上展示版：调查 agent 要调用模型，公开网页不能放 API key，所以只能打开预先分析好的记录。本地运行 python -m web.serve 可分析你自己的记录。"}
      >
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="upload" disabled={!local}>上传文件</TabsTrigger>
            <TabsTrigger value="paste" disabled={!local}>粘贴 JSON</TabsTrigger>
            <TabsTrigger value="sample">{local ? "选一条样例" : "预先分析的记录"}</TabsTrigger>
          </TabsList>
          <TabsContent value="upload" className="mt-3 space-y-2">
            <input type="file" accept=".json,application/json" onChange={(e) => setFile(e.target.files[0])}
                   className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-zinc-100 file:px-3 file:py-1.5" />
            <p className="text-xs text-zinc-500">τ²-bench retail 的单次运行记录，需要 task_id 和 messages，例如 results/runs/v1/task_2__trial_0.json。</p>
          </TabsContent>
          <TabsContent value="paste" className="mt-3">
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={7}
                      placeholder='{"task_id": "2", "messages": [...]}'
                      className="w-full rounded-md border border-zinc-300 p-2 font-mono text-xs" />
          </TabsContent>
          <TabsContent value="sample" className="mt-3">
            <select value={choice} onChange={(e) => setChoice(e.target.value)}
                    className="w-full rounded-md border border-zinc-300 bg-white p-2 text-sm">
              <option value="">请选择…</option>
              {index.length > 0 && (
                <optgroup label="预先分析的报告">
                  {index.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
                </optgroup>
              )}
              {samples.length > 0 && (
                <optgroup label="实时分析（本地）">
                  {samples.map((s) => (
                    <option key={s.file} value={s.file}>
                      {s.tag} · 任务 {s.task_id} · 第 {s.trial} 次 · {s.success ? "成功" : "失败"}{s.false_success ? " · 假成功" : ""}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </TabsContent>
        </Tabs>
        {err && <p className="mt-3 text-sm text-fail">{err}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <DialogClose asChild><Button variant="outline" size="sm">取消</Button></DialogClose>
          <Button size="sm" onClick={submit}>开始分析</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
