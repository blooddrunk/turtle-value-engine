import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import type { ReactElement } from "react";

import {
  fetchHealth,
  fetchSurfaces,
  type SurfaceMetadata,
} from "../api/client";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  StatusBadge,
  TechnicalDetails,
} from "../components";
import { formatScalar, getCopy, useCopy, useLocale } from "../presentation";

function SurfaceRow({ surface }: { surface: SurfaceMetadata }): ReactElement {
  const locale = useLocale();
  const copy = getCopy(locale);
  return (
    <tr>
      <th scope="row">
        <Link
          className="surface-link"
          params={{ surfaceId: surface.surface_id }}
          to="/surfaces/$surfaceId"
        >
          <span>{surface.primary_listing}</span>
        </Link>
      </th>
      <td>{surface.as_of}</td>
      <td>
        <span className="profile-label">{surface.profile_id}</span>
      </td>
      <td>
        <TechnicalDetails summary={copy.tableTechnical}>
          <dl className="field-list technical-field-list">
            <div className="field-row">
              <dt>{copy.analysisIdLabel}</dt>
              <dd className="mono-value">{formatScalar(surface.analysis_id, locale)}</dd>
            </div>
            <div className="field-row">
              <dt>{copy.surfaceIdLabel}</dt>
              <dd className="mono-value">{formatScalar(surface.surface_id, locale)}</dd>
            </div>
            <div className="field-row">
              <dt>{copy.contentHashLabel}</dt>
              <dd className="mono-value">{formatScalar(surface.content_sha256, locale)}</dd>
            </div>
          </dl>
        </TechnicalDetails>
      </td>
    </tr>
  );
}

export function OverviewPage(): ReactElement {
  const copy = useCopy();
  const search = useSearch({ from: "/" });
  const navigate = useNavigate({ from: "/" });
  const [listing, setListing] = useState(search.listing ?? "");
  const [profile, setProfile] = useState(search.profile ?? "");
  const [asOf, setAsOf] = useState(search.asOf ?? "");
  const filters = { listing: search.listing, profile: search.profile, asOf: search.asOf };
  const hasActiveFilters = Boolean(filters.listing || filters.profile || filters.asOf);
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth });
  const surfaces = useQuery({
    queryKey: ["surfaces", filters],
    queryFn: () => fetchSurfaces(filters),
  });

  function submitFilters(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    void navigate({
      search: {
        listing: listing || undefined,
        profile: profile || undefined,
        asOf: asOf || undefined,
      },
    });
  }

  function clearFilters(): void {
    setListing("");
    setProfile("");
    setAsOf("");
    void navigate({ search: {} });
  }

  const countLabel = surfaces.data
    ? copy.countLabel(surfaces.data.surfaces.length)
    : copy.awaitingIndex;

  return (
    <div className="page page-overview">
      <div className="page-heading">
        <div>
          <h1>{copy.overviewTitle}</h1>
          <p className="lede">{copy.overviewLede}</p>
        </div>
        <div className="heading-meta">
          <StatusBadge value="READ_ONLY" />
        </div>
      </div>

      <section className="health-strip" aria-label={copy.healthLabel}>
        <div className="health-label">
          <span className="health-pulse" aria-hidden="true" />
          <span>{copy.healthLabel}</span>
        </div>
        {health.isPending ? <span className="muted-copy">{copy.healthChecking}</span> : null}
        {health.isError ? <StatusBadge value="UNAVAILABLE" /> : null}
        {health.data ? (
          <>
            <StatusBadge value={health.data.status.toUpperCase()} />
            <span className="health-count">{copy.healthLoadedCount(health.data.loaded_snapshot_count)}</span>
          </>
        ) : null}
        <button
          className="button button-quiet"
          onClick={() => void Promise.all([health.refetch(), surfaces.refetch()])}
          type="button"
        >
          {copy.refreshData}
        </button>
      </section>

      <section className="filter-panel" aria-labelledby="filter-heading">
        <div className="section-heading filter-heading">
          <h2 id="filter-heading">{copy.filterHeading}</h2>
          <span className="table-count">{countLabel}</span>
        </div>
        <form className="filter-form" onSubmit={submitFilters}>
          <label>
            {copy.filterListing}
            <input
              name="listing"
              onChange={(event) => setListing(event.target.value)}
              placeholder={copy.filterListingPlaceholder}
              value={listing}
            />
          </label>
          <label>
            {copy.filterProfile}
            <input
              name="profile"
              onChange={(event) => setProfile(event.target.value)}
              placeholder={copy.filterProfilePlaceholder}
              value={profile}
            />
          </label>
          <label>
            {copy.filterAsOf}
            <input
              name="asOf"
              onChange={(event) => setAsOf(event.target.value)}
              type="date"
              value={asOf}
            />
          </label>
          <div className="filter-actions">
            <button className="button button-primary" type="submit">
              {copy.applyFilters}
            </button>
            <button className="button button-secondary" onClick={clearFilters} type="button">
              {copy.clearFilters}
            </button>
          </div>
        </form>
        <p className="filter-note">
          {copy.filterNotePrefix}{" "}
          <code>primary_listing · profile_id · as_of</code>
        </p>
      </section>

      <section className="surface-index" aria-labelledby="surface-index-heading">
        <div className="section-heading">
          <div>
            <h2 id="surface-index-heading">{copy.loadedSurfacesHeading}</h2>
            <p className="section-description">{copy.loadedSurfacesDescription}</p>
          </div>
          <span className="section-rule" aria-hidden="true" />
        </div>

        {surfaces.isPending ? <LoadingState label={copy.loadingOverview} /> : null}
        {surfaces.isError ? (
          <ErrorState error={surfaces.error} onRetry={() => void surfaces.refetch()} />
        ) : null}
        {surfaces.data && surfaces.data.surfaces.length === 0 ? (
          <EmptyState variant={hasActiveFilters ? "no-matches" : "no-snapshots"} />
        ) : null}
        {surfaces.data && surfaces.data.surfaces.length > 0 ? (
          <div className="table-frame">
            <table className="surface-table">
              <thead>
                <tr>
                  <th scope="col">{copy.tableListing}</th>
                  <th scope="col">{copy.tableAsOf}</th>
                  <th scope="col">{copy.tableProfile}</th>
                  <th scope="col">{copy.tableTechnical}</th>
                </tr>
              </thead>
              <tbody>
                {surfaces.data.surfaces.map((surface) => (
                  <SurfaceRow key={surface.surface_id} surface={surface} />
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
