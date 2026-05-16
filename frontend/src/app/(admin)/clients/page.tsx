"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { getClients } from "@/lib/api";

export default function ClientsPage() {
  const [clients, setClients] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    getClients()
      .then(setClients)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const filtered = clients.filter(
    (c) =>
      !search ||
      c.name?.toLowerCase().includes(search.toLowerCase()) ||
      c.matter_ref?.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="p-8">
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-white">Clients</h2>
        <p className="text-gray-500 text-sm mt-1">{clients.length} client record(s) processed</p>
      </div>

      <div className="mb-4">
        <input
          type="text"
          placeholder="Search by name or matter ref..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full max-w-md bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500 transition-colors"
        />
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-gray-500 text-sm">Loading...</div>
        ) : filtered.length === 0 ? (
          <div className="p-8 text-center text-gray-500 text-sm">
            {search ? "No clients match your search." : "No clients yet. Process a credit report to get started."}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-gray-500 text-left text-xs uppercase tracking-wider">
                  <th className="px-5 py-3">Client Name</th>
                  <th className="px-5 py-3">Matter Ref</th>
                  <th className="px-5 py-3">Date of Birth</th>
                  <th className="px-5 py-3">Added</th>
                  <th className="px-5 py-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                {filtered.map((c) => (
                  <tr key={c.id} className="hover:bg-gray-800/30 transition-colors">
                    <td className="px-5 py-3">
                      <Link
                        href={`/clients/${encodeURIComponent(c.matter_ref)}`}
                        className="font-medium text-white hover:text-blue-400 transition-colors"
                      >
                        {c.name}
                      </Link>
                    </td>
                    <td className="px-5 py-3 font-mono text-xs text-gray-400">{c.matter_ref}</td>
                    <td className="px-5 py-3 text-gray-400">
                      {c.dob ? new Date(c.dob).toLocaleDateString("en-GB") : "—"}
                    </td>
                    <td className="px-5 py-3 text-gray-500 text-xs">
                      {c.created_at ? new Date(c.created_at).toLocaleDateString("en-GB") : "—"}
                    </td>
                    <td className="px-5 py-3">
                      <Link
                        href={`/clients/${encodeURIComponent(c.matter_ref)}`}
                        className="text-xs text-blue-400 hover:text-blue-300 font-medium transition-colors"
                      >
                        View →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
