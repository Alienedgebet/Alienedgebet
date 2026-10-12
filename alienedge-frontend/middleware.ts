import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Fast UX gate only. The backend remains the authoritative auth check; this
 * middleware prevents unauthenticated users from receiving product pages.
 */
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  // Public routes (landing, legal, support, password-reset flow) must match
  // lib/public-paths.ts exactly — if this list drifts, public pages bounce
  // to /login or protected pages leak. The BACKEND auth middleware remains
  // the real security check; this is only the fast UX gate.
  if (
    pathname === "/" ||
    pathname === "/login" ||
    pathname === "/signup" ||
    pathname === "/forgot-password" ||
    pathname === "/reset-password" ||
    pathname === "/support" ||
    pathname === "/terms" ||
    pathname === "/privacy" ||
    pathname === "/responsible-gambling" ||
    pathname === "/cookies" ||
    pathname === "/sw.js" ||
    pathname === "/manifest.webmanifest" ||
    pathname.startsWith("/icons/") ||
    pathname === "/apple-touch-icon.png" ||
    pathname === "/hero-alien-mascot-login-v1-540.webp" ||
    pathname === "/hero-alien-mascot-login-v1-1024.webp" ||
    pathname.startsWith("/api/") ||
    pathname.startsWith("/_next/") ||
    pathname === "/favicon.ico"
  ) {
    return NextResponse.next();
  }
  if (!request.cookies.has("alienedge_session")) {
    const login = new URL("/login", request.url);
    login.searchParams.set("next", pathname);
    return NextResponse.redirect(login);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
