"use client";

/**
 * The one input on the page: paste the copy, or drop the creative.
 *
 * The old workbench made you pick a mode first (Upload / Carousel / Paste text
 * / Paste HTML) before it would let you do anything. The mode is inferable —
 * text that starts with a tag is HTML, a dropped file carries its own kind,
 * several images are a carousel — so this infers it and shows what it decided
 * rather than asking.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { CornerDownLeft, Paperclip, X } from "lucide-react";
import {
  KIND_LABEL,
  buildPicked,
  probeVideoDuration,
  type PickedFile,
} from "@/components/app/dropzone";
import { cn } from "@/lib/utils";

export type Draft =
  | { mode: "text"; text: string }
  | { mode: "html"; text: string }
  | { mode: "files"; files: PickedFile[] };

/** HTML if the first non-space character opens a tag. */
export function inferInlineKind(text: string): "text" | "html" {
  return /^\s*<[a-z!/]/i.test(text) ? "html" : "text";
}

export function describeDraft(draft: Draft): string {
  if (draft.mode === "files") {
    const [first] = draft.files;
    if (!first) return "Nothing attached";
    if (draft.files.length > 1) return `Carousel · ${draft.files.length} cards`;
    return first.kind ? KIND_LABEL[first.kind] : "Unsupported file";
  }
  return draft.mode === "html" ? "Pasted HTML" : "Pasted text";
}

