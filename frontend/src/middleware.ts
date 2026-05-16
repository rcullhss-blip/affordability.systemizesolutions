import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PORTAL_HOSTS = ["affordability.systemizesolutions.co.uk"];

export function middleware(request: NextRequest) {
  const host = request.headers.get("host") || "";
  const pathname = request.nextUrl.pathname;

  // Portal domain — First Legal upload only, no admin routes
  if (PORTAL_HOSTS.some((h) => host.includes(h))) {
    if (!pathname.startsWith("/upload")) {
      return NextResponse.redirect(new URL("/upload", request.url));
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon\\.ico|.*\\.png|.*\\.jpg|.*\\.jpeg|.*\\.svg|.*\\.ico|.*\\.webp).*)"],
};
