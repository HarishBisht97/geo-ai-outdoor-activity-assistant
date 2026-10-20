import type { components } from "@/types/api";

type S = components["schemas"];

export type RecommendRequest = S["RecommendRequest"];
export type RecommendResponse = S["RecommendResponse"];
export type Recommendation = S["Recommendation"];
export type SlotResult = S["SlotResult"];
export type SlotConditions = S["SlotConditions"];
export type EvidenceValue = S["EvidenceValue"];
export type Provenance = S["Provenance"];
export type WarningItem = S["WarningItem"];
export type Clarification = S["Clarification"];
export type ClarificationOption = S["ClarificationOption"];
export type CandidateSummary = S["CandidateSummary"];
export type Timeline = S["Timeline"];
export type HourlySeries = S["HourlySeries"];
export type SunTimes = S["SunTimes"];
export type Narrative = S["Narrative"];
export type NarrativeItem = S["NarrativeItem"];
export type Fact = S["Fact"];
export type ScoreComponent = S["ScoreComponent"];
export type Preferences = S["Preferences"];
export type IntentOverrides = S["IntentOverrides"];
export type ErrorBody = S["ErrorBody"];
export type DataKind = EvidenceValue["kind"];
export type SlotStatus = SlotResult["status"];
export type TravelMode = NonNullable<Preferences["travel_mode"]>;
export type Sensitivity = NonNullable<Preferences["sensitivities"]>[number];

export type StageEvent = { stage: string; detail?: string | null };
