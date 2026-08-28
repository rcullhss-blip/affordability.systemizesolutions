"use client";
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getToken, getUser, setSession, clearSession, type Role, type SessionUser } from "@/lib/auth";
import { api } from "@/lib/api";

/**
 * Gate for a page tree. Renders nothing until the session is verified with the
 * API (/auth/me) — a stale or forged token never shows a page shell.
 *   role="admin"  — Systemize staff only (dashboard).
 *   role omitted  — any signed-in user (firm upload portals).
 */
export function RequireAuth({ role, children }: { role?: Role; children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState<"checking" | "ok" | "forbidden">("checking");

  useEffect(() => {
    let cancelled = false;
    const token = getToken();
    if (!token) {
      router.replace(`/login?next=${encodeURIComponent(pathname || "/")}`);
      return;
    }
    api.get("/api/v1/auth/me")
      .then(({ data }) => {
        if (cancelled) return;
        const user = data as SessionUser;
        setSession(token, user);
        if (role && user.role !== role) setState("forbidden");
        else setState("ok");
      })
      .catch(() => {
        if (cancelled) return;
        clearSession();
        router.replace(`/login?next=${encodeURIComponent(pathname || "/")}`);
      });
    return () => { cancelled = true; };
  }, [role, router, pathname]);

  if (state === "ok") return <>{children}</>;

  if (state === "forbidden") {
    const u = getUser();
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950 text-white p-6">
        <div className="max-w-sm text-center space-y-3">
          <h1 className="text-lg font-semibold">This area is for Systemize staff</h1>
          <p className="text-sm text-gray-400">
            You're signed in as {u?.email}. Your firm's upload portal is at <a className="text-blue-400 underline" href="/upload">/upload</a>.
          </p>
          <button onClick={() => { clearSession(); router.replace("/login"); }} className="text-sm text-gray-300 underline">
            Sign in as someone else
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950 text-gray-500 text-sm">
      Checking your sign-in…
    </div>
  );
}
