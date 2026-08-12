/** One typed client for the FastAPI backend.
 *
 * - `Authorization: Bearer <supabase access token>` for user sessions
 * - `X-Org-Id` on every request once an organization is selected
 * - optional `X-API-Key` mode (keys are never persisted by this client)
 * - errors normalized to the backend's `{error:{code,message,request_id,details}}`
 * - submissions carry a caller-provided Idempotency-Key that is NEVER rotated
 *   silently — the same pending submission always replays the same key.
 */

import type {
  ApiKeyCreated,
  ApiKeyRow,
  CreditBalance,
  FindingRow,
  FindingStatus,
  InlineKind,
  LedgerEntry,
  MemberRow,
  OrgMe,
  PublicPlansResponse,
  ReportResponse,
  Role,
  RunEffort,
  RunEventsResponse,
  RunResponse,
  RunRow,
  SubmissionAccepted,
  SubmissionDetail,
  SubmissionRow,
} from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8080";

// ---------------------------------------------------------------- errors

export interface ApiErrorShape {
  code: string;
  message: string;
  request_id?: string;
  details?: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: Record<string, unknown>;
  readonly retryAfterSeconds: number | null;

  constructor(
    status: number,
    shape: ApiErrorShape,
    retryAfterSeconds: number | null = null
  ) {
    super(shape.message);
    this.name = "ApiError";
    this.status = status;
    this.code = shape.code;
    this.requestId = shape.request_id ?? null;
    this.details = shape.details ?? {};
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

/** Human-readable framing for the states the product must handle well. */
export function describeError(e: unknown): { title: string; detail: string } {
  if (!isApiError(e)) {
    return {
      title: "Something went wrong",
      detail: e instanceof Error ? e.message : "Unexpected error.",
    };
  }
  switch (e.status) {
    case 0:
      return {
        title: "Can't reach the review service",
        detail:
          "The API is not responding. Check that the backend is running, then try again.",
      };
    case 401:
      return {
        title: "Session expired",
        detail: "Sign in again to continue.",
      };
    case 402: {
      const needed = e.details["needed"];
      const balance = e.details["balance"];
      return {
        title: "Not enough credits",
        detail:
          typeof needed === "number" && typeof balance === "number"
            ? `This review costs ${needed} credits and your balance is ${balance}. Add a credit pack or upgrade your plan to continue.`
            : "Your credit balance can't cover this review. Add credits or upgrade your plan.",
      };
    }
    case 403:
      if (e.code === "step_up_required") {
        return {
          title: "Extra verification needed",
          detail:
            "Your account has multi-factor authentication enabled, and this action requires a recent MFA challenge. Sign in again with your second factor, then retry.",
        };
      }
      if (e.code === "billing_hold") {
        return {
          title: "Billing needs attention",
          detail:
            "Payment is past due, so new reviews are paused. Resolve billing to continue — your data is untouched.",
        };
      }
      return { title: "Not allowed", detail: e.message };
    case 404:
      return {
        title: "Not found",
        detail: "This resource doesn't exist or you don't have access to it.",
      };
    case 409:
      return { title: "Not ready yet", detail: e.message };
    case 413:
      return {
        title: "File too large",
        detail:
          "This file is over your plan's upload limit. Compress the creative or upgrade for a higher cap.",
      };
    case 415:
      return {
        title: "Unsupported file type",
        detail:
          "v1 analyzes PNG, JPEG, WebP, GIF, TXT and HTML. PDF and video are not analyzable yet.",
      };
    case 422:
      return { title: "Submission rejected", detail: e.message };
    case 429:
      return {
        title: "Rate limit reached",
        detail: e.retryAfterSeconds
          ? `Too many requests. Try again in about ${e.retryAfterSeconds}s.`
          : "Too many requests. Give it a moment and try again.",
      };
    case 503:
      return {
        title: "Service temporarily unavailable",
        detail:
          e.code === "scanner_unavailable"
            ? "Upload scanning is temporarily unavailable. Your file was not stored or charged — try again shortly."
            : "The service is briefly unavailable. Try again shortly.",
      };
    default:
      return { title: "Request failed", detail: e.message };
  }
}

// ---------------------------------------------------------------- client

interface ClientOptions {
  getToken: () => Promise<string | null>;
  getOrgId: () => string | null;
}

interface RequestOptions {
  method?: string;
  body?: BodyInit;
  json?: unknown;
  idempotencyKey?: string;
  /** omit the X-Org-Id header (e.g. first-org creation) */
  noOrg?: boolean;
  signal?: AbortSignal;
}

async function parseError(res: Response): Promise<ApiError> {
  let shape: ApiErrorShape = {
    code: "error",
    message: `Request failed with status ${res.status}.`,
  };
  try {
    const body = (await res.json()) as { error?: ApiErrorShape };
    if (body && typeof body === "object" && body.error?.message) {
      shape = body.error;
    }
  } catch {
    /* non-JSON error body — keep the generic shape */
  }
  const retryAfter = res.headers.get("Retry-After");
  const retrySeconds = retryAfter ? parseInt(retryAfter, 10) || null : null;
  return new ApiError(res.status, shape, retrySeconds);
}

export class ApiClient {
  constructor(private readonly opts: ClientOptions) {}

  private async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const headers = new Headers();
    const token = await this.opts.getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const orgId = this.opts.getOrgId();
    if (orgId && !options.noOrg) headers.set("X-Org-Id", orgId);
    if (options.idempotencyKey)
      headers.set("Idempotency-Key", options.idempotencyKey);

    let body = options.body;
    if (options.json !== undefined) {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(options.json);
    }

    let res: Response;
    try {
      res = await fetch(`${API_URL}${path}`, {
        method: options.method ?? "GET",
        headers,
        body,
        signal: options.signal,
      });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") throw e;
      throw new ApiError(0, {
        code: "network",
        message: "The API could not be reached.",
      });
    }
    if (!res.ok) throw await parseError(res);
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  // -- orgs -----------------------------------------------------------------

  orgMe(signal?: AbortSignal) {
    return this.request<OrgMe>("/v1/orgs/me", { signal });
  }

  createOrg(name: string) {
    return this.request<{ org_id: string; name: string; tier: string }>(
      "/v1/orgs",
      { method: "POST", json: { name }, noOrg: true }
    );
  }

  listMembers(signal?: AbortSignal) {
    return this.request<{ members: MemberRow[]; seats: number | null }>(
      "/v1/orgs/members",
      { signal }
    );
  }

  addMember(email: string, role: Exclude<Role, "owner">) {
    return this.request<{ user_id: string; role: Role }>("/v1/orgs/members", {
      method: "POST",
      json: { email, role },
    });
  }

  changeMemberRole(userId: string, role: Exclude<Role, "owner">) {
    return this.request<{ user_id: string; role: Role }>("/v1/orgs/members", {
      method: "PATCH",
      json: { user_id: userId, role },
    });
  }

  removeMember(userId: string) {
    return this.request<{ removed: string }>(
      `/v1/orgs/members/${encodeURIComponent(userId)}`,
      { method: "DELETE" }
    );
  }

  // -- credits --------------------------------------------------------------

  credits(signal?: AbortSignal) {
    return this.request<CreditBalance>("/v1/credits", { signal });
  }

  creditLedger(beforeId?: number | null, limit = 50, signal?: AbortSignal) {
    const q = new URLSearchParams();
    if (beforeId) q.set("before_id", String(beforeId));
    q.set("limit", String(limit));
    return this.request<{ ledger: LedgerEntry[]; next_before_id: number | null }>(
      `/v1/credits/ledger?${q}`,
      { signal }
    );
  }

  packCheckout(pack: "starter" | "growth" | "scale") {
    return this.request<{ checkout_url: string }>("/v1/credits/checkout", {
      method: "POST",
      json: { pack },
    });
  }

  // -- billing --------------------------------------------------------------

  /** PUBLIC pricing + entitlements document (plan_pricing et al). */
  plans(signal?: AbortSignal) {
    return this.request<PublicPlansResponse>("/v1/plans", { signal });
  }

  subscriptionCheckout(tier: "hobby" | "pro" | "design" | "enterprise") {
    // interval intentionally omitted — the backend defaults to monthly and
    // annual pricing is not implemented; we never send users down that path.
    return this.request<{ checkout_url: string }>("/v1/billing/checkout", {
      method: "POST",
      json: { tier },
    });
  }

  billingPortal() {
    return this.request<{ portal_url: string }>("/v1/billing/portal", {
      method: "POST",
    });
  }

  // -- submissions ----------------------------------------------------------

  listSubmissions(before?: string | null, limit = 50, signal?: AbortSignal) {
    const q = new URLSearchParams({ limit: String(limit) });
    if (before) q.set("before", before);
    return this.request<{ submissions: SubmissionRow[]; next_before: string | null }>(
      `/v1/submissions?${q}`,
      { signal }
    );
  }

  getSubmission(id: string, signal?: AbortSignal) {
    return this.request<SubmissionDetail>(
      `/v1/submissions/${encodeURIComponent(id)}`,
      { signal }
    );
  }

  submitInline(
    payload: {
      kind: InlineKind;
      content: string;
      title?: string;
      target_jurisdictions: string[];
    },
    idempotencyKey: string
  ) {
    const json: Record<string, unknown> = {
      kind: payload.kind,
      content: payload.content,
      target_jurisdictions: payload.target_jurisdictions,
    };
    if (payload.title) json.title = payload.title;
    return this.request<SubmissionAccepted>("/v1/submissions", {
      method: "POST",
      json,
      idempotencyKey,
    });
  }

  submitFiles(
    payload: { files: File[]; title?: string; target_jurisdictions: string[] },
    idempotencyKey: string
  ) {
    const form = new FormData();
    if (payload.files.length === 1) {
      form.append("file", payload.files[0]);
    } else {
      for (const f of payload.files) form.append("files", f);
    }
    if (payload.title) form.append("title", payload.title);
    if (payload.target_jurisdictions.length)
      form.append("target_jurisdictions", payload.target_jurisdictions.join(","));
    return this.request<SubmissionAccepted>("/v1/submissions", {
      method: "POST",
      body: form,
      idempotencyKey,
    });
  }

  // -- runs -----------------------------------------------------------------

  listRuns(
    opts: { status?: string | null; before?: string | null; limit?: number } = {},
    signal?: AbortSignal
  ) {
    const q = new URLSearchParams({ limit: String(opts.limit ?? 50) });
    if (opts.status) q.set("status", opts.status);
    if (opts.before) q.set("before", opts.before);
    return this.request<{ runs: RunRow[]; next_before: string | null }>(
      `/v1/runs?${q}`,
      { signal }
    );
  }

  getRun(id: string, signal?: AbortSignal) {
    return this.request<RunResponse>(`/v1/runs/${encodeURIComponent(id)}`, {
      signal,
    });
  }

  getReport(id: string, signal?: AbortSignal) {
    return this.request<ReportResponse>(
      `/v1/runs/${encodeURIComponent(id)}/report`,
      { signal }
    );
  }

  /** Sanitized live-activity feed — poll with the last id you have. */
  runEvents(id: string, afterId: number, signal?: AbortSignal) {
    return this.request<RunEventsResponse>(
      `/v1/runs/${encodeURIComponent(id)}/events?after_id=${afterId}`,
      { signal }
    );
  }

  resumeRun(id: string, guidance: string) {
    return this.request<{
      run_id: string;
      resumed_from_run_id: string;
      /** Escrowed for the extra review round; unused credits come back. */
      credits_reserved: number;
      credits_floor: number;
      /** @deprecated (0012) equals credits_reserved. */
      credits_charged: number;
    }>(`/v1/runs/${encodeURIComponent(id)}/resume`, {
      method: "POST",
      json: { guidance },
    });
  }

  /** Line items behind a run's metered charge (0012). */
  runEffort(id: string, signal?: AbortSignal) {
    return this.request<RunEffort>(
      `/v1/runs/${encodeURIComponent(id)}/effort`,
      { signal }
    );
  }

  // -- findings -------------------------------------------------------------

  listFindings(
    opts: {
      run_id?: string;
      submission_id?: string;
      status?: FindingStatus | null;
      limit?: number;
    } = {},
    signal?: AbortSignal
  ) {
    const q = new URLSearchParams({ limit: String(opts.limit ?? 100) });
    if (opts.run_id) q.set("run_id", opts.run_id);
    if (opts.submission_id) q.set("submission_id", opts.submission_id);
    if (opts.status) q.set("status", opts.status);
    return this.request<{ findings: FindingRow[] }>(`/v1/findings?${q}`, {
      signal,
    });
  }

  reviewFinding(id: string, status: Exclude<FindingStatus, "open">) {
    return this.request<{ finding: { id: string; status: FindingStatus } }>(
      `/v1/findings/${encodeURIComponent(id)}`,
      { method: "PATCH", json: { status } }
    );
  }

  // -- api keys -------------------------------------------------------------

  listApiKeys(signal?: AbortSignal) {
    return this.request<{ api_keys: ApiKeyRow[] }>("/v1/api-keys", { signal });
  }

  createApiKey(payload: {
    name: string;
    scopes: string[];
    rate_limit_rpm?: number | null;
  }) {
    const json: Record<string, unknown> = {
      name: payload.name,
      scopes: payload.scopes,
    };
    if (payload.rate_limit_rpm) json.rate_limit_rpm = payload.rate_limit_rpm;
    return this.request<ApiKeyCreated>("/v1/api-keys", {
      method: "POST",
      json,
    });
  }

  revokeApiKey(id: string) {
    return this.request<{ revoked: string }>(
      `/v1/api-keys/${encodeURIComponent(id)}`,
      { method: "DELETE" }
    );
  }
}
