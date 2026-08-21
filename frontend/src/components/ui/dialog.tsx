"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  className,
  children,
  title,
  description,
  hideClose,
}: {
  className?: string;
  children: React.ReactNode;
  title: string;
  description?: string;
  hideClose?: boolean;
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-canvas/55 backdrop-blur-[3px] data-[state=open]:animate-fade-in" />
      <DialogPrimitive.Content
        className={cn(
          "fixed top-1/2 left-1/2 z-50 w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-line bg-surface p-6 shadow-(--shadow-float) focus:outline-none data-[state=open]:animate-fade-up",
          className
        )}
      >
        <DialogPrimitive.Title className="text-lg font-bold text-strong">
          {title}
        </DialogPrimitive.Title>
        {description ? (
          <DialogPrimitive.Description className="mt-1 text-sm text-subtle">
            {description}
          </DialogPrimitive.Description>
        ) : (
          <DialogPrimitive.Description className="sr-only">
            {title}
          </DialogPrimitive.Description>
        )}
        <div className="mt-4">{children}</div>
        {!hideClose && (
          <DialogPrimitive.Close
            aria-label="Close dialog"
            className="absolute top-4 right-4 rounded-full p-1.5 text-subtle transition-colors hover:bg-tint-2 hover:text-body"
          >
            <X className="size-4" />
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
