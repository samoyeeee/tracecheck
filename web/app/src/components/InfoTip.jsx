import { useEffect, useRef, useState } from "react";
import { Info } from "lucide-react";

// Explanations live here, out of the page: hover or tap the (i) to read.
export default function InfoTip({ text, className = "" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);
  if (!text) return null;
  return (
    <span ref={ref} className={`relative inline-flex align-middle ${className}`}
          onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button type="button" aria-label="说明" aria-expanded={open} onClick={() => setOpen(!open)}
              className="grid h-4 w-4 place-items-center rounded-full text-ink3 hover:text-ink cursor-pointer">
        <Info size={13} />
      </button>
      {open && (
        <span role="tooltip"
              className="absolute top-5 left-1/2 z-50 w-64 -translate-x-1/2 rounded-lg bg-ink px-3 py-2 text-left text-xs leading-relaxed font-normal text-white shadow-lg">
          {text}
        </span>
      )}
    </span>
  );
}
