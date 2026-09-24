import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Fast UX gate only. The backend remains the authoritative auth check; this
 * middleware prevents unauthenticated users from receiving product pages.
 */
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (
    pathname === "/login" ||
    pathname === "/signup" ||
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
