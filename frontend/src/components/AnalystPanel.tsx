"use client";

import { useActionState, useRef } from "react";
import { askAnalyst, type AskState } from "@/app/actions";
import type { VerifiedItem } from "@/lib/api";

const TYPE_STYLE: Record<VerifiedItem["type"], { label: string; cls: string }> = {
  fact: { label: "Fact", cls: "border-pos/50 text-pos" },
  estimate: { label: "Estimate", cls: "border-warn/50 text-warn" },
  interpretation: { label: "AI interpretation", cls: "border-info/50 text-info" },
};

const EXAMPLES = [
  "Which products generate the most revenue?",
  "What changed in my business this week?",
  "Which products are losing momentum?",
  "Where am I losing money?",
  "What should I investigate tomorrow?",
];

export function AnalystPanel({ configured, model }: { configured: boolean; model: string }) {
  const [state, action, pending] = useActionState<AskState, FormData>(askAnalyst, {
    question: "",
    answer: null,
    error: null,
  });
  const input = useRef<HTMLTextAreaElement>(null);

  if (!configured) {
    return (
      <div className="text-[12px] text-dim">
        <p>
          The AI analyst needs a Claude API key. Add <code className="num text-text">ANTHROPIC_API_KEY=…</code> to{" "}
          <code className="num text-text">backend/.env</code> and restart ATLAS. Keys come from console.anthropic.com
          (separate from a Claude subscription). Never paste the key into a chat.
        </p>
        <p className="mt-2 text-faint">Reports below work without it; only the AI interpretation is skipped.</p>
      </div>
    );
  }

  const a = state.answer;
  return (
    <div>
      <form action={action} className="flex flex-col gap-2">
        <textarea
          ref={input}
          name="question"
          defaultValue={state.question}
          rows={2}
          maxLength={2000}
          placeholder="Ask about your store, e.g. Which products should I investigate further?"
          aria-label="Question for the AI analyst"
          className="w-full resize-y rounded-sm border border-border-strong bg-panel-2 px-2.5 py-2 text-[13px] placeholder:text-faint"
        />
        <div className="flex flex-wrap items-center gap-1.5">
          {EXAMPLES.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => {
                if (input.current) input.current.value = q;
              }}
              className="rounded-sm border border-border px-2 py-[2px] text-[11px] text-dim hover:border-border-strong hover:text-text"
            >
              {q}
            </button>
          ))}
          <button
            type="submit"
            disabled={pending}
            className="ml-auto rounded-sm border border-accent px-3 py-1 text-[12px] text-accent hover:bg-accent-dim disabled:opacity-50"
          >
            {pending ? "Analyzing…" : "Ask"}
          </button>
        </div>
      </form>

      {state.error && <div className="mt-3 rounded-sm border border-neg/40 bg-neg/5 px-3 py-2 text-[12px] text-neg">{state.error}</div>}

      {a && (
        <div className="mt-4 space-y-3" aria-live="polite">
          <div className="rounded-sm border border-border bg-panel-2 px-3 py-2">
            <div className="text-[11px] uppercase tracking-wider text-faint">Answer · AI summary</div>
            <div className="mt-1 text-[13px]">{a.summary}</div>
            {a.insufficient_data && (
              <div className="mt-1.5 text-[12px] text-warn">⚠ The available data can&apos;t fully answer this question.</div>
            )}
          </div>
          <ul className="space-y-2">
            {a.items.map((it, i) => {
              const t = TYPE_STYLE[it.type];
              return (
                <li key={i} className="rounded-sm border border-border px-3 py-2">
                  <div className="mb-1 flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-wider">
                    <span className={`rounded-sm border px-1.5 py-[1px] ${t.cls}`}>{t.label}</span>
                    {it.verified ? (
                      <span className="text-pos">✓ {it.type === "fact" ? "verified against data" : "citations valid"}</span>
                    ) : (
                      <span className="text-neg">⚠ unverified</span>
                    )}
                  </div>
                  <div className="text-[13px]">{it.text}</div>
                  {!it.verified && <div className="mt-1 text-[11px] text-neg">{it.issues.join(" ")}</div>}
                  {it.citations.length > 0 && (
                    <details className="mt-1 text-[11px] text-faint">
                      <summary className="cursor-pointer hover:text-dim">Sources ({it.citations.length})</summary>
                      <ul className="num mt-1 space-y-0.5">
                        {it.citations.map((c) => (
                          <li key={c}>
                            {c} ={" "}
                            <span className="text-dim">
                              {c in it.cited_values ? JSON.stringify(it.cited_values[c]) : "— not in data"}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </li>
              );
            })}
          </ul>
          <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-faint">
            <span>
              {a.verification.verified} verified · {a.verification.unverified} unverified · model {a.model ?? model} · data
              as of {a.data_as_of ? new Date(a.data_as_of).toLocaleString() : "—"}
            </span>
            <span>{a.disclaimer}</span>
          </div>
          {a.follow_up_questions.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {a.follow_up_questions.map((q) => (
                <button key={q} type="button"
                  onClick={() => { if (input.current) { input.current.value = q; input.current.focus(); } }}
                  className="rounded-sm border border-border px-2 py-[2px] text-[11px] text-dim hover:text-text">
                  {q}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
