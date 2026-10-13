export const money = (value: number | null, currency = "USD") =>
  value == null
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency,
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(value);
export const bps = (value: number | null) =>
  value == null ? "—" : `${value.toFixed(2)} bps`;
export const integer = (value: number) => value.toLocaleString("en-US");
