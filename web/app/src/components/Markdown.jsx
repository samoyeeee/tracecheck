import { Fragment } from "react";

// Minimal renderer for the agent's markdown-ish messages: **bold**, "- " bullets,
// numbered lines, headings. Everything is rendered as text (no HTML injection).
function inline(text) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <b key={i}>{part.slice(2, -2)}</b> : <Fragment key={i}>{part}</Fragment>);
}

export default function Markdown({ text }) {
  const blocks = [];
  let list = null;
  text.split("\n").forEach((raw, i) => {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (bullet) {
      (list ||= []).push(<li key={i}>{inline(bullet[1])}</li>);
      return;
    }
    if (list) { blocks.push(<ul key={`l${i}`} className="my-1 list-disc space-y-0.5 pl-5">{list}</ul>); list = null; }
    if (!line.trim()) return;
    const h = line.match(/^#+\s+(.*)$/);
    blocks.push(<p key={i} className={h ? "mt-1 font-semibold" : "my-1"}>{inline(h ? h[1] : line)}</p>);
  });
  if (list) blocks.push(<ul key="lend" className="my-1 list-disc space-y-0.5 pl-5">{list}</ul>);
  return <div className="break-words">{blocks}</div>;
}
