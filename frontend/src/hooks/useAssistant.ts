import { useCallback, useRef, useState } from "react";
import { ApiError, recommendStream } from "@/lib/api";
import { normalize } from "@/lib/normalize";
import type {
  ClarificationOption,
  IntentOverrides,
  Preferences,
  RecommendRequest,
  RecommendResponse,
  StageEvent,
} from "@/lib/types";

export type Phase = "idle" | "running" | "done" | "error";

export type AssistantState = {
  phase: Phase;
  stages: StageEvent[];
  ranking: RecommendResponse | null; // deterministic results streamed before the explanation
  response: RecommendResponse | null;
  error: ApiError | null;
  recorded: { name: string; capturedAt: string } | null;
};

const INITIAL: AssistantState = { phase: "idle", stages: [], ranking: null, response: null, error: null, recorded: null };

export function useAssistant() {
  const [state, setState] = useState<AssistantState>(INITIAL);
  const lastRequest = useRef<RecommendRequest | null>(null);
  const abort = useRef<AbortController | null>(null);

  const run = useCallback(async (req: RecommendRequest) => {
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    lastRequest.current = req;
    setState({ ...INITIAL, phase: "running" });
    try {
      const response = await recommendStream(
        req,
        {
          onStage: (e) => setState((s) => ({ ...s, stages: [...s.stages.filter((x) => x.stage !== e.stage), e] })),
          onRanking: (r) => setState((s) => ({ ...s, ranking: r })),
        },
        ctrl.signal,
      );
      if (!ctrl.signal.aborted) setState((s) => ({ ...s, phase: "done", response }));
    } catch (err) {
      if (ctrl.signal.aborted) return;
      const e =
        err instanceof ApiError
          ? err
          : new ApiError("network_error", "Could not reach the server. Check your connection and retry.");
      setState((s) => ({ ...s, phase: "error", error: e }));
    }
  }, []);

  const ask = useCallback(
    (question: string, preferences: Preferences, overrides?: IntentOverrides | null) =>
      run({ question, preferences, overrides: overrides ?? null }),
    [run],
  );

  /** Re-run the previous question with a structured answer from the clarification form. */
  const answer = useCallback(
    (opt: ClarificationOption | { field: string; value: Record<string, unknown> }) => {
      const prev = lastRequest.current;
      if (!prev) return;
      const value = opt.value as Record<string, unknown>;
      const preferences: Preferences = { max_results: 3, ...prev.preferences };
      const overrides: IntentOverrides = { ...(prev.overrides ?? {}) };
      for (const [k, v] of Object.entries(value)) {
        if (k === "origin") preferences.origin = v as Preferences["origin"];
        else (overrides as Record<string, unknown>)[k] = v;
      }
      void run({ question: prev.question, preferences, overrides });
    },
    [run],
  );

  const retry = useCallback(() => {
    if (lastRequest.current) void run(lastRequest.current);
  }, [run]);

  const loadRecorded = useCallback(async (name: string) => {
    abort.current?.abort();
    setState({ ...INITIAL, phase: "running" });
    try {
      const resp = await fetch(`/recorded/${name}.json`);
      if (!resp.ok) throw new Error(String(resp.status));
      const response = normalize((await resp.json()) as RecommendResponse);
      setState({ ...INITIAL, phase: "done", response, recorded: { name, capturedAt: response.generated_at } });
    } catch {
      setState({ ...INITIAL, phase: "error", error: new ApiError("recorded_missing", "Recorded session not found.") });
    }
  }, []);

  const reset = useCallback(() => {
    abort.current?.abort();
    setState(INITIAL);
  }, []);

  return { state, ask, answer, retry, loadRecorded, reset };
}
