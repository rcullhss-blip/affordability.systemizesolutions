"use client";
import { useEffect, useState } from "react";
import { listUsers, createUser, resetUserPassword, setUserActive } from "@/lib/api";
import { getUser } from "@/lib/auth";

const FIRMS: { key: string; label: string }[] = [
  { key: "first_legal", label: "First Legal Solicitors" },
  { key: "barings", label: "Barings Law" },
  { key: "accord", label: "Accord Solicitors" },
  { key: "ryans", label: "Ryans Solicitors" },
  { key: "tr_sols", label: "TR Sols" },
  { key: "woodville", label: "Woodville" },
];

type U = { id: number; email: string; name: string | null; role: "admin" | "firm"; firm: string | null; is_active: boolean; last_login_at: string | null };

function generatePassword(): string {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789";
  const buf = new Uint32Array(16);
  crypto.getRandomValues(buf);
  return Array.from(buf, (n) => chars[n % chars.length]).join("");
}

export default function UsersPage() {
  const me = getUser();
  const [users, setUsers] = useState<U[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [form, setForm] = useState({ email: "", name: "", role: "firm" as "admin" | "firm", firm: "barings", password: generatePassword() });
  const [busy, setBusy] = useState(false);

  const load = () => listUsers().then(setUsers).catch((e) => setError(e?.response?.data?.detail || "Couldn't load users"));
  useEffect(() => { load(); }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      await createUser({ email: form.email, name: form.name || undefined, role: form.role, firm: form.role === "firm" ? form.firm : null, password: form.password });
      setNotice(`Created ${form.email}. Password: ${form.password} — share it privately; it isn't shown again.`);
      setForm({ email: "", name: "", role: "firm", firm: "barings", password: generatePassword() });
      load();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Couldn't create user");
    } finally { setBusy(false); }
  };

  const reset = async (u: U) => {
    const pw = generatePassword();
    if (!confirm(`Reset the password for ${u.email}? They will be signed out everywhere.`)) return;
    try {
      await resetUserPassword(u.id, pw);
      setNotice(`New password for ${u.email}: ${pw} — share it privately; it isn't shown again.`);
    } catch (err: any) { setError(err?.response?.data?.detail || "Couldn't reset password"); }
  };

  const toggle = async (u: U) => {
    try { await setUserActive(u.id, !u.is_active); load(); }
    catch (err: any) { setError(err?.response?.data?.detail || "Couldn't update user"); }
  };

  const firmLabel = (k: string | null) => FIRMS.find((f) => f.key === k)?.label || k || "—";

  return (
    <div className="p-6 md:p-8 space-y-8 max-w-5xl">
      <div>
        <h1 className="text-xl font-semibold">Users</h1>
        <p className="text-sm text-gray-400 mt-1">Who can sign in. Admins see everything; firm users see only their own firm's batches and the upload portal.</p>
      </div>

      {notice && <div className="rounded-lg border border-emerald-800 bg-emerald-950/40 text-emerald-200 text-sm px-4 py-3 break-all">{notice}</div>}
      {error && <div className="rounded-lg border border-red-800 bg-red-950/40 text-red-200 text-sm px-4 py-3">{error}</div>}

      <form onSubmit={submit} className="rounded-xl border border-gray-800 bg-gray-900 p-5 grid gap-4 md:grid-cols-2">
        <h2 className="md:col-span-2 text-sm font-semibold text-gray-200">Add a user</h2>
        <label className="text-sm"><span className="text-gray-400">Email</span>
          <input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className="mt-1 w-full rounded-lg bg-gray-950 border border-gray-700 px-3 py-2" /></label>
        <label className="text-sm"><span className="text-gray-400">Name (optional)</span>
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="mt-1 w-full rounded-lg bg-gray-950 border border-gray-700 px-3 py-2" /></label>
        <label className="text-sm"><span className="text-gray-400">Role</span>
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as "admin" | "firm" })} className="mt-1 w-full rounded-lg bg-gray-950 border border-gray-700 px-3 py-2">
            <option value="firm">Firm user (upload portal + own batches)</option>
            <option value="admin">Admin (Systemize staff — everything)</option>
          </select></label>
        {form.role === "firm" && (
          <label className="text-sm"><span className="text-gray-400">Firm</span>
            <select value={form.firm} onChange={(e) => setForm({ ...form, firm: e.target.value })} className="mt-1 w-full rounded-lg bg-gray-950 border border-gray-700 px-3 py-2">
              {FIRMS.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
            </select></label>
        )}
        <label className="text-sm md:col-span-2"><span className="text-gray-400">Initial password (generated — copy it before saving)</span>
          <div className="mt-1 flex gap-2">
            <input value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="flex-1 rounded-lg bg-gray-950 border border-gray-700 px-3 py-2 font-mono" />
            <button type="button" onClick={() => setForm({ ...form, password: generatePassword() })} className="rounded-lg border border-gray-700 px-3 text-sm text-gray-300 hover:bg-gray-800">Regenerate</button>
          </div></label>
        <div className="md:col-span-2">
          <button type="submit" disabled={busy} className="rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-60 px-4 py-2 text-sm font-medium">{busy ? "Creating…" : "Create user"}</button>
        </div>
      </form>

      <div className="rounded-xl border border-gray-800 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-900 text-gray-400 text-xs uppercase tracking-wider">
            <tr><th className="text-left px-4 py-3">Email</th><th className="text-left px-4 py-3">Role</th><th className="text-left px-4 py-3">Firm</th><th className="text-left px-4 py-3">Last sign-in</th><th className="text-left px-4 py-3">Status</th><th className="px-4 py-3"></th></tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {users.map((u) => (
              <tr key={u.id} className={u.is_active ? "" : "opacity-50"}>
                <td className="px-4 py-3"><div className="font-medium">{u.email}</div>{u.name && <div className="text-xs text-gray-500">{u.name}</div>}</td>
                <td className="px-4 py-3">{u.role === "admin" ? "Admin" : "Firm user"}</td>
                <td className="px-4 py-3">{u.role === "admin" ? "—" : firmLabel(u.firm)}</td>
                <td className="px-4 py-3 text-gray-400">{u.last_login_at ? new Date(u.last_login_at).toLocaleString("en-GB") : "Never"}</td>
                <td className="px-4 py-3">{u.is_active ? <span className="text-emerald-400">Active</span> : <span className="text-gray-500">Disabled</span>}</td>
                <td className="px-4 py-3 text-right whitespace-nowrap space-x-3">
                  <button onClick={() => reset(u)} className="text-blue-400 hover:underline">Reset password</button>
                  {me?.id !== u.id && (
                    <button onClick={() => toggle(u)} className={u.is_active ? "text-red-400 hover:underline" : "text-emerald-400 hover:underline"}>
                      {u.is_active ? "Disable" : "Enable"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {users.length === 0 && <tr><td colSpan={6} className="px-4 py-6 text-center text-gray-500">No users yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
