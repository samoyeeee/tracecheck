import * as T from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

export const Tabs = T.Root;
export function TabsList({ className, ...props }) {
  return <T.List className={cn("inline-flex rounded-lg bg-zinc-100 p-1 text-sm", className)} {...props} />;
}
export function TabsTrigger({ className, ...props }) {
  return (
    <T.Trigger
      className={cn(
        "rounded-md px-3 py-1 text-zinc-600 data-[state=active]:bg-white data-[state=active]:text-zinc-900 data-[state=active]:shadow-xs disabled:opacity-40 cursor-pointer",
        className,
      )}
      {...props}
    />
  );
}
export const TabsContent = T.Content;
