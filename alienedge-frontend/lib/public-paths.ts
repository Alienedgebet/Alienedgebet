/**
 * Single source of truth for routes that are reachable WITHOUT a session.
 * Used by BOTH the auth gate (so visitors are not bounced to /login) and the
 * app shell (so these pages never render inside the sidebar/topbar chrome —
 * they carry their own headers). Add new public pages here, nowhere else.
 */
export const PUBLIC_PATHS = [
  "/",                       // landing page (item 7 of the launch plan)
  "/login",
  "/signup",
  "/forgot-password",        // password reset flow
  "/reset-password",
  "/support",                // contact + FAQ (email + WhatsApp)
  "/terms",
  "/privacy",
  "/responsible-gambling",
  "/cookies",
] as const;

const PUBLIC_PATH_SET: ReadonlySet<string> = new Set(PUBLIC_PATHS);

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATH_SET.has(pathname);
}
