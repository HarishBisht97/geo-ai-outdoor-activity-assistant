import type { RecommendResponse } from "./types";

const empty = <T>(v: T[] | undefined | null): T[] => v ?? [];

/** OpenAPI marks defaulted arrays optional; the live response always includes them. */
export function normalize(r: RecommendResponse): RecommendResponse {
  return {
    ...r,
    recommendations: empty(r.recommendations),
    candidates_considered: empty(r.candidates_considered),
    facts: empty(r.facts),
    warnings: empty(r.warnings),
    data_quality: empty(r.data_quality),
    sources: empty(r.sources),
    attribution: empty(r.attribution),
    clarification: r.clarification
      ? { ...r.clarification, options: empty(r.clarification.options), missing_fields: empty(r.clarification.missing_fields), questions: empty(r.clarification.questions) }
      : r.clarification,
    interpretation: r.interpretation
      ? {
          ...r.interpretation,
          assumptions: empty(r.interpretation.assumptions),
          sensitivities: empty(r.interpretation.sensitivities),
          preferences: empty(r.interpretation.preferences),
        }
      : r.interpretation,
    narrative: r.narrative
      ? {
          ...r.narrative,
          why: empty(r.narrative.why),
          carry: empty(r.narrative.carry),
          watch_for: empty(r.narrative.watch_for),
          postpone_if: empty(r.narrative.postpone_if),
          caveats: empty(r.narrative.caveats),
          notes: empty(r.narrative.notes),
        }
      : r.narrative,
  };
}
