import type { components } from "../generated/surface-api";

export type SurfaceHealth = components["schemas"]["SurfaceHealthResponse"];
export type SurfaceListResponse = components["schemas"]["SurfaceListResponse"];
export type SurfaceMetadata = components["schemas"]["SurfaceMetadata"];
export type SurfaceSnapshot = components["schemas"]["ResearchSurfaceSnapshotV1"];
export type SurfaceErrorResponse = components["schemas"]["SurfaceErrorResponse"];

export interface SurfaceFilters {
  listing?: string;
  profile?: string;
  asOf?: string;
}

export function buildSurfacesUrl(filters: SurfaceFilters = {}): string {
  const params = new URLSearchParams();
  if (filters.listing) params.set("primary_listing", filters.listing);
  if (filters.profile) params.set("profile_id", filters.profile);
  if (filters.asOf) params.set("as_of", filters.asOf);
  const query = params.toString();
  return `/api/v1/surfaces${query ? `?${query}` : ""}`;
}

export class SurfaceAPIError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "SurfaceAPIError";
    this.status = status;
    this.code = code;
  }
}

async function request<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let code = "REQUEST_FAILED";
    let message = `Request failed with status ${response.status}`;
    try {
      const body = (await response.json()) as SurfaceErrorResponse;
      code = body.error?.code ?? code;
      message = body.error?.message ?? message;
    } catch {
      // Preserve a stable client error when the upstream body is not JSON.
    }
    throw new SurfaceAPIError(response.status, code, message);
  }
  return (await response.json()) as T;
}

export function fetchHealth(): Promise<SurfaceHealth> {
  return request<SurfaceHealth>("/api/healthz");
}

export function fetchSurfaces(filters: SurfaceFilters = {}): Promise<SurfaceListResponse> {
  return request<SurfaceListResponse>(buildSurfacesUrl(filters));
}

export function fetchSurface(surfaceId: string): Promise<SurfaceSnapshot> {
  return request<SurfaceSnapshot>(`/api/v1/surfaces/${encodeURIComponent(surfaceId)}`);
}
