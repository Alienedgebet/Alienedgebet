# AlienEdge — Mobile Pass Checklist (2026-10-12)

Status of the automated pass (code review) + the manual device checklist to
run before announcing to the first 100 users.

## Automated pass — VERIFIED in code

| Check | Result |
|---|---|
| Viewport meta (`width=device-width, initial-scale=1`) | ✅ present (Next default, verified in served HTML) |
| Tables on small screens | ✅ `overflow-x-auto` on the Table wrapper — wide pick boards scroll, never clip (`components/ui/table.tsx`) |
| Sidebar on small screens | ✅ off-canvas (`-translate-x-full`) with dim overlay, hamburger opens it (`Sidebar.tsx`), overlay is `md:hidden` |
| App shell margins | ✅ sidebar/right-panel margins only at `md:` and up; mobile gets full width |
| iOS input zoom | ✅ FIXED — auth inputs were `.92rem` (14.7px); now forced to 16px ≤640px (login, signup, forgot/reset password) |
| Auth pages | ✅ existing `@media (max-width: 480px)` block (smaller hero, tighter paddings) |
| New public pages (landing, support, legal, reset) | ✅ written mobile-first: `sm:`/`lg:` breakpoints, `flex-wrap`, `grid-cols-1→2/3`, no fixed widths |
| Public pages vs app chrome | ✅ FIXED — `lib/public-paths.ts` is the single list; AuthGate skips the redirect AND AppShell skips sidebar/topbar/right-panel for those routes |
| PWA installability | ✅ `manifest.webmanifest`, icon-192/512, apple-touch-icon, `apple-mobile-web-app-capable`, theme-color `#060912` |
| Tap targets | ⚠️ TopBar icon buttons are 32×32 (usable but under the 44×44 guideline) — noted, not blocking |
| Safe-area (notch in standalone PWA) | ⚠️ `viewport-fit=cover` deliberately NOT enabled — default viewport containment is safer than cover-without-inset-padding |

## Manual device checklist (before the 100-user sendout)

On a real iPhone (Safari) and a real Android (Chrome):

1. Visit `https://www.alienedge.tech` — hero readable without zooming; buttons tappable.
2. Create an account — inputs do NOT zoom on focus; keyboard does not cover the button.
3. Sign in → dashboard renders; sidebar opens/closes via hamburger.
4. Win page: tables scroll horizontally by swiping; nothing clipped.
5. Change the date — loading skeletons show, no layout jump.
6. Alerts page: push prompt appears; grant/deny both handled.
7. Log out → forgot-password → reset link flow end-to-end on the phone.
8. Add to Home Screen (PWA) — opens standalone with correct name/icon.
9. Live page during a match — live rows update, no jank.
10. Rotate to landscape — no broken layout.

If any step fails, photograph the screen and fix before sendout.
