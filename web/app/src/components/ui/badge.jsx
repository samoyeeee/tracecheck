import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badge = cva("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", {
  variants: {
    tone: {
      bad: "bg-fail-soft text-fail",
      warn: "bg-check-soft text-check",
      ai: "bg-ai-soft text-ai",
      good: "bg-pass-soft text-pass",
      muted: "bg-zinc-100 text-zinc-600",
    },
  },
  defaultVariants: { tone: "muted" },
});

export function Badge({ className, tone, ...props }) {
  return <span className={cn(badge({ tone }), className)} {...props} />;
}
