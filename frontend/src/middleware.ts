import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Perimeter for EVERY page (admin dashboard and all firm upload portals).
 *
 * Incident 28 Aug 2026: the admin dashboard was reachable from a Google search
 * with no sign-in. Access is now enforced by real accounts: the API rejects any
 * request without a valid login (backend app/core/auth.py) and every page tree
 * is gated by <RequireAuth> which sends unauthenticated visitors to /login.
 * This middleware keeps the pages out of search engines and caches.
 *
 * (An HTTP Basic prompt was used as the emergency wall for the first hour; it
 * was removed once account sign-in was live because two stacked sign-ins
 * confused users. Re-enable by setting PORTAL_BASIC_AUTH="user:pass;..." —
 * the check below only runs when that env var is present.)
 */

const PORTAL_HOSTS = ["affordability.systemizesolutions.co.uk"];

function basicCredentialsOk(header: string | null, configured: string): boolean {
  if (!header || !header.startsWith("Basic ")) return false;
  let decoded = "";
  try { decoded = atob(header.slice(6)); } catch { return false; }
  return configured.split(";").map((p) => p.trim()).filter(Boolean).includes(decoded);
}

function unauthorised(): NextResponse {
  return new NextResponse("Sign in required.", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="Systemize", charset="UTF-8"',
      "X-Robots-Tag": "noindex, nofollow, noarchive",
      "Cache-Control": "no-store",
    },
  });
}

export function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname;

  // robots.txt must stay reachable so crawlers see the disallow.
  if (pathname === "/robots.txt") return NextResponse.next();

  // Optional extra wall, only when PORTAL_BASIC_AUTH is configured.
  const basic = process.env.PORTAL_BASIC_AUTH;
  if (basic && !basicCredentialsOk(request.headers.get("authorization"), basic)) {
    return unauthorised();
  }

  const host = request.headers.get("host") || "";
  let response: NextResponse;

  // Portal domain — upload only, no admin routes
  if (PORTAL_HOSTS.some((h) => host.includes(h)) && !pathname.startsWith("/upload") && !pathname.startsWith("/login")) {
    response = NextResponse.redirect(new URL("/upload", request.url));
  } else {
    response = NextResponse.next();
  }

  response.headers.set("X-Robots-Tag", "noindex, nofollow, noarchive");
  response.headers.set("Cache-Control", "private, no-store");
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon\\.ico|.*\\.png|.*\\.jpg|.*\\.jpeg|.*\\.svg|.*\\.ico|.*\\.webp).*)"],
};
