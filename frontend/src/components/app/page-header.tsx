export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line px-5 py-6 sm:px-8">
      <div>
        <h1 className="text-[22px] font-extrabold tracking-tight text-ink-900">
          {title}
        </h1>
        {description && (
          <p className="mt-1 max-w-xl text-[13.5px] leading-relaxed text-ink-500">
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2.5">{actions}</div>}
    </div>
  );
}

export function PageBody({ children }: { children: React.ReactNode }) {
  return <div className="px-5 py-6 sm:px-8">{children}</div>;
}
