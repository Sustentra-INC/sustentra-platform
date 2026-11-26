/* @vitest-environment jsdom */
import { describe, it, expect, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { OtpInput } from "../OtpInput";

function setup(value = "", onChange = vi.fn()) {
  const result = render(<OtpInput length={6} value={value} onChange={onChange} />);
  return { onChange, ...result };
}

describe("OtpInput", () => {
  it("renders 6 labeled boxes", () => {
    setup();
    for (let i = 1; i <= 6; i++) {
      expect(screen.getByLabelText(`Digit ${i}`)).toBeInTheDocument();
    }
  });

  it("typing a digit calls onChange with the updated code", () => {
    const onChange = vi.fn();
    setup("", onChange);
    fireEvent.change(screen.getByLabelText("Digit 1"), { target: { value: "3" } });
    expect(onChange).toHaveBeenCalledWith("3");
  });

  it("paste fills all digits from Digit 1", () => {
    const onChange = vi.fn();
    setup("", onChange);
    fireEvent.paste(screen.getByLabelText("Digit 1"), {
      clipboardData: { getData: () => "123456" },
    });
    expect(onChange).toHaveBeenCalledWith("123456");
  });

  it("paste strips non-digits and truncates to length", () => {
    const onChange = vi.fn();
    setup("", onChange);
    fireEvent.paste(screen.getByLabelText("Digit 1"), {
      clipboardData: { getData: () => "12 34 56 78" },
    });
    expect(onChange).toHaveBeenCalledWith("123456");
  });

  it("backspace on a filled box clears it without moving back", () => {
    const onChange = vi.fn();
    setup("1", onChange);
    fireEvent.keyDown(screen.getByLabelText("Digit 1"), { key: "Backspace" });
    expect(onChange).toHaveBeenCalledWith("");
  });

  it("backspace on an empty box clears the previous digit", () => {
    const onChange = vi.fn();
    setup("12", onChange);
    fireEvent.keyDown(screen.getByLabelText("Digit 3"), { key: "Backspace" });
    expect(onChange).toHaveBeenCalledWith("1");
  });

  it("renders each digit in its box when value is provided", () => {
    setup("123456");
    expect(screen.getByLabelText("Digit 1")).toHaveValue("1");
    expect(screen.getByLabelText("Digit 6")).toHaveValue("6");
  });
});
