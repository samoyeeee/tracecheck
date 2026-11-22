import * as D from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Dialog = D.Root;
export const DialogTrigger = D.Trigger;
export const DialogClose = D.Close;

export function DialogContent({ className, children, title, description }) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-40 bg-black/40" />
      <D.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 w-[calc(100vw-32px)] max-w-xl -translate-x-1/2 -translate-y-1/2 rounded-xl bg-white p-5 shadow-xl",
          className,
        )}
      >
        <D.Title className="text-base font-semibold">{title}</D.Title>
        {description && <D.Description className="mt-1 text-sm text-zinc-500">{description}</D.Description>}
        <div className="mt-4">{children}</div>
        <D.Close className="absolute right-3 top-3 rounded p-1 text-zinc-500 hover:bg-zinc-100" aria-label="关闭">
          <X size={16} />
        </D.Close>
      </D.Content>
    </D.Portal>
  );
}
