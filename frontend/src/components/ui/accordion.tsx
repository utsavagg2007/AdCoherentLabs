"use client";

import * as AccordionPrimitive from "@radix-ui/react-accordion";
import { Plus } from "lucide-react";
import { cn } from "@/lib/utils";

export const Accordion = AccordionPrimitive.Root;

export function AccordionItem({
  value,
  question,
  children,
  className,
}: {
  value: string;
  question: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <AccordionPrimitive.Item
      value={value}
      className={cn("border-b border-line last:border-b-0", className)}
    >
      <AccordionPrimitive.Header asChild>
        <h3 className="m-0">
          <AccordionPrimitive.Trigger className="group flex w-full cursor-pointer items-center justify-between gap-4 py-5 text-left text-[15px] font-bold text-body transition-colors duration-200 hover:text-strong">
            {question}
            <Plus
              aria-hidden
              className="size-4 shrink-0 text-subtle transition-transform duration-300 group-hover:text-body group-data-[state=open]:rotate-45"
            />
          </AccordionPrimitive.Trigger>
        </h3>
      </AccordionPrimitive.Header>
      <AccordionPrimitive.Content className="overflow-hidden data-[state=closed]:animate-[accordion-up_0.25s_ease-out] data-[state=open]:animate-[accordion-down_0.3s_ease-out]">
        <div className="pb-5 text-[15px] leading-relaxed text-muted">
          {children}
        </div>
      </AccordionPrimitive.Content>
      <style>{`
        @keyframes accordion-down { from { height: 0 } to { height: var(--radix-accordion-content-height) } }
        @keyframes accordion-up { from { height: var(--radix-accordion-content-height) } to { height: 0 } }
        @media (prefers-reduced-motion: reduce) {
          [data-state] { animation-duration: 0.01ms !important; }
        }
      `}</style>
    </AccordionPrimitive.Item>
  );
}
