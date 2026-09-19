import type { ReactElement, ReactNode } from "react";

export function StatusBadge({ value }: { value: string | null | undefined }): ReactElement {
  const text = value ?? "NOT_AVAILABLE";
  const normalized = text.toLowerCase().replaceAll("_", "-");
  const tone = ["pass", "accepted", "available", "ready", "ok"].includes(normalized)
    ? "positive"
    : ["fail", "blocked", "special-review", "not-evaluated", "not-available"].includes(
          normalized,
        )
      ? "negative"
      : ["watch", "partial", "unknown"].includes(normalized)
        ? "caution"
        : "neutral";
  return (
    <span className={`status-badge status-${tone}`} aria-label={`Status ${text}`}>
      <span className="status-dot" aria-hidden="true" />
      {text}
    </span>
  );
}

export function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "NOT_AVAILABLE";
  if (typeof value === "number" && !Number.isFinite(value)) return "NOT_AVAILABLE";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function HashValue({ value }: { value: string | null | undefined }): ReactElement {
  return <code className="hash-value">{displayValue(value)}</code>;
}

export function LoadingState({ label = "Loading frozen surface data" }): ReactElement {
  return (
    <div className="state-panel loading-panel" aria-busy="true" data-testid="loading-state">
      <span className="loading-line loading-line-wide" />
      <span className="loading-line" />
      <p>{label}</p>
    </div>
  );
}

export function ErrorState({
  title = "The read-only API is unavailable",
  message,
  onRetry,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
}): ReactElement {
  return (
    <div className="state-panel error-panel" role="alert">
      <StatusBadge value="ERROR" />
      <h2>{title}</h2>
      <p>{message ?? "The surface could not be loaded. Check the local API process and try again."}</p>
      {onRetry ? (
        <button className="button button-secondary" onClick={onRetry} type="button">
          Retry GET request
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState(): ReactElement {
  return (
    <div className="state-panel empty-panel">
      <StatusBadge value="NO_MATCHES" />
      <h2>No frozen surfaces match</h2>
      <p>
        This read model is explicit and bounded. Remove a filter or prepare another validated
        snapshot before it can appear here.
      </p>
    </div>
  );
}

export function Section({
  title,
  children,
  className = "",
}: {
  title: string;
  children: ReactNode;
  className?: string;
}): ReactElement {
  return (
    <section className={`detail-section ${className}`.trim()}>
      <div className="section-heading">
        <h2>{title}</h2>
      </div>
      {children}
    </section>
  );
}

export function FieldList({
  rows,
  className = "",
}: {
  rows: readonly { label: string; value: unknown; mono?: boolean }[];
  className?: string;
}): ReactElement {
  return (
    <dl className={`field-list ${className}`.trim()}>
      {rows.map((row) => (
        <div className="field-row" key={row.label}>
          <dt>{row.label}</dt>
          <dd className={row.mono ? "mono-value" : undefined}>{displayValue(row.value)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function StringList({
  items,
  empty = "None recorded",
}: {
  items: readonly string[] | undefined;
  empty?: string;
}): ReactElement {
  if (!items?.length) return <p className="muted-copy">{empty}</p>;
  return (
    <ul className="plain-list">
      {items.map((item, index) => (
        <li key={`${item}-${index}`}>{item}</li>
      ))}
    </ul>
  );
}

export function PillList({ items }: { items: readonly string[] | undefined }): ReactElement | null {
  if (!items?.length) return null;
  return (
    <div className="pill-list">
      {items.map((item) => (
        <span className="data-pill" key={item}>
          {item}
        </span>
      ))}
    </div>
  );
}
