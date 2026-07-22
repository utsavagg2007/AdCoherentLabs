"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Clapperboard,
  FileText,
  FileWarning,
  ImageIcon,
  Lock,
  UploadCloud,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

/** Media kinds mirror the backend's upload pipeline. Which of them THIS org
 * may submit comes from plan entitlements (allowed_kinds +
 * max_video_seconds) — the client only guides; the backend enforces. */

export type MediaKind = "image" | "text" | "html" | "pdf" | "docx" | "video";

export interface PickedFile {
  file: File;
  id: string;
  kind: MediaKind | null;      // null = not a type the platform accepts at all
  previewUrl: string | null;   // object URL for images
  overCap: boolean;
  planLocked: boolean;         // accepted by the platform, not by this plan
  durationSeconds: number | null; // videos, once metadata resolves
  tooLong: boolean;            // video over the plan's length cap
}

const KIND_BY_MIME: Record<string, MediaKind> = {
  "image/png": "image",
  "image/jpeg": "image",
  "image/webp": "image",
  "image/gif": "image",
  "text/plain": "text",
  "text/html": "html",
  "application/pdf": "pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
    "docx",
  "video/mp4": "video",
  "video/quicktime": "video",
  "video/webm": "video",
};

const KIND_BY_EXT: [RegExp, MediaKind][] = [
  [/\.(png|jpe?g|webp|gif)$/i, "image"],
  [/\.txt$/i, "text"],
  [/\.html?$/i, "html"],
  [/\.pdf$/i, "pdf"],
  [/\.docx$/i, "docx"],
  [/\.(mp4|mov|webm)$/i, "video"],
];

export const KIND_LABEL: Record<MediaKind, string> = {
  image: "Image",
  text: "Text file",
  html: "HTML file",
  pdf: "PDF",
  docx: "Word document",
  video: "Video",
};

export function kindForFile(file: File): MediaKind | null {
  if (file.type && KIND_BY_MIME[file.type]) return KIND_BY_MIME[file.type];
  for (const [rx, kind] of KIND_BY_EXT) if (rx.test(file.name)) return kind;
  return null;
}

/** Resolve a video's duration from its metadata (no decode, no upload). */
export function probeVideoDuration(file: File): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const v = document.createElement("video");
    v.preload = "metadata";
    const done = (val: number | null) => {
      URL.revokeObjectURL(url);
      resolve(val);
    };
    v.onloadedmetadata = () =>
      done(Number.isFinite(v.duration) ? v.duration : null);
    v.onerror = () => done(null);
    v.src = url;
  });
}

