import * as S from "@radix-ui/react-switch";

export function Switch({ id, checked, onCheckedChange, label }) {
  return (
    <label htmlFor={id} className="inline-flex cursor-pointer items-center gap-2 text-sm text-zinc-700">
      <S.Root
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        className="relative h-5 w-9 rounded-full bg-zinc-300 transition-colors data-[state=checked]:bg-zinc-900"
      >
        <S.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]" />
      </S.Root>
      {label}
    </label>
  );
}
