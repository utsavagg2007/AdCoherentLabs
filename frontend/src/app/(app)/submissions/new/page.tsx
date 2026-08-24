import { redirect } from "next/navigation";

/**
 * The form-shaped workbench that used to live here is gone — starting a review
 * is a conversation now, and it happens on /dashboard.
 *
 * Kept as a redirect rather than deleted: this path is in bookmarks, in the
 * onboarding docs, and in the empty states of other pages. A 404 for something
 * that still exists under a different shape is a worse answer than a hop.
 */
export default function NewSubmissionRedirect() {
  redirect("/dashboard");
}
