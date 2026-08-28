import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Sign-in wall for EVERY page (admin dashboard and all firm upload portals).
 *
 * Incident 28 Aug 2026: the admin dashboard was reachable from a Google search
 * with no sign-in. This middleware requires HTTP Basic credentials on every
 * request and marks every response noindex, so nothing is browsable or
 * indexable without a password. Per-user logins with API-side enforcement are
 * layered on top of this (app/login + backend /auth); this wall stays as the
 * outer perimeter.
 *
 * Credentials: PORTAL_BASIC_AUTH env var, "user:password;user2:password2".
 * If the env var is not set, the SHA-256 credential hashes below apply
 * (emergency defaults — rotate via the env var).
 */

const PORTAL_HOSTS = ["affordability.systemizesolutions.co.uk"];

// sha256("user:password") — emergency defaults, overridden by PORTAL_BASIC_AUTH.
const DEFAULT_CREDENTIAL_HASHES = new Set([
  "2a0beb48645aaf45a3c3f305d0f3bd9baeafad750af865b174849a78a6ddeea7", // admin
  "61886ce591f5e3b825c958ef49bad43668c4837b30b41454dc675bf46c16842e", // portal
]);

async function sha256Hex(s: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function credentialsOk(header: string | null): Promise<boolean> {
  if (!header || !header.startsWith("Basic ")) return false;
  let decoded = "";
  try { decoded = atob(header.slice(6)); } catch { return false; }
  if (!decoded.includes(":")) return false;

  const configured = process.env.PORTAL_BASIC_AUTH;
  if (configured) {
    return configured.split(";").map((p) => p.trim()).filter(Boolean).includes(decoded);
  }
  return DEFAULT_CREDENTIAL_HASHES.has(await sha256Hex(decoded));
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

export async function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname;

  // robots.txt must stay reachable so crawlers see the disallow.
  if (pathname === "/robots.txt") return NextResponse.next();

  if (!(await credentialsOk(request.headers.get("authorization")))) {
    return unauthorised();
  }

  const host = request.headers.get("host") || "";
  let response: NextResponse;

  // Portal domain — upload only, no admin routes
  if (PORTAL_HOSTS.some((h) => host.includes(h)) && !pathname.startsWith("/upload")) {
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
