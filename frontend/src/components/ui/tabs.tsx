"use client";

import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

export const Tabs = TabsPrimitive.Root;
export const TabsContent = TabsPrimitive.Content;

export function TabsList({
  className,
  children,
  label,
}: {
  className?: string;
  children: React.ReactNode;
  label: string;
}) {
  return (
    <TabsPrimitive.List
      aria-label={label}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-line bg-cream p-1",
        className
      )}
    >
      {children}
    </TabsPrimitive.List>
  );
}

export function TabsTrigger({
  className,
  value,
  children,
}: {
  className?: string;
  value: string;
  children: React.ReactNode;
}) {
  return (
    <TabsPrimitive.Trigger
      value={value}
      className={cn(
        "rounded-full px-3.5 py-1.5 text-[13px] font-semibold text-ink-500 transition-colors hover:text-ink-800 data-[state=active]:bg-coal-800 data-[state=active]:text-ink-900 data-[state=active]:shadow-(--shadow-soft)",
        className
      )}
    >
      {children}
    </TabsPrimitive.Trigger>
  );
}
