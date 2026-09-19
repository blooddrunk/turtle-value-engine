import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import type { ReactElement } from "react";

import {
  buildSurfacesUrl,
  fetchHealth,
  fetchSurfaces,
  type SurfaceMetadata,
} from "../api/client";
import { EmptyState, ErrorState, HashValue, LoadingState, StatusBadge } from "../components";

function SurfaceRow({ surface }: { surface: SurfaceMetadata }): ReactElement {
  return (
    <tr>
      <th scope="row">
        <Link className="surface-link" params={{ surfaceId: surface.surface_id }} to="/surfaces/$surfaceId">
          <span>{surface.primary_listing}</span>
          <small>{surface.analysis_id}</small>
        </Link>
      </th>
      <td>{surface.as_of}</td>
      <td>
        <span className="profile-label">{surface.profile_id}</span>
      </td>
      <td>
        <HashValue value={surface.content_sha256} />
      </td>
    </tr>
  );
}

export function OverviewPage(): ReactElement {
  const search = useSearch({ from: "/" });
  const navigate = useNavigate({ from: "/" });
  const [listing, setListing] = useState(search.listing ?? "");
  const [profile, setProfile] = useState(search.profile ?? "");
  const [asOf, setAsOf] = useState(search.asOf ?? "");
  const filters = { listing: search.listing, profile: search.profile, asOf: search.asOf };
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
    ? `${surfaces.data.surfaces.length} ${surfaces.data.surfaces.length === 1 ? "surface" : "surfaces"}`
    : "Awaiting surface index";

  return (
    <div className="page page-overview">
      <div className="page-heading">
        <div>
          <h1>Research surface ledger</h1>
          <p className="lede">
            A quiet read model for frozen company analysis. Every value below comes from the
            validated M6-B API; this surface never recalculates investment semantics.
          </p>
        </div>
        <div className="heading-meta">
          <StatusBadge value="READ_ONLY" />
          <span className="contract-note">research_surface_snapshot_v1</span>
        </div>
      </div>

      <section className="health-strip" aria-label="API-local health">
        <div className="health-label">
          <span className="health-pulse" aria-hidden="true" />
          <span>API-local health</span>
        </div>
        {health.isPending ? <span className="muted-copy">Checking the local adapter…</span> : null}
        {health.isError ? <StatusBadge value="UNAVAILABLE" /> : null}
        {health.data ? (
          <>
            <StatusBadge value={health.data.status.toUpperCase()} />
            <span className="health-count">{health.data.loaded_snapshot_count} loaded snapshots</span>
          </>
        ) : null}
        <button
          className="button button-quiet"
          onClick={() => void Promise.all([health.refetch(), surfaces.refetch()])}
          type="button"
        >
          Refresh GET data
        </button>
      </section>

      <section className="filter-panel" aria-labelledby="filter-heading">
        <div className="section-heading filter-heading">
          <h2 id="filter-heading">Narrow the ledger</h2>
          <span className="table-count">{countLabel}</span>
        </div>
        <form className="filter-form" onSubmit={submitFilters}>
          <label>
            Listing
            <input
              name="listing"
              onChange={(event) => setListing(event.target.value)}
              placeholder="e.g. SH600000"
              value={listing}
            />
          </label>
          <label>
            Profile
            <input
              name="profile"
              onChange={(event) => setProfile(event.target.value)}
              placeholder="e.g. strict-v1"
              value={profile}
            />
          </label>
          <label>
            As-of date
            <input
              name="asOf"
              onChange={(event) => setAsOf(event.target.value)}
              type="date"
              value={asOf}
            />
          </label>
          <div className="filter-actions">
            <button className="button button-primary" type="submit">
              Apply filters
            </button>
            <button className="button button-secondary" onClick={clearFilters} type="button">
              Clear
            </button>
          </div>
        </form>
        <p className="filter-note">
          Supported API filters only: <code>{buildSurfacesUrl({ listing: "…" })}</code>
        </p>
      </section>

      <section className="surface-index" aria-labelledby="surface-index-heading">
        <div className="section-heading">
          <div>
            <h2 id="surface-index-heading">Loaded surfaces</h2>
            <p className="section-description">Deterministic metadata from the list endpoint.</p>
          </div>
          <span className="section-rule" aria-hidden="true" />
        </div>

        {surfaces.isPending ? <LoadingState label="Reading the frozen surface index" /> : null}
        {surfaces.isError ? (
          <ErrorState
            message={surfaces.error instanceof Error ? surfaces.error.message : undefined}
            onRetry={() => void surfaces.refetch()}
          />
        ) : null}
        {surfaces.data && surfaces.data.surfaces.length === 0 ? <EmptyState /> : null}
        {surfaces.data && surfaces.data.surfaces.length > 0 ? (
          <div className="table-frame">
            <table className="surface-table">
              <thead>
                <tr>
                  <th scope="col">Listing / analysis</th>
                  <th scope="col">As of</th>
                  <th scope="col">Profile</th>
                  <th scope="col">Content hash</th>
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
