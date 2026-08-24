/**
 * Client-side claim spotting — ONLY to make the intake question concrete.
 *
 * This is a regex pass, not analysis. The real claim extraction is Layer 2 of
 * the engine (`claim_candidates` on the prepared asset), which runs server-side
 * after submission and is what the review actually reasons over. This exists so
 * the intake can ask "what backs the 3.9% APR?" instead of the useless generic
 * "do you have substantiation?", and so a reviewer can see we are asking about
 * something specific in their copy.
 *
 * It is deliberately allowed to miss things. It must never be presented as the
 * set of claims found in the ad — the wording in the intake says "spotted",
 * and the run reports the real set.
 *
 * Grouping is by SENTENCE, not by match. An early version quoted a window
 * around each match, which produced six overlapping near-duplicate quotes for
 * a three-sentence ad. You substantiate a sentence, not a regex hit — so
 * matches within one sentence collapse into one item that lists everything
 * that sentence needs.
 */

export type ClaimKind =
  | "rate"
  | "superlative"
  | "guarantee"
  | "money"
  | "speed"
  | "comparison";

export interface SpottedClaim {
  /** The sentence, trimmed and whitespace-collapsed. */
  text: string;
  /** Everything this sentence needs backing for, de-duplicated, in order. */
  asks: string[];
}

/**
 * Kept short and non-overlapping: several of these can appear on one sentence,
 * joined with semicolons, so any that read as full clauses would pile up.
 */
const ASK: Record<ClaimKind, string> = {
  rate: "the rate's source and the terms it assumes",
  superlative: "the data behind the ranking",
  guarantee: "the conditions and exclusions",
  money: "how the figure was calculated, and who actually achieves it",
  speed: "the typical timeline",
  comparison: "who it is measured against, and when",
};

const PATTERNS: { kind: ClaimKind; re: RegExp }[] = [
  {
    kind: "rate",
    re: /\b\d+(?:\.\d+)?\s*%\s*(?:apr|apy|interest|rate|back|off|cash\s*back)?\b/gi,
  },
  {
    kind: "money",
    re: /(?:save|earn|make|up\s+to|as\s+much\s+as|worth)\s+\$\s?\d[\d,]*(?:\.\d+)?[kmb]?\b/gi,
  },
  {
    kind: "superlative",
    re: /\b(?:#\s?1|no\.?\s?1|best|top[-\s]rated|fastest|cheapest|lowest|highest|leading|largest|most\s+trusted|only)\b/gi,
  },
  {
    kind: "guarantee",
    re: /\b(?:guarantee(?:d|s)?|risk[-\s]free|no\s+(?:fees?|hidden\s+(?:fees?|costs?|charges?)|catch|obligation)|zero\s+fees?|free\s+forever|100%\s+\w+)\b/gi,
  },
  {
    kind: "speed",
    re: /\b(?:instant(?:ly|aneous)?|same[-\s]day|overnight|in\s+(?:as\s+little\s+as\s+)?\d+\s*(?:seconds?|minutes?|hours?|days?)|within\s+\d+\s*(?:hours?|days?))\b/gi,
  },
  {
    kind: "comparison",
    re: /\b(?:\d+(?:\.\d+)?x\s+(?:faster|cheaper|better|more)|(?:faster|cheaper|better|more)\s+than\s+\w+|outperforms?|beats?\s+the\s+\w+)\b/gi,
  },
];

const MAX_CLAIMS = 4;
const MAX_SENTENCE = 180;

export function spotClaims(input: string): SpottedClaim[] {
  const text = stripTags(input);
  if (!text.trim()) return [];

  const sentences = splitSentences(text);
  if (sentences.length === 0) return [];

  // sentence index -> ordered, de-duplicated asks
  const hits = new Map<number, Set<ClaimKind>>();

  for (const { kind, re } of PATTERNS) {
    // Fresh lastIndex per call: these regexes are module-level and /g is
    // stateful, so reusing them across calls without this skips matches.
    re.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      if (m[0].length === 0) {
        re.lastIndex += 1; // a zero-width match would loop forever
        continue;
      }
      const i = sentences.findIndex(
        (s) => m!.index >= s.start && m!.index < s.end
      );
      if (i === -1) continue;
      const set = hits.get(i) ?? new Set<ClaimKind>();
      set.add(kind);
      hits.set(i, set);
    }
  }

  return [...hits.entries()]
    .sort((a, b) => a[0] - b[0])
    .slice(0, MAX_CLAIMS)
    .map(([i, kinds]) => ({
      text: clip(collapse(text.slice(sentences[i].start, sentences[i].end))),
      asks: [...kinds].map((k) => ASK[k]),
    }))
    .filter((c) => c.text.length > 0);
}

interface Span {
  start: number;
  end: number;
}

/**
 * Sentence boundaries by offset. Ad copy is not prose — it is full of line
 * breaks, em dashes and fragments — so a newline ends a sentence just as a
 * period does, and a bare fragment with no terminator still counts.
 */
function splitSentences(text: string): Span[] {
  const spans: Span[] = [];
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    const isBreak =
      ch === "\n" ||
      ((ch === "." || ch === "!" || ch === "?") &&
        // not a decimal point, and not mid-abbreviation
        !/\d/.test(text[i + 1] ?? "") &&
        /\s|$/.test(text[i + 1] ?? " "));
    if (!isBreak) continue;
    if (text.slice(start, i + 1).trim()) spans.push({ start, end: i + 1 });
    start = i + 1;
  }
  if (text.slice(start).trim()) spans.push({ start, end: text.length });
  return spans;
}

function clip(s: string): string {
  if (s.length <= MAX_SENTENCE) return s;
  const cut = s.lastIndexOf(" ", MAX_SENTENCE);
  return `${s.slice(0, cut > 0 ? cut : MAX_SENTENCE)}…`;
}

function stripTags(s: string): string {
  // Pasted HTML is common here; the tags are noise for this pass. The engine
  // sees the original markup either way. Block-level tags become breaks so a
  // markup-only "sentence" does not swallow the whole ad.
  return s
    .replace(/<\/(p|div|li|h[1-6]|br|section|tr)\s*>/gi, "\n")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<[^>]*>/g, " ");
}

function collapse(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}
