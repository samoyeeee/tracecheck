import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";

const button = cva(
  "inline-flex items-center justify-center gap-1.5 rounded-md text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ai cursor-pointer",
  {
    variants: {
      variant: {
        default: "bg-zinc-900 text-white hover:bg-zinc-700",
        outline: "border border-zinc-300 bg-white hover:bg-zinc-100",
        ghost: "hover:bg-zinc-100",
        ai: "bg-ai text-white hover:bg-ai/90",
        pass: "border border-pass/40 bg-pass-soft text-pass hover:bg-pass/10",
        fail: "border border-fail/40 bg-fail-soft text-fail hover:bg-fail/10",
      },
      size: { sm: "h-8 px-3", md: "h-9 px-4", xs: "h-7 px-2 text-xs" },
    },
    defaultVariants: { variant: "default", size: "md" },
  },
);

export function Button({ className, variant, size, ...props }) {
  return <button className={cn(button({ variant, size }), className)} {...props} />;
}
