import { useEffect, useMemo, useRef, useState } from "react";

const ROW_HEIGHT = 36;
const pad = (value: number) => String(value).padStart(2, "0");
const minutes = (value: string) => {
  const [hour, minute] = value.split(":").map(Number);
  return hour * 60 + minute;
};
const clock = (value: number) =>
  `${pad(Math.floor(value / 60))}:${pad(value % 60)}`;

function Wheel({
  id,
  label,
  values,
  value,
  onChange,
}: {
  id: string;
  label: string;
  values: number[];
  value: number;
  onChange: (value: number) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const positioning = useRef(false);
  const index = Math.max(0, values.indexOf(value));
  useEffect(() => {
    positioning.current = true;
    if (container.current) container.current.scrollTop = index * ROW_HEIGHT;
    const frame = requestAnimationFrame(() => {
      positioning.current = false;
    });
    return () => {
      cancelAnimationFrame(frame);
      if (timer.current) clearTimeout(timer.current);
    };
  }, [index, values]);
  return (
    <div className="wheel-column">
      <span className="wheel-label">
        {label.endsWith("hour") ? "Hour" : "Minute"}
      </span>
      <div className="wheel-window">
        <div
          ref={container}
          className="time-wheel"
          role="listbox"
          aria-label={label}
          aria-activedescendant={`${id}-${value}`}
          tabIndex={0}
          onKeyDown={(event) => {
            const direction =
              event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
            if (direction || event.key === "Home" || event.key === "End") {
              event.preventDefault();
              onChange(
                values[
                  event.key === "Home"
                    ? 0
                    : event.key === "End"
                      ? values.length - 1
                      : Math.max(
                          0,
                          Math.min(values.length - 1, index + direction),
                        )
                ],
              );
            }
          }}
          onScroll={(event) => {
            if (positioning.current) return;
            if (timer.current) clearTimeout(timer.current);
            const element = event.currentTarget;
            timer.current = setTimeout(() => {
              const next =
                values[
                  Math.max(
                    0,
                    Math.min(
                      values.length - 1,
                      Math.round(element.scrollTop / ROW_HEIGHT),
                    ),
                  )
                ];
              if (next !== value) onChange(next);
            }, 120);
          }}
        >
          {values.map((item) => (
            <div
              id={`${id}-${item}`}
              key={item}
              className={
                item === value ? "wheel-option selected-time" : "wheel-option"
              }
              role="option"
              aria-selected={item === value}
              onClick={() => {
                onChange(item);
                container.current?.focus({ preventScroll: true });
              }}
            >
              {pad(item)}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function TimePicker({
  id,
  label,
  value,
  min = "09:30",
  max = "16:00",
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  min?: string;
  max?: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const lower = minutes(min);
  const upper = minutes(max);
  const current = Math.max(
    lower,
    Math.min(upper, Number.isFinite(minutes(value)) ? minutes(value) : lower),
  );
  const hour = Math.floor(current / 60);
  const minute = current % 60;
  const hours = useMemo(
    () =>
      Array.from(
        { length: Math.floor(upper / 60) - Math.floor(lower / 60) + 1 },
        (_, i) => Math.floor(lower / 60) + i,
      ),
    [lower, upper],
  );
  const minuteValues = useMemo(
    () =>
      Array.from({ length: 60 }, (_, i) => i).filter(
        (i) => hour * 60 + i >= lower && hour * 60 + i <= upper,
      ),
    [hour, lower, upper],
  );
  useEffect(() => {
    if (!open) return;
    root.current
      ?.querySelector<HTMLElement>('[role="listbox"]')
      ?.focus({ preventScroll: true });
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  return (
    <div
      className="time-picker"
      ref={root}
      onBlurCapture={(event) => {
        if (
          event.relatedTarget &&
          !event.currentTarget.contains(event.relatedTarget)
        )
          setOpen(false);
      }}
    >
      <label htmlFor={id}>{label}</label>
      <div className="time-input-row">
        <input
          id={id}
          type="time"
          required
          step="60"
          min={min}
          max={max}
          value={value}
          onInput={(event) => onChange(event.currentTarget.value)}
        />
        <button
          type="button"
          ref={trigger}
          className="time-trigger"
          aria-label={`Choose ${label.toLowerCase()} time`}
          aria-expanded={open}
          aria-controls={`${id}-picker`}
          aria-haspopup="dialog"
          onClick={() => setOpen(!open)}
        >
          <span aria-hidden="true">↕</span>
        </button>
      </div>
      {open && (
        <div
          className="time-popover"
          id={`${id}-picker`}
          role="dialog"
          aria-label={`${label} time picker`}
        >
          <div className="time-popover-heading">
            <strong>{value || min} ET</strong>
            <span>Scroll or swipe</span>
          </div>
          <div className="time-wheels">
            <Wheel
              id={`${id}-hour`}
              label={`${label} hour`}
              values={hours}
              value={hour}
              onChange={(next) =>
                onChange(
                  clock(Math.max(lower, Math.min(upper, next * 60 + minute))),
                )
              }
            />
            <span className="wheel-colon" aria-hidden="true">
              :
            </span>
            <Wheel
              id={`${id}-minute`}
              label={`${label} minute`}
              values={minuteValues}
              value={minute}
              onChange={(next) => onChange(clock(hour * 60 + next))}
            />
          </div>
          <button
            type="button"
            className="time-done"
            onClick={() => {
              setOpen(false);
              trigger.current?.focus();
            }}
          >
            Done
          </button>
        </div>
      )}
    </div>
  );
}
