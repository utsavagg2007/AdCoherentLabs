import { notFound } from "next/navigation";
import { requireContext, getRunDetail } from "@/lib/data";
import { RunViewer } from "./run-viewer";

export const metadata = { title: "Analysis run" };

export default async function RunPage(props: PageProps<"/runs/[id]">) {
  const { id } = await props.params;
  const ctx = await requireContext();
  const detail = await getRunDetail(id);
  if (!detail || detail.run.org_id !== ctx.org.id) notFound();

  const canReview = ["owner", "admin", "reviewer"].includes(ctx.role);

  return (
    <RunViewer
      initial={detail}
      demo={ctx.demo}
      canReview={canReview}
    />
  );
}
