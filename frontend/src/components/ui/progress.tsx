import { cn } from "@/lib/utils";

export function Progress({
  value,
  className,
  barClassName,
}: {
  value: number; // 0–100
  className?: string;
  barClassName?: string;
}) {
  const clamped = Math.min(100, Math.max(0, value));
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-raised", className)}
    >
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-500",
          clamped >= 90 ? "bg-rose-400" : clamped >= 70 ? "bg-amber-400" : "bg-brand",
          barClassName,
        )}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
