import { afterEach, describe, expect, it, vi } from "vitest";

import {
  proxy,
  resolveUpstreamConfig,
  type WorkerEnv,
} from "./index";

function testEnv(overrides: Partial<WorkerEnv> = {}): WorkerEnv {
  return {
    ASSETS: { fetch: vi.fn() } as unknown as Fetcher,
    SURFACE_API_ORIGIN: "http://127.0.0.1:8787",
    ...overrides,
  };
}

function request(path: string, init?: RequestInit): Request {
  return new Request(`https://dashboard.example.test${path}`, init);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("M6-C2 Worker upstream security boundary", () => {
  it("keeps loopback HTTP preview valid without service credentials", async () => {
    const upstreamFetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));

    const response = await proxy(request("/api/healthz"), testEnv());

    expect(response.status).toBe(200);
    expect(upstreamFetch).toHaveBeenCalledTimes(1);
    const [, init] = upstreamFetch.mock.calls[0];
    expect(new Headers(init?.headers).get("CF-Access-Client-Id")).toBeNull();
    expect(new Headers(init?.headers).get("CF-Access-Client-Secret")).toBeNull();
  });

  it("accepts remote HTTPS only with a complete server-side service token", () => {
    expect(
      resolveUpstreamConfig("https://surface.example.test", "client-id", "client-secret"),
    ).toEqual({
      config: {
        origin: new URL("https://surface.example.test/"),
        accessClientId: "client-id",
        accessClientSecret: "client-secret",
      },
    });
    expect(resolveUpstreamConfig("http://surface.example.test", "client-id", "client-secret")).toEqual(
      { error: "UPSTREAM_CONFIGURATION_INVALID" },
    );
    expect(resolveUpstreamConfig("https://surface.example.test", undefined, undefined)).toEqual(
      { error: "UPSTREAM_CONFIGURATION_INVALID" },
    );
  });

  it("rejects half-configured credentials for both local and remote origins", async () => {
    for (const origin of ["http://127.0.0.1:8787", "https://surface.example.test"]) {
      for (const credentials of [
        { SURFACE_API_ACCESS_CLIENT_ID: "only-client-id" },
        { SURFACE_API_ACCESS_CLIENT_SECRET: "only-client-secret" },
      ]) {
        const upstreamFetch = vi.spyOn(globalThis, "fetch");
        const response = await proxy(
          request("/api/healthz"),
          testEnv({
            SURFACE_API_ORIGIN: origin,
            ...credentials,
          }),
        );

        expect(response.status).toBe(503);
        await expect(response.json()).resolves.toEqual({
          error: {
            code: "UPSTREAM_CONFIGURATION_INVALID",
            message: "surface API origin configuration is invalid",
          },
        });
        expect(upstreamFetch).not.toHaveBeenCalled();
        vi.restoreAllMocks();
      }
    }
  });

  it("rejects empty or surrounding-whitespace credentials before upstream fetch", async () => {
    for (const origin of ["http://127.0.0.1:8787", "https://surface.example.test"]) {
      for (const credentials of [
        { SURFACE_API_ACCESS_CLIENT_ID: "", SURFACE_API_ACCESS_CLIENT_SECRET: "secret" },
        { SURFACE_API_ACCESS_CLIENT_ID: "client-id", SURFACE_API_ACCESS_CLIENT_SECRET: " " },
        { SURFACE_API_ACCESS_CLIENT_ID: " client-id", SURFACE_API_ACCESS_CLIENT_SECRET: "secret" },
        { SURFACE_API_ACCESS_CLIENT_ID: "client-id", SURFACE_API_ACCESS_CLIENT_SECRET: "secret " },
        { SURFACE_API_ACCESS_CLIENT_ID: " ", SURFACE_API_ACCESS_CLIENT_SECRET: " " },
      ]) {
        const upstreamFetch = vi.spyOn(globalThis, "fetch");
        const response = await proxy(
          request("/api/healthz"),
          testEnv({
            SURFACE_API_ORIGIN: origin,
            ...credentials,
          }),
        );

        expect(response.status).toBe(503);
        await expect(response.json()).resolves.toEqual({
          error: {
            code: "UPSTREAM_CONFIGURATION_INVALID",
            message: "surface API origin configuration is invalid",
          },
        });
        expect(upstreamFetch).not.toHaveBeenCalled();
        vi.restoreAllMocks();
      }
    }
  });

  it("injects configured credentials and ignores browser credential spoofing", async () => {
    let forwardedHeaders: Headers | undefined;
    const upstreamFetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      forwardedHeaders = new Headers(init?.headers);
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json", etag: '"surface-etag"' },
      });
    });

    const response = await proxy(
      request("/api/v1/surfaces", {
        headers: {
          "CF-Access-Client-Id": "browser-client-id",
          "CF-Access-Client-Secret": "browser-client-secret",
          "If-None-Match": '"surface-etag"',
        },
      }),
      testEnv({
        SURFACE_API_ORIGIN: "https://surface.example.test",
        SURFACE_API_ACCESS_CLIENT_ID: "server-client-id",
        SURFACE_API_ACCESS_CLIENT_SECRET: "server-client-secret",
      }),
    );

    expect(response.status).toBe(200);
    const responseBody = await response.text();
    const responseHeaders = JSON.stringify([...response.headers.entries()]);
    expect(responseBody).not.toContain("server-client-id");
    expect(responseBody).not.toContain("server-client-secret");
    expect(responseHeaders).not.toContain("server-client-id");
    expect(responseHeaders).not.toContain("server-client-secret");
    expect(response.headers.get("CF-Access-Client-Secret")).toBeNull();
    expect(forwardedHeaders?.get("CF-Access-Client-Id")).toBe("server-client-id");
    expect(forwardedHeaders?.get("CF-Access-Client-Secret")).toBe("server-client-secret");
    expect(forwardedHeaders?.get("If-None-Match")).toBe('"surface-etag"');
    expect(forwardedHeaders?.get("browser-client-secret")).toBeNull();
    expect(upstreamFetch).toHaveBeenCalledTimes(1);
  });

  it("rejects remote HTTP and malformed origins before any upstream fetch", async () => {
    for (const origin of [
      "http://surface.example.test",
      "https://user:password@surface.example.test",
      "https://surface.example.test/path",
      "https://surface.example.test/?query=1",
      "https://surface.example.test/#fragment",
      "ftp://surface.example.test",
    ]) {
      const upstreamFetch = vi.spyOn(globalThis, "fetch");
      const response = await proxy(
        request("/api/healthz"),
        testEnv({
          SURFACE_API_ORIGIN: origin,
          SURFACE_API_ACCESS_CLIENT_ID: "client-id",
          SURFACE_API_ACCESS_CLIENT_SECRET: "client-secret",
        }),
      );

      expect(response.status).toBe(503);
      await expect(response.json()).resolves.toEqual({
        error: {
          code: "UPSTREAM_CONFIGURATION_INVALID",
          message: "surface API origin configuration is invalid",
        },
      });
      expect(upstreamFetch).not.toHaveBeenCalled();
      vi.restoreAllMocks();
    }
  });

  it("rejects mutations and unknown API routes before upstream fetch", async () => {
    const upstreamFetch = vi.spyOn(globalThis, "fetch");

    for (const method of ["POST", "PUT", "PATCH", "DELETE"] as const) {
      const mutation = await proxy(
        request(`/api/v1/surfaces/${"0".repeat(64)}`, { method, body: "{}" }),
        testEnv({
          SURFACE_API_ORIGIN: "https://surface.example.test",
          SURFACE_API_ACCESS_CLIENT_ID: "server-client-id",
          SURFACE_API_ACCESS_CLIENT_SECRET: "server-client-secret",
        }),
      );
      expect(mutation.status).toBe(405);
      await expect(mutation.json()).resolves.toMatchObject({
        error: { code: "READ_ONLY_METHOD_NOT_ALLOWED" },
      });
    }

    const unknown = await proxy(
      request("/api/v1/not-allowed"),
      testEnv({
        SURFACE_API_ORIGIN: "https://surface.example.test",
        SURFACE_API_ACCESS_CLIENT_ID: "server-client-id",
        SURFACE_API_ACCESS_CLIENT_SECRET: "server-client-secret",
      }),
    );
    expect(unknown.status).toBe(404);
    await expect(unknown.json()).resolves.toMatchObject({
      error: { code: "API_ROUTE_NOT_FOUND" },
    });
    expect(upstreamFetch).not.toHaveBeenCalled();
  });

  it("preserves ETag and If-None-Match behavior", async () => {
    let forwardedHeaders: Headers | undefined;
    const upstreamFetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      forwardedHeaders = new Headers(init?.headers);
      return new Response(null, { status: 304, headers: { etag: '"surface-etag"' } });
    });

    const response = await proxy(
      request("/api/v1/surfaces/" + "a".repeat(64), {
        headers: { "If-None-Match": '"surface-etag"' },
      }),
      testEnv({
        SURFACE_API_ORIGIN: "https://surface.example.test",
        SURFACE_API_ACCESS_CLIENT_ID: "server-client-id",
        SURFACE_API_ACCESS_CLIENT_SECRET: "server-client-secret",
      }),
    );

    expect(response.status).toBe(304);
    expect(response.headers.get("etag")).toBe('"surface-etag"');
    expect(forwardedHeaders?.get("if-none-match")).toBe('"surface-etag"');
    expect(upstreamFetch).toHaveBeenCalledTimes(1);
  });
});
