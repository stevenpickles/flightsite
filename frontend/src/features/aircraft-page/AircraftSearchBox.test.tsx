import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AircraftSearchBox,
  SEARCH_DEBOUNCE_MS,
} from "@/features/aircraft-page/AircraftSearchBox";
import { MAX_SEARCH_LENGTH } from "@/features/aircraft-page/lib/urlState";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function input(): HTMLInputElement {
  return screen.getByLabelText("Filter aircraft", { selector: "input" });
}

function type(value: string) {
  fireEvent.change(input(), { target: { value } });
}

describe("AircraftSearchBox", () => {
  it("commits once, after the debounce, however many keystrokes came first", () => {
    const onChange = vi.fn();
    render(<AircraftSearchBox value={undefined} onChange={onChange} />);

    type("G");
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS - 50));
    type("G-");
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS - 50));
    type("G-EZ");

    expect(onChange).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("G-EZ");
  });

  it("trims what it commits, and treats whitespace as no search", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <AircraftSearchBox value="BAW" onChange={onChange} />,
    );

    type("   ");
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS));
    expect(onChange).toHaveBeenLastCalledWith(undefined);

    rerender(<AircraftSearchBox value={undefined} onChange={onChange} />);
    type("  ezy ");
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS));
    expect(onChange).toHaveBeenLastCalledWith("ezy");
  });

  it("does not commit a keystroke that leaves the search unchanged", () => {
    const onChange = vi.fn();
    render(<AircraftSearchBox value="BAW" onChange={onChange} />);

    type("BAW ");
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS * 2));

    expect(onChange).not.toHaveBeenCalled();
  });

  it("commits at once on Enter, without waiting for the debounce", () => {
    const onChange = vi.fn();
    render(<AircraftSearchBox value={undefined} onChange={onChange} />);

    type("N123");
    fireEvent.submit(input());

    expect(onChange).toHaveBeenCalledWith("N123");
  });

  it("clears the box and the search together", () => {
    const onChange = vi.fn();
    render(<AircraftSearchBox value="DAL" onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "Clear filter" }));

    expect(input().value).toBe("");
    expect(onChange).toHaveBeenCalledWith(undefined);
    expect(
      screen.queryByRole("button", { name: "Clear filter" }),
    ).not.toBeInTheDocument();
  });

  it("follows the URL when it changes underneath the box", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <AircraftSearchBox value="DAL" onChange={onChange} />,
    );
    expect(input().value).toBe("DAL");

    // Back button, a shared link, "Clear filters" elsewhere...
    rerender(<AircraftSearchBox value="UAL" onChange={onChange} />);
    expect(input().value).toBe("UAL");

    rerender(<AircraftSearchBox value={undefined} onChange={onChange} />);
    expect(input().value).toBe("");
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS * 2));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("keeps a trailing space the user is still typing after its own commit", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <AircraftSearchBox value={undefined} onChange={onChange} />,
    );

    type("Delta ");
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS));
    expect(onChange).toHaveBeenCalledWith("Delta");
    rerender(<AircraftSearchBox value="Delta" onChange={onChange} />);

    expect(input().value).toBe("Delta ");
  });

  it("caps the input at the API's length and explains what it matches", () => {
    render(<AircraftSearchBox value={undefined} onChange={vi.fn()} />);

    expect(input()).toHaveAttribute("maxLength", String(MAX_SEARCH_LENGTH));
    expect(input()).toHaveAccessibleDescription(
      /icao address, registration, callsign, type or operator/i,
    );
    expect(screen.getByRole("search")).toBeInTheDocument();
  });

  it("holds back a single character with a hint, and sends no request", () => {
    const onChange = vi.fn();
    render(<AircraftSearchBox value={undefined} onChange={onChange} />);

    type(" a ");
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS * 2));
    fireEvent.submit(input());

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Type at least 2 characters.",
    );

    type("ab");
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS));

    expect(onChange).toHaveBeenCalledWith("ab");
    expect(screen.getByRole("status")).toHaveTextContent("");
  });

  it("keeps the committed search while the box is cut back to one character", () => {
    const onChange = vi.fn();
    render(<AircraftSearchBox value="DAL" onChange={onChange} />);

    type("D");
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS * 2));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(/at least 2/);
  });
});
