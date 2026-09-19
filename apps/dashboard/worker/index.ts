interface Env {
  ASSETS: Fetcher;
  SURFACE_API_ORIGIN?: string;
}

const ALLOWED_FILTERS = new Set(["primary_listing", "profile_id", "as_of"]);
const SURFACE_ID = /^[0-9a-f]{64}$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function errorResponse(status: number, code: string, message: string): Response {
  return Response.json({ error: { code, message } }, { status });
}

function upstreamOrigin(rawOrigin: string | undefined): URL | null {
  if (!rawOrigin) return null;
  try {
    const origin = new URL(rawOrigin);
    if (!["http:", "https:"].includes(origin.protocol)) return null;
    if (origin.username || origin.password || origin.pathname !== "/" || origin.search) {
      return null;
    }
    return origin;
  } catch {
    return null;
  }
}

function allowedQuery(url: URL): URLSearchParams | Response {
  const query = new URLSearchParams();
  for (const [key, value] of url.searchParams.entries()) {
    if (!ALLOWED_FILTERS.has(key) || url.searchParams.getAll(key).length !== 1) {
      return errorResponse(400, "INVALID_QUERY_PARAMETER", "unsupported query parameter");
    }
    if (value.length === 0 || value.length > 80) {
      return errorResponse(400, "INVALID_QUERY_PARAMETER", "invalid query parameter");
    }
    if (key === "as_of" && !ISO_DATE.test(value)) {
      return errorResponse(400, "INVALID_QUERY_PARAMETER", "as_of must use YYYY-MM-DD");
    }
    query.set(key, value);
  }
  return query;
}

function upstreamPath(url: URL): string | Response {
  if (url.pathname === "/api/healthz") {
    if (url.search) return errorResponse(400, "INVALID_QUERY_PARAMETER", "healthz does not accept filters");
    return "/healthz";
  }
  if (url.pathname === "/api/v1/surfaces") {
    return "/v1/surfaces";
  }
  const match = url.pathname.match(/^\/api\/v1\/surfaces\/([^/]+)$/);
  if (match && SURFACE_ID.test(match[1])) {
    if (url.search) return errorResponse(400, "INVALID_QUERY_PARAMETER", "surface detail does not accept filters");
    return `/v1/surfaces/${match[1]}`;
  }
  return errorResponse(404, "API_ROUTE_NOT_FOUND", "read-only API route not found");
}

function copyReadHeaders(source: Headers): Headers {
  const headers = new Headers();
  for (const name of ["cache-control", "content-type", "etag", "vary"]) {
    const value = source.get(name);
    if (value) headers.set(name, value);
  }
  return headers;
}

async function proxy(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  if (request.method !== "GET" && request.method !== "HEAD") {
    return errorResponse(405, "READ_ONLY_METHOD_NOT_ALLOWED", "read-only method not allowed");
  }
  const path = upstreamPath(url);
  if (path instanceof Response) return path;
  const query = allowedQuery(url);
  if (query instanceof Response) return query;
  const origin = upstreamOrigin(env.SURFACE_API_ORIGIN);
  if (!origin) {
    return errorResponse(503, "UPSTREAM_NOT_CONFIGURED", "surface API origin is not configured");
  }

  const target = new URL(path, origin);
  target.search = query.toString();
  const headers = new Headers();
  const ifNoneMatch = request.headers.get("if-none-match");
  if (ifNoneMatch) headers.set("if-none-match", ifNoneMatch);
  try {
    const upstream = await fetch(target, { method: request.method, headers });
    return new Response(request.method === "HEAD" ? null : upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: copyReadHeaders(upstream.headers),
    });
  } catch {
    return errorResponse(502, "UPSTREAM_UNREACHABLE", "surface API is unreachable");
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/")) {
      return proxy(request, env);
    }
    return env.ASSETS.fetch(request);
  },
} satisfies ExportedHandler<Env>;

export { allowedQuery, proxy, upstreamPath, upstreamOrigin };
