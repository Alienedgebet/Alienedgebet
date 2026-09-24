import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const UPSTREAM_TIMEOUT_MS = 6_000;

/**
 * Same-origin browser-to-backend proxy. BACKEND_API_URL is server-only and is
 * never read by client components. Prediction routes and response shapes are
 * forwarded unchanged.
 */
async function proxy(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = await context.params;
  const configuredBackend = process.env.BACKEND_API_URL;
  const backend = configuredBackend || (process.env.NODE_ENV === "production" ? "https://api.alienedge.tech" : "http://127.0.0.1:8000");
  const target = path.length === 1 && path[0] === "health"
    ? `${backend.replace(/\/$/, "")}/health${request.nextUrl.search}`
    : `${backend.replace(/\/$/, "")}/api/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const accept = request.headers.get("accept");
  if (contentType) headers.set("content-type", contentType);
  if (accept) headers.set("accept", accept);
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("cookie", cookie);
  const authorization = request.headers.get("authorization");
  if (authorization) headers.set("authorization", authorization);

  const method = request.method.toUpperCase();
  const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();
  const controller = new AbortController();
  const abortFromRequest = () => controller.abort();
  if (request.signal.aborted) controller.abort();
  else request.signal.addEventListener("abort", abortFromRequest, { once: true });
  const timeout = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);
  let upstream: Response;
  let responseBody: ArrayBuffer | undefined;
  try {
    upstream = await fetch(target, {
      method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
      signal: controller.signal,
    });
    // Auth responses are tiny; buffer them so the deadline covers the complete
    // response and a stalled body cannot leave the client waiting.
    if (path[0] === "auth") responseBody = await upstream.arrayBuffer();
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "AbortError";
    return new Response(
      JSON.stringify({
        detail: timedOut
          ? "The service took too long to respond. Please try again."
          : "The service is temporarily unavailable. Please try again.",
      }),
      {
        status: timedOut ? 504 : 502,
        headers: { "content-type": "application/json", "cache-control": "no-store" },
      },
    );
  } finally {
    clearTimeout(timeout);
    request.signal.removeEventListener("abort", abortFromRequest);
  }

  const responseHeaders = new Headers();
  for (const name of ["content-type", "cache-control", "etag", "vary"]) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }

  // Node/undici exposes Set-Cookie as separate values. Preserve each value so
  // a session cookie is not lost or malformed when the response crosses the
  // Vercel proxy boundary. Keep the single-header fallback for older runtimes.
  const upstreamHeaders = upstream.headers as Headers & { getSetCookie?: () => string[] };
  const setCookies = upstreamHeaders.getSetCookie?.() ?? [];
  if (setCookies.length > 0) {
    for (const cookie of setCookies) responseHeaders.append("set-cookie", cookie);
  } else {
    const setCookie = upstream.headers.get("set-cookie");
    if (setCookie) responseHeaders.set("set-cookie", setCookie);
  }

  return new Response(responseBody ?? upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
