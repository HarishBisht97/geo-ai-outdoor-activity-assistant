import { normalize } from "./normalize";
import type { ErrorBody, RecommendRequest, RecommendResponse, StageEvent } from "./types";

export const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public requestId?: string,
    public status?: number,
  ) {
    super(message);
  }
}

async function errorFrom(resp: Response): Promise<ApiError> {
  try {
    const body = (await resp.json()) as { error?: ErrorBody };
    if (body.error) return new ApiError(body.error.code, body.error.message, body.error.request_id, resp.status);
  } catch {
    /* non-JSON error body */
  }
  return new ApiError("http_error", `The server answered with HTTP ${resp.status}.`, undefined, resp.status);
}

export type ReadyInfo = {
  ready: boolean;
  status: "ready" | "loading" | "degraded";
  slm_enabled: boolean;
  model?: { loaded?: boolean; base_model?: string; quantization?: string };
};

export async function getReady(signal?: AbortSignal): Promise<ReadyInfo> {
  const resp = await fetch(`${API_BASE}/ready`, { signal });
  if (resp.status !== 200 && resp.status !== 503) throw await errorFrom(resp);
  return (await resp.json()) as ReadyInfo;
}

export type StreamHandlers = {
  onStage?: (e: StageEvent) => void;
  onRanking?: (r: RecommendResponse) => void;
};

/** Parse a text/event-stream body into (event, data) pairs. */
export function parseSse(buffer: string): { events: { event: string; data: string }[]; rest: string } {
  const events: { event: string; data: string }[] = [];
  const blocks = buffer.split(/\r?\n\r?\n/);
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (data.length) events.push({ event, data: data.join("\n") });
  }
  return { events, rest };
}

/** POST /api/v1/recommend/stream (EventSource cannot POST, so the stream is read with fetch). */
export async function recommendStream(
  req: RecommendRequest,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<RecommendResponse> {
  const resp = await fetch(`${API_BASE}/api/v1/recommend/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(req),
    signal,
  });
  if (!resp.ok || !resp.body) throw await errorFrom(resp);
  const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    const { events, rest } = parseSse(buffer);
    buffer = rest;
    for (const { event, data } of events) {
      const payload = JSON.parse(data);
      if (event === "stage") handlers.onStage?.(payload as StageEvent);
      else if (event === "ranking") handlers.onRanking?.(normalize(payload as RecommendResponse));
      else if (event === "done") return normalize(payload as RecommendResponse);
      else if (event === "error") throw new ApiError(payload.code, payload.message, payload.request_id);
    }
  }
  throw new ApiError("stream_closed", "The connection closed before the answer was complete. Please retry.");
}
