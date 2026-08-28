"use client";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { setSession, type SessionUser } from "@/lib/auth";

const FIRM = process.env.NEXT_PUBLIC_FIRM || "";
const FIRM_NAME: Record<string, string> = {
  barings: "Barings Law", accord: "Accord Solicitors", first_legal: "First Legal Solicitors", ryans: "Ryans Solicitors",
};

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const { data } = await api.post("/api/v1/auth/login", { email, password });
      const user = data.user as SessionUser;
      setSession(data.token, user);
      const next = params.get("next");
      // Firm users land on their upload portal; admins on the dashboard.
      router.replace(next && next !== "/login" ? next : user.role === "admin" ? "/" : "/upload");
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Couldn't sign in. Check your email and password.");
    } finally {
      setBusy(false);
    }
  };

  const title = FIRM && FIRM_NAME[FIRM] ? `${FIRM_NAME[FIRM]} — Secure Portal` : "Systemize";

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950 text-white px-4">
      <form onSubmit={submit} className="w-full max-w-sm bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-5">
        <div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo-white.png" alt="Systemize" style={{ height: 30, width: "auto" }} />
          <h1 className="mt-4 text-lg font-semibold">{title}</h1>
          <p className="text-sm text-gray-400 mt-1">Sign in to continue. Access is restricted to authorised users.</p>
        </div>
        <label className="block text-sm">
          <span className="text-gray-300">Email</span>
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-lg bg-gray-950 border border-gray-700 px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </label>
        <label className="block text-sm">
          <span className="text-gray-300">Password</span>
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-lg bg-gray-950 border border-gray-700 px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </label>
        {error && <p className="text-sm text-red-400" role="alert">{error}</p>}
        <button type="submit" disabled={busy}
          className="w-full rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-60 px-4 py-2 text-sm font-medium transition-colors">
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="text-xs text-gray-600">Forgotten your password? Ask your Systemize administrator to reset it.</p>
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
