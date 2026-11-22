import { cn } from "@/lib/utils";

export function Card({ className, ...props }) {
  return <section className={cn("rounded-xl border border-zinc-200 bg-white shadow-xs", className)} {...props} />;
}
export function CardHeader({ className, ...props }) {
  return <div className={cn("flex flex-wrap items-baseline justify-between gap-2 px-5 pt-4 pb-2", className)} {...props} />;
}
export function CardTitle({ className, ...props }) {
  return <h2 className={cn("text-base font-semibold", className)} {...props} />;
}
export function CardContent({ className, ...props }) {
  return <div className={cn("px-5 pb-5", className)} {...props} />;
}