export function Composer({
  onSubmit,
  disabled,
  busy,
  capMb,
  allowedKinds,
  maxVideoSeconds,
  placeholder = "Paste the ad copy, or drop the creative here.",
  autoFocus = false,
}: {
  onSubmit: (draft: Draft) => void;
  disabled?: boolean;
  busy?: boolean;
  capMb: number | null;
  allowedKinds: string[] | null;
  maxVideoSeconds: number | null;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<PickedFile[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-grow. Height is derived from content on every render pass that
  // changes `text`, so it never fights the user's scroll position.
  useEffect(() => {
    const el = areaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
  }, [text]);

  const addFiles = useCallback(
    (incoming: File[]) => {
      if (incoming.length === 0) return;
      const picked = incoming
        .slice(0, 10)
        .map((f) => buildPicked(f, capMb, allowedKinds));
      setFiles((prev) => [...prev, ...picked].slice(0, 10));

      for (const p of picked) {
        if (p.kind !== "video" || p.planLocked) continue;
        void probeVideoDuration(p.file).then((dur) => {
          setFiles((prev) =>
            prev.map((x) =>
              x.id === p.id
                ? {
                    ...x,
                    durationSeconds: dur,
                    tooLong:
                      dur != null &&
                      maxVideoSeconds != null &&
                      dur > maxVideoSeconds,
                  }
                : x
            )
          );
        });
      }
    },
    [capMb, allowedKinds, maxVideoSeconds]
  );

  const problem = firstProblem(files, text, capMb, maxVideoSeconds);
  const hasContent = files.length > 0 || text.trim().length > 0;
  const canSend = hasContent && !problem && !disabled && !busy;

  function send() {
    if (!canSend) return;
    if (files.length > 0) {
      onSubmit({ mode: "files", files });
    } else {
      onSubmit({ mode: inferInlineKind(text), text });
    }
    setText("");
    setFiles([]);
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (disabled) return;
        addFiles(Array.from(e.dataTransfer.files));
      }}
      className={cn(
        "rounded-2xl border bg-raised shadow-(--shadow-float) transition-colors duration-150",
        dragging ? "border-brand bg-brand-soft" : "border-line-strong",
        disabled && "opacity-60"
      )}
    >
      {files.length > 0 && (
        <ul className="flex flex-wrap gap-2 border-b border-line p-3">
          {files.map((f) => (
            <li key={f.id}>
              <span
                className={cn(
                  "inline-flex max-w-full items-center gap-2 rounded-lg border py-1 pr-1 pl-2.5 text-[12.5px] font-semibold",
                  f.kind && !f.overCap && !f.planLocked && !f.tooLong
                    ? "border-line-strong bg-tint text-body"
                    : "border-fail-line bg-fail-soft text-fail"
                )}
              >
                <span className="truncate">{f.file.name}</span>
                <button
                  type="button"
                  onClick={() =>
                    setFiles((prev) => prev.filter((x) => x.id !== f.id))
                  }
                  aria-label={`Remove ${f.file.name}`}
                  className="cursor-pointer rounded-md p-1 hover:bg-hover"
                >
                  <X className="size-3.5" />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="flex items-end gap-2 p-2.5">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={disabled}
          aria-label="Attach a creative"
          className="flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-xl text-subtle transition-colors duration-150 hover:bg-hover hover:text-strong focus-visible:ring-2 focus-visible:ring-brand-ring focus-visible:outline-none disabled:cursor-not-allowed"
        >
          <Paperclip className="size-[18px]" />
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          className="sr-only"
          tabIndex={-1}
          onChange={(e) => {
            addFiles(Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />

        <label htmlFor="composer" className="sr-only">
          Ad copy or creative
        </label>
        <textarea
          id="composer"
          ref={areaRef}
          rows={1}
          value={text}
          autoFocus={autoFocus}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          onPaste={(e) => {
            const dropped = Array.from(e.clipboardData.files);
            if (dropped.length > 0) {
              e.preventDefault();
              addFiles(dropped);
            }
          }}
          placeholder={placeholder}
          maxLength={2_000_000}
          className="max-h-[260px] min-h-11 flex-1 resize-none bg-transparent py-2.5 text-[14.5px] leading-relaxed text-strong placeholder:text-faint focus:outline-none"
        />

        <button
          type="button"
          onClick={send}
          disabled={!canSend}
          className="flex h-11 shrink-0 cursor-pointer items-center gap-2 rounded-xl bg-brand px-4 text-[13.5px] font-bold text-brand-on transition-colors duration-150 hover:bg-brand-hover focus-visible:ring-2 focus-visible:ring-brand-ring focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-45"
        >
          {busy ? "Sending" : "Send"}
          <CornerDownLeft className="size-4" aria-hidden />
        </button>
      </div>

      <p
        className={cn(
          "px-4 pb-3 text-[12px] leading-relaxed",
          problem ? "font-semibold text-fail" : "text-subtle"
        )}
        role={problem ? "alert" : undefined}
      >
        {problem ??
          (hasContent
            ? `Sending as ${describeDraft(
                files.length > 0
                  ? { mode: "files", files }
                  : { mode: inferInlineKind(text), text }
              ).toLowerCase()}. Enter to send, Shift+Enter for a new line.`
            : "Uploads are virus-scanned and re-encoded before analysis.")}
      </p>
    </div>
  );
}

function firstProblem(
  files: PickedFile[],
  text: string,
  capMb: number | null,
  maxVideoSeconds: number | null
): string | null {
  if (files.length > 0 && text.trim()) {
    return "Send the file or the pasted copy, not both — they are separate reviews.";
  }
  const bad = files.find((f) => f.kind === null);
  if (bad) {
    return `${bad.file.name} isn't a supported type — use an image, PDF, Word document, video, TXT, or HTML.`;
  }
  const locked = files.find((f) => f.planLocked);
  if (locked && locked.kind) {
    return `${KIND_LABEL[locked.kind]} uploads aren't included in your plan.`;
  }
  const over = files.find((f) => f.overCap);
  if (over) return `${over.file.name} is over your plan's ${capMb} MB cap.`;
  const long = files.find((f) => f.tooLong);
  if (long) {
    return `Videos on your plan are capped at ${maxVideoSeconds}s — ${long.file.name} runs ${Math.round(long.durationSeconds ?? 0)}s.`;
  }
  if (files.length > 1 && files.some((f) => f.kind !== "image")) {
    return "Only images can be sent together, as a carousel.";
  }
  return null;
}
