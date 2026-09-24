import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

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
  const upstream = await fetch(target, {
    method,
    headers,
    body,
    cache: "no-store",
    redirect: "manual",
  });

  const responseHeaders = new Headers();
  for (const name of ["content-type", "cache-control", "etag", "vary"]) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  const setCookie = upstream.headers.get("set-cookie");
  if (setCookie) responseHeaders.set("set-cookie", setCookie);
  return new Response(upstream.body, {
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