export function buildPicked(
  file: File,
  capMb: number | null,
  allowedKinds?: string[] | null
): PickedFile {
  const kind = kindForFile(file);
  return {
    file,
    id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`,
    kind,
    previewUrl: kind === "image" ? URL.createObjectURL(file) : null,
    overCap: capMb !== null ? file.size > capMb * 1024 * 1024 : false,
    planLocked:
      kind !== null && Array.isArray(allowedKinds)
        ? !allowedKinds.includes(kind)
        : false,
    durationSeconds: null,
    tooLong: false,
  };
}

function formatsLine(allowedKinds: string[] | null | undefined): string {
  const k = new Set(allowedKinds ?? ["image", "text", "html"]);
  const parts: string[] = [];
  if (k.has("image")) parts.push("PNG, JPEG, WebP, GIF");
  if (k.has("pdf")) parts.push("PDF");
  if (k.has("docx")) parts.push("DOCX");
  if (k.has("video")) parts.push("MP4, MOV, WebM");
  if (k.has("text")) parts.push("TXT");
  if (k.has("html")) parts.push("HTML");
  return parts.join(" · ");
}

export function Dropzone({
  files,
  onAdd,
  onRemove,
  multiple,
  maxFiles,
  capMb,
  imagesOnly,
  allowedKinds,
  maxVideoSeconds,
}: {
  files: PickedFile[];
  onAdd: (files: File[]) => void;
  onRemove: (id: string) => void;
  multiple: boolean;
  maxFiles: number;
  capMb: number | null;
  imagesOnly?: boolean;
  allowedKinds?: string[] | null;
  maxVideoSeconds?: number | null;
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

  const kinds = new Set(allowedKinds ?? ["image", "text", "html"]);
  const accept = imagesOnly
    ? "image/png,image/jpeg,image/webp,image/gif"
    : [
        "image/png,image/jpeg,image/webp,image/gif",
        "text/plain,text/html,.txt,.html,.htm",
        kinds.has("pdf") ? "application/pdf,.pdf" : "",
        kinds.has("docx")
          ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx"
          : "",
        kinds.has("video") ? "video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm" : "",
      ]
        .filter(Boolean)
        .join(",");

  const handleFiles = useCallback(
    (list: FileList | File[]) => {
      const incoming = Array.from(list);
      if (!incoming.length) return;
      onAdd(incoming);
    },
    [onAdd]
  );

  const atCapacity = files.length >= maxFiles;
  const videoAllowed = !imagesOnly && kinds.has("video");

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
          "flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors duration-200",
          dragging
            ? "border-white/40 bg-white/6"
            : "border-white/15 bg-coal-850 hover:border-white/25 hover:bg-white/5",
          atCapacity && "cursor-not-allowed opacity-60"
        )}
      >
        <UploadCloud
          className={cn("size-8", dragging ? "text-ink-700" : "text-ink-500")}
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
        <p className="mt-1 text-[12px] leading-relaxed text-ink-500">
          {imagesOnly ? "PNG, JPEG, WebP, GIF" : formatsLine(allowedKinds)}
          {capMb ? ` · up to ${capMb} MB on your plan` : ""}
        </p>
        {!imagesOnly && (
          <p className="mt-0.5 text-[11.5px] text-ink-500">
            {videoAllowed
              ? maxVideoSeconds != null
                ? `Video up to ${maxVideoSeconds}s on your plan — analysed frame by frame.`
                : "Full-length video on your plan — analysed frame by frame."
              : "Video review unlocks on the Hobby plan and above."}
          </p>
        )}
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
          {files.map((f, i) => {
            const problem =
              f.kind === null || f.planLocked || f.overCap || f.tooLong;
            return (
              <li
                key={f.id}
                className={cn(
                  "flex items-center gap-3 rounded-xl border bg-coal-800 p-2.5",
                  problem ? "border-amber-400/30" : "border-line"
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
                  <span className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-coal-700 text-ink-500">
                    {f.kind === null ? (
                      <FileWarning className="size-5 text-amber-400" aria-hidden />
                    ) : f.planLocked ? (
                      <Lock className="size-5 text-amber-400" aria-hidden />
                    ) : f.kind === "video" ? (
                      <Clapperboard className="size-5" aria-hidden />
                    ) : f.kind === "image" ? (
                      <ImageIcon className="size-5" aria-hidden />
                    ) : (
                      <FileText className="size-5" aria-hidden />
                    )}
                  </span>
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[12.5px] font-bold text-ink-900">
                    {multiple && (
                      <span className="mr-1.5 font-mono text-[10.5px] text-ink-600">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                    )}
                    {f.file.name}
                  </span>
                  <span
                    className={cn(
                      "block text-[11px]",
                      problem ? "font-semibold text-amber-300" : "text-ink-500"
                    )}
                  >
                    {(f.file.size / (1024 * 1024)).toFixed(2)} MB
                    {f.kind === "video" && f.durationSeconds != null &&
                      ` · ${Math.round(f.durationSeconds)}s`}
                    {f.overCap && " · over your plan's upload cap"}
                    {f.kind === null && " · type not supported"}
                    {f.planLocked &&
                      ` · ${KIND_LABEL[f.kind!].toLowerCase()} uploads need a higher plan`}
                    {f.tooLong && " · over your plan's video length cap"}
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => onRemove(f.id)}
                  aria-label={`Remove ${f.file.name}`}
                  className="cursor-pointer rounded-md p-1.5 text-ink-500 hover:bg-white/8 hover:text-red-300"
                >
                  <X className="size-4" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
