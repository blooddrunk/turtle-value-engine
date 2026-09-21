import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { ReactElement } from "react";

import {
  DEFAULT_LOCALE,
  LOCALE_STORAGE_KEY,
  LocaleContext,
  apiErrorPresentation,
  formatScalar,
  getCopy,
  resolveLocale,
  statePresentation,
  useCopy,
  useLocale,
  type Copy,
  type Locale,
} from "./presentation";

interface LocaleControls {
  readonly locale: Locale;
  readonly setLocale: (locale: Locale) => void;
  readonly toggleLocale: () => void;
}

const LocaleControlsContext = createContext<LocaleControls>({
  locale: DEFAULT_LOCALE,
  setLocale: () => undefined,
  toggleLocale: () => undefined,
});

function readStoredLocale(): Locale {
  try {
    return resolveLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY));
  } catch {
    return DEFAULT_LOCALE;
  }
}

/**
 * Client-only locale preference: zh-CN by default, optionally persisted in
 * localStorage. No server state is involved anywhere.
 */
export function LocaleProvider({ children }: { children: ReactNode }): ReactElement {
  const [locale, setLocale] = useState<Locale>(readStoredLocale);
  useEffect(() => {
    document.documentElement.lang = locale;
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    } catch {
      // A blocked localStorage must never break rendering.
    }
  }, [locale]);
  const toggleLocale = useCallback(() => {
    setLocale((current) => (current === "zh-CN" ? "en" : "zh-CN"));
  }, []);
  const controls = useMemo<LocaleControls>(
    () => ({ locale, setLocale, toggleLocale }),
    [locale, toggleLocale],
  );
  return (
    <LocaleControlsContext.Provider value={controls}>
      <LocaleContext.Provider value={locale}>{children}</LocaleContext.Provider>
    </LocaleControlsContext.Provider>
  );
}

export function useLocaleControls(): LocaleControls {
  return useContext(LocaleControlsContext);
}

export function StatusBadge({ value }: { value: string | null | undefined }): ReactElement {
  const locale = useLocale();
  const presentation = statePresentation(value, locale);
  return (
    <span
      className={`status-badge status-${presentation.tone}${presentation.known ? "" : " status-unknown"}`}
      title={`${presentation.raw}：${presentation.explanation}`}
    >
      <span className="status-dot" aria-hidden="true" />
      <span className="status-label">{presentation.label}</span>
      <span className="status-raw">{presentation.raw}</span>
    </span>
  );
}

export function HashValue({ value }: { value: string | null | undefined }): ReactElement {
  const locale = useLocale();
  return <code className="hash-value">{formatScalar(value, locale)}</code>;
}

export function LoadingState({ label }: { label?: string }): ReactElement {
  const copy = useCopy();
  return (
    <div className="state-panel loading-panel" aria-busy="true" data-testid="loading-state">
      <span className="loading-line loading-line-wide" />
      <span className="loading-line" />
      <p>{label ?? copy.loadingStateLabel}</p>
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error?: unknown;
  onRetry?: () => void;
}): ReactElement {
  const locale = useLocale();
  const copy = getCopy(locale);
  const presentation = apiErrorPresentation(error, locale);
  return (
    <div className="state-panel error-panel" role="alert">
      <StatusBadge value="ERROR" />
      <h2>{presentation.title}</h2>
      <p>{presentation.message}</p>
      <details className="error-technical">
        <summary>{copy.errorTechnicalSummary}</summary>
        <dl className="field-list error-technical-list">
          <div className="field-row">
            <dt>{copy.errorHttpStatus}</dt>
            <dd className="mono-value">{presentation.raw.status}</dd>
          </div>
          <div className="field-row">
            <dt>{copy.errorCodeLabel}</dt>
            <dd className="mono-value">{presentation.raw.code}</dd>
          </div>
          <div className="field-row">
            <dt>{copy.errorMessageLabel}</dt>
            <dd className="mono-value">{presentation.raw.message}</dd>
          </div>
        </dl>
      </details>
      {onRetry ? (
        <button className="button button-secondary" onClick={onRetry} type="button">
          {copy.errorRetry}
        </button>
      ) : null}
    </div>
  );
}

export type EmptyVariant = "no-snapshots" | "no-matches";

export function EmptyState({ variant = "no-matches" }: { variant?: EmptyVariant }): ReactElement {
  const copy = useCopy();
  const isNoMatches = variant === "no-matches";
  return (
    <div className="state-panel empty-panel">
      <StatusBadge value={isNoMatches ? "NO_MATCHES" : "NOT_AVAILABLE"} />
      <h2>{isNoMatches ? copy.emptyNoMatchesTitle : copy.emptyNoSnapshotsTitle}</h2>
      <p>{isNoMatches ? copy.emptyNoMatchesBody : copy.emptyNoSnapshotsBody}</p>
    </div>
  );
}

export function TechnicalDetails({
  summary,
  children,
  className = "",
}: {
  summary: string;
  children: ReactNode;
  className?: string;
}): ReactElement {
  return (
    <details className={`technical-details ${className}`.trim()}>
      <summary>{summary}</summary>
      <div className="technical-details-body">{children}</div>
    </details>
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
  rows: readonly { label: string; value: unknown; mono?: boolean; state?: boolean }[];
  className?: string;
}): ReactElement {
  const locale = useLocale();
  return (
    <dl className={`field-list ${className}`.trim()}>
      {rows.map((row) => (
        <div className="field-row" key={row.label}>
          <dt>{row.label}</dt>
          <dd className={row.mono ? "mono-value" : undefined}>
            {row.state ? (
              <StatusBadge value={typeof row.value === "string" ? row.value : null} />
            ) : (
              formatScalar(row.value, locale)
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function StringList({
  items,
  empty,
}: {
  items: readonly string[] | undefined;
  empty?: string;
}): ReactElement {
  const copy = useCopy();
  if (!items?.length) return <p className="muted-copy">{empty ?? copy.stringListEmpty}</p>;
  return (
    <ul className="plain-list">
      {items.map((item, index) => (
        <li key={`${item}-${index}`}>{item}</li>
      ))}
    </ul>
  );
}

/**
 * Raw machine flags (for example MISSING_CDC_FIELD:...) stay compact and
 * monospaced; they are diagnostics, not primary semantic states. Known state
 * codes still get a friendly tooltip, and the raw text is never altered.
 */
export function PillList({ items }: { items: readonly string[] | undefined }): ReactElement | null {
  const locale = useLocale();
  if (!items?.length) return null;
  return (
    <div className="pill-list">
      {items.map((item, index) => {
        const presentation = statePresentation(item, locale);
        return (
          <span
            className={`data-pill${presentation.known ? ` pill-${presentation.tone}` : ""}`}
            key={`${item}-${index}`}
            title={presentation.known ? `${presentation.raw}：${presentation.explanation}` : item}
          >
            {item}
          </span>
        );
      })}
    </div>
  );
}

export type { Copy };
