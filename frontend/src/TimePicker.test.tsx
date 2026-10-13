// @vitest-environment jsdom
import { useState } from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { TimePicker } from "./TimePicker";

function Harness({ initial = "10:15" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <TimePicker id="start" label="Start" value={value} onChange={setValue} />
      <button>Outside</button>
    </>
  );
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) =>
    setTimeout(() => callback(0), 0),
  );
  vi.stubGlobal("cancelAnimationFrame", clearTimeout);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
function open() {
  fireEvent.click(screen.getByRole("button", { name: "Choose start time" }));
  act(() => vi.advanceTimersByTime(20));
}
it("clamps the minute at both session boundaries when changing hour", () => {
  render(<Harness />);
  open();
  const hours = screen.getByRole("listbox", { name: "Start hour" });
  fireEvent.keyDown(hours, { key: "Home" });
  expect((screen.getByLabelText("Start") as HTMLInputElement).value).toBe(
    "09:30",
  );
  expect(
    within(screen.getByRole("listbox", { name: "Start minute" })).getAllByRole(
      "option",
    ),
  ).toHaveLength(30);
  fireEvent.keyDown(hours, { key: "End" });
  expect((screen.getByLabelText("Start") as HTMLInputElement).value).toBe(
    "16:00",
  );
  expect(
    within(screen.getByRole("listbox", { name: "Start minute" })).getAllByRole(
      "option",
    ),
  ).toHaveLength(1);
});
it("commits a scrolled minute and keeps the typed input in sync", () => {
  render(<Harness />);
  open();
  const minuteWheel = screen.getByRole("listbox", { name: "Start minute" });
  fireEvent.scroll(minuteWheel, { target: { scrollTop: 36 * 42 } });
  act(() => vi.advanceTimersByTime(150));
  expect((screen.getByLabelText("Start") as HTMLInputElement).value).toBe(
    "10:42",
  );
  fireEvent.input(screen.getByLabelText("Start"), {
    target: { value: "11:05" },
  });
  expect(
    within(screen.getByRole("listbox", { name: "Start hour" }))
      .getByRole("option", { name: "11" })
      .getAttribute("aria-selected"),
  ).toBe("true");
  expect(
    within(minuteWheel)
      .getByRole("option", { name: "05" })
      .getAttribute("aria-selected"),
  ).toBe("true");
});
it("supports arrow keys, Done, Escape and outside dismissal", () => {
  render(<Harness />);
  open();
  fireEvent.keyDown(screen.getByRole("listbox", { name: "Start minute" }), {
    key: "ArrowDown",
  });
  expect((screen.getByLabelText("Start") as HTMLInputElement).value).toBe(
    "10:16",
  );
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(
    screen.getByRole("button", { name: "Choose start time" }),
  );
  open();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  open();
  fireEvent.pointerDown(screen.getByRole("button", { name: "Outside" }));
  expect(screen.queryByRole("dialog")).toBeNull();
});
