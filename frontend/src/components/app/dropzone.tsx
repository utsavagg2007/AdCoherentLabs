"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FileText, FileWarning, ImageIcon, UploadCloud, X } from "lucide-react";
import { cn } from "@/lib/utils";

export interface PickedFile {
  file: File;
  id: string;
  previewUrl: string | null; // object URL for images
  overCap: boolean;
  unsupported: boolean;
}

const SUPPORTED_MIME = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
  "text/plain",
  "text/html",
]);
const SUPPORTED_EXT = /\.(png|jpe?g|webp|gif|txt|html?)$/i;

export function buildPicked(file: File, capMb: number | null): PickedFile {
  const isImage = file.type.startsWith("image/");
  const unsupported = file.type
    ? !SUPPORTED_MIME.has(file.type)
    : !SUPPORTED_EXT.test(file.name);
  return {
    file,
    id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`,
    previewUrl: isImage ? URL.createObjectURL(file) : null,
    overCap: capMb !== null ? file.size > capMb * 1024 * 1024 : false,
    unsupported,
  };
}

export function Dropzone({
  files,
  onAdd,
  onRemove,
  multiple,
  maxFiles,
  capMb,
  imagesOnly,
}: {
  files: PickedFile[];
  onAdd: (files: File[]) => void;
  onRemove: (id: string) => void;
  multiple: boolean;
  maxFiles: number;
  capMb: number | null;
  imagesOnly?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);

  useEffect(
    () => () => {
      for (const f of files) if (f.previewUrl) URL.revokeObjectURL(f.previewUrl);
    },
    // revoke only on unmount — object URLs stay valid while listed
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  const accept = imagesOnly
    ? "image/png,image/jpeg,image/webp,image/gif"
    : "image/png,image/jpeg,image/webp,image/gif,text/plain,text/html,.txt,.html,.htm";

  const handleFiles = useCallback(
    (list: FileList | File[]) => {
      const incoming = Array.from(list);
      if (!incoming.length) return;
      onAdd(incoming);
    },
    [onAdd]
  );

  const atCapacity = files.length >= maxFiles;

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-label={
          multiple ? "Add carousel cards (drag and drop or browse)" : "Add a creative file (drag and drop or browse)"
        }
        onClick={() => !atCapacity && inputRef.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && !atCapacity) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragEnter={(e) => {
          e.preventDefault();
          dragDepth.current += 1;
          setDragging(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          dragDepth.current -= 1;
          if (dragDepth.current <= 0) setDragging(false);
        }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          dragDepth.current = 0;
          setDragging(false);
          if (!atCapacity) handleFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors",
          dragging
            ? "border-violet-400 bg-violet-50"
            : "border-zinc-300 bg-cream/60 hover:border-violet-300 hover:bg-violet-50/40",
          atCapacity && "cursor-not-allowed opacity-60"
        )}
      >
        <UploadCloud
          className={cn("size-8", dragging ? "text-violet-600" : "text-zinc-400")}
          aria-hidden
        />
        <p className="mt-3 text-[14px] font-bold text-ink-900">
          {atCapacity
            ? `Maximum ${maxFiles} card${maxFiles > 1 ? "s" : ""} reached`
            : dragging
              ? "Drop to add"
              : multiple
                ? "Drag carousel cards here, or browse"
                : "Drag a creative here, or browse"}
        </p>
        <p className="mt-1 text-[12px] leading-relaxed text-zinc-500">
          {imagesOnly ? "PNG, JPEG, WebP, GIF" : "PNG, JPEG, WebP, GIF, TXT, HTML"}
          {capMb ? ` · up to ${capMb} MB on your plan` : ""}
        </p>
        <p className="mt-0.5 text-[11.5px] text-zinc-400">
          PDF and video aren&apos;t analyzable in v1 — uploads of those are
          rejected before any credits are charged.
        </p>
        <input
          ref={inputRef}
          type="file"
          className="sr-only"
          accept={accept}
          multiple={multiple}
          onChange={(e) => {
            if (e.target.files) handleFiles(e.target.files);
            e.target.value = "";
          }}
          tabIndex={-1}
        />
      </div>

      {files.length > 0 && (
        <ul className="mt-3 grid gap-2 sm:grid-cols-2">
          {files.map((f, i) => (
            <li
              key={f.id}
              className={cn(
                "flex items-center gap-3 rounded-xl border bg-white p-2.5",
                f.overCap || f.unsupported ? "border-amber-300" : "border-line"
              )}
            >
              {f.previewUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={f.previewUrl}
                  alt=""
                  className="size-11 shrink-0 rounded-lg border border-line object-cover"
                />
              ) : (
                <span className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-cream text-zinc-400">
                  {f.unsupported ? (
                    <FileWarning className="size-5 text-amber-500" aria-hidden />
                  ) : f.file.type.startsWith("image/") ? (
                    <ImageIcon className="size-5" aria-hidden />
                  ) : (
                    <FileText className="size-5" aria-hidden />
                  )}
                </span>
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[12.5px] font-bold text-ink-900">
                  {multiple && (
                    <span className="mr-1.5 font-mono text-[10.5px] text-violet-600">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                  )}
                  {f.file.name}
                </span>
                <span
                  className={cn(
                    "block text-[11px]",
                    f.overCap || f.unsupported
                      ? "font-semibold text-amber-700"
                      : "text-zinc-400"
                  )}
                >
                  {(f.file.size / (1024 * 1024)).toFixed(2)} MB
                  {f.overCap && " · over your plan's upload cap"}
                  {f.unsupported && " · type not analyzable in v1"}
                </span>
              </span>
              <button
                type="button"
                onClick={() => onRemove(f.id)}
                aria-label={`Remove ${f.file.name}`}
                className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-red-600"
              >
                <X className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
