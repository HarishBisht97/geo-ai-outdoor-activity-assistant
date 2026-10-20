import { describe, expect, it } from "vitest";
import { fmtRange, fmtValue, scoreColor } from "./format";

describe("format", () => {
  it("renders times in the location timezone, not the browser's", () => {
    expect(fmtRange("2026-10-21T06:00:00+05:30", "2026-10-21T11:00:00+05:30", "Asia/Kolkata")).toBe(
      "Wed, 21 Oct, 06:00–11:00",
    );
  });

  it("unknown evidence is the word Unknown, not a zero", () => {
    expect(fmtValue({ value: null, unit: "degC", kind: "unknown" })).toBe("Unknown");
    expect(fmtValue({ value: 29.4, unit: "degC", kind: "derived" })).toBe("29°C");
    expect(fmtValue({ value: 170, unit: "US_AQI", kind: "modeled" })).toBe("170");
  });

  it("score colour is not the only encoding (values stay numeric)", () => {
    expect(scoreColor(80)).not.toBe(scoreColor(20));
    expect(scoreColor(null)).toBe("#94a3b8");
  });
});
