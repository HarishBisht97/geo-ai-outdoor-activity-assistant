import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { QueryBox } from "./QueryBox";

function Box({ onSubmit }: { onSubmit: () => void }) {
  const [v, setV] = useState("");
  return <QueryBox value={v} onChange={setV} onSubmit={onSubmit} busy={false} />;
}

describe("QueryBox", () => {
  it("keeps Find disabled until the question is at least 3 characters", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<Box onSubmit={onSubmit} />);
    const btn = screen.getByRole("button", { name: /find/i });
    expect(btn).toBeDisabled();
    await user.type(screen.getByLabelText(/your question/i), "hi");
    expect(btn).toBeDisabled();
    await user.type(screen.getByLabelText(/your question/i), " there");
    expect(btn).toBeEnabled();
    await user.click(btn);
    expect(onSubmit).toHaveBeenCalledOnce();
  });
});
