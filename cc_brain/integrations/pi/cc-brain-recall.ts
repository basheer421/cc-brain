// cc-brain auto-recall: before each agent run, recall facts related to the user's prompt and inject the
// new ones as a context message. Closes the "agent forgot to call recall" gap (Hermes-style push memory).
// No LLM call: `cc-brain recall --json` is BM25 + local embeddings, ~0.3-0.9 s. Fails silent.
// Log: ~/.cc-brain/logs/auto-recall.jsonl (one line per decision) for the usage watch.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { appendFile } from "node:fs/promises";
import { homedir } from "node:os";
import { basename, join } from "node:path";

// `cc-brain init` installs to ~/.local/bin; Pi may be started without it on PATH.
const BIN =
  process.env.CC_BRAIN_BIN ||
  [join(homedir(), ".local", "bin", "cc-brain")].find((p) => existsSync(p)) ||
  "cc-brain";
const LOG = join(homedir(), ".cc-brain", "logs", "auto-recall.jsonl");
const TIMEOUT_MS = 4000;
const FIRST_N = 5; // first prompt of a session
const LATER_N = 3; // later prompts: only facts not injected yet
const MAX_FACT_CHARS = 320;

// English stopwords + conversational filler. A prompt needs real content words to trigger recall,
// because recall scores can't separate chit-chat from real queries (measured: "explain it again please" = 34,
// "fix the crowdsec bouncer on k3s" = 32).
const STOP = new Set(
  (
    "the a an and or but if then so to of in on at for from by with without into onto about over under " +
    "is are was were be been being am do does did done doing have has had having will would can could should " +
    "shall may might must it its it's this that these those there here what which who whom whose when where why how " +
    "i me my mine we us our you your yours he she they them their his her not no yes yeah yep ok okay sure " +
    "please thanks thank cool nice great good fine right well also just now still again more less very really " +
    "lets let's let go going gonna want wanna need make made get got give take see look looks think know " +
    "explain tell show say said check continue proceed ahead keep start stop try use using work works working " +
    "thing things stuff something anything everything way all any some each every other another same new old " +
    "one two first last next back out up down off too than like basically actually maybe guess sounds hmm"
  ).split(/\s+/),
);

type Fact = { id: string; kind: string; project: string; text: string; date: string; score: string };

function contentTokens(text: string): string[] {
  const words = text.toLowerCase().match(/[a-z0-9][a-z0-9_.\-]{2,}/g) || [];
  return [...new Set(words.filter((w) => !STOP.has(w) && !/^\d+$/.test(w)))];
}

function sharesToken(fact: string, tokens: string[]): boolean {
  const f = fact.toLowerCase();
  // 5-char prefix = cheap stemming ("deploying" ~ "deployment")
  return tokens.some((t) => f.includes(t.length > 5 ? t.slice(0, 5) : t));
}

function projectSlug(cwd: string): string | undefined {
  if (!cwd || cwd === homedir()) return undefined;
  return basename(cwd).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || undefined;
}

function recall(query: string, project?: string): Promise<Fact[]> {
  const args = ["recall", query, "-n", "10", "--json"];
  if (project) args.push("-p", project);
  return new Promise((resolve) => {
    execFile(BIN, args, { timeout: TIMEOUT_MS, maxBuffer: 1 << 20 }, (err, stdout) => {
      if (err) return resolve([]);
      try {
        resolve(JSON.parse(stdout));
      } catch {
        resolve([]);
      }
    });
  });
}

function log(entry: Record<string, unknown>) {
  appendFile(LOG, JSON.stringify({ ts: new Date().toISOString(), ...entry }) + "\n").catch(() => {});
}

export default function (pi: ExtensionAPI) {
  if (process.env.CC_BRAIN_AUTO_RECALL === "0") return;

  // Per-session state; rebuilt from the transcript on resume so facts aren't injected twice.
  let sessionId: string | undefined;
  let injected = new Set<string>();
  let prompts = 0;

  pi.on("before_agent_start", async (event, ctx) => {
    const sid = ctx.sessionManager.getSessionId();
    if (sid !== sessionId) {
      sessionId = sid;
      injected = new Set();
      prompts = 0;
      for (const e of ctx.sessionManager.getEntries() as any[]) {
        if (e.type === "custom_message" && e.customType === "cc-brain-recall") {
          for (const id of e.details?.ids ?? []) injected.add(String(id));
          prompts++;
        }
      }
    }

    const prompt = (event.prompt || "").trim();
    // Slash commands and harness notifications (<background-task-notification>, ...) aren't user questions.
    if (!prompt || prompt.startsWith("/") || prompt.startsWith("<")) return;

    const first = prompts === 0;
    const tokens = contentTokens(prompt);
    if (tokens.length < (first ? 1 : 2)) {
      log({ session: sid, action: "skip", reason: "few-content-words", tokens: tokens.length });
      return;
    }

    const project = projectSlug(ctx.cwd);
    const t0 = Date.now();
    const facts = await recall(prompt.slice(0, 600), project);
    const ms = Date.now() - t0;

    const picked = facts
      .filter((f) => !injected.has(String(f.id)) && sharesToken(f.text, tokens))
      .slice(0, first ? FIRST_N : LATER_N);
    prompts++;
    if (!picked.length) {
      log({ session: sid, action: "none", ms, candidates: facts.length, project });
      return;
    }
    for (const f of picked) injected.add(String(f.id));

    const lines = picked.map((f) => {
      const t = f.text.replace(/\s+/g, " ");
      return `- #${f.id} [${f.kind}/${f.project} ${f.date}] ${t.length > MAX_FACT_CHARS ? t.slice(0, MAX_FACT_CHARS) + "…" : t}`;
    });
    log({ session: sid, action: "inject", ms, project, ids: picked.map((f) => f.id), first });

    return {
      message: {
        customType: "cc-brain-recall",
        display: true,
        content:
          "[cc-brain auto-recall: facts from long-term memory that may relate to this prompt. They can be stale; " +
          "repo and tool output win. Call `recall` for more, `correct(id)` if one is wrong.]\n" +
          lines.join("\n"),
        details: { ids: picked.map((f) => f.id), project, ms },
      },
    };
  });
}
