import { describe, expect, it } from "vitest";
import { parseSse } from "./api";

describe("parseSse", () => {
  it("splits complete events and keeps a partial trailing block", () => {
    const { events, rest } = parseSse("event: stage\ndata: {\"stage\":\"ranking\"}\n\nevent: ranking\ndata: {\"status\"");
    expect(events).toEqual([{ event: "stage", data: "{\"stage\":\"ranking\"}" }]);
    expect(rest).toContain("event: ranking");
  });

  it("joins multi-line data", () => {
    const { events } = parseSse("event: done\ndata: {\"a\":1,\ndata: \"b\":2}\n\n");
    expect(events[0]).toEqual({ event: "done", data: "{\"a\":1,\n\"b\":2}" });
  });
});
