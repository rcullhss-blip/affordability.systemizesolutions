"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { getCases, getCasesSummary } from "@/lib/api";

function TrafficDot({ light }: { light: string | null }) {
  const color =
    light === "GREEN" ? "bg-green-400"
    : light === "AMBER" ? "bg-yellow-400"
    : light === "RED" ? "bg-red-400"
    : "bg-gray-600";
  return <span className={`inline-block w-2 h-2 rounded-full ${color} mr-2`} />;
}

function JobStatusBadge({ status }: { status: string | null }) {
  const s = status || "PENDING";
  const done = s === "COMPLETE";
  const failed = s === "FAILED";
  const cls = done
    ? "bg-green-600/20 text-green-400 border-green-700/50"
    : failed
    ? "bg-red-600/20 text-red-400 border-red-700/50"
    : "bg-blue-600/20 text-blue-400 border-blue-700/50 animate-pulse";
  return (
    <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded border ${cls}`}>
      {s}
    </span>
  );
}

function OutcomeBadge({ sent, status }: { sent: boolean; status: string }) {
  if (sent) return <span className="text-green-400 text-xs font-semibold">Sent ✓</span>;
  if (status === "OUTCOME_FAILED") return <span className="text-red-400 text-xs font-semibold">Failed</span>;
  return <span className="text-gray-500 text-xs">Pending</span>;
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl px-5 py-4">
      <p className="text-gray-500 text-xs uppercase tracking-wider">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${tone || "text-white"}`}>{value}</p>
    </div>
  );
}

export default function CasesPage() {
  const [cases, setCases] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>({ total: 0, in_progress: 0, outcome_sent: 0, locs_sent: 0, failed: 0 });
  const [loading, setLoading] = useState(true);

  const load = () =>
    Promise.all([getCases().then(setCases).catch(() => {}), getCasesSummary().then(setSummary).catch(() => {})])
      .finally(() => setLoading(false));

  useEffect(() => {
    load();
    const iv = setInterval(load, 8000);
    return () => clearInterval(iv);
  }, []);

  return (
    <div className="p-8">
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-white">Cases</h2>
        <p className="text-gray-500 text-sm mt-1">IRL cases from the PCP platform — auto-refreshes every 8s</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <Stat label="Total" value={summary.total} />
        <Stat label="In progress" value={summary.in_progress} tone="text-blue-400" />
        <Stat label="Outcome sent" value={summary.outcome_sent} tone="text-green-400" />
        <Stat label="LOCs sent" value={summary.locs_sent} tone="text-emerald-400" />
        <Stat label="Failed" value={summary.failed} tone="text-red-400" />
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-gray-500 text-sm">Loading...</div>
        ) : cases.length === 0 ? (
          <div className="p-8 text-center text-gray-500 text-sm">No cases yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-gray-500 text-left text-xs uppercase tracking-wider">
                  <th className="px-5 py-3">Lead Ref</th>
                  <th className="px-5 py-3">Client</th>
                  <th className="px-5 py-3">Source</th>
                  <th className="px-5 py-3">Signals</th>
                  <th className="px-5 py-3">Assessment</th>
                  <th className="px-5 py-3">Result</th>
                  <th className="px-5 py-3">Outcome → PCP</th>
                  <th className="px-5 py-3">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                {cases.map((c) => {
                  const signals = c.triage?.fired_signals?.length ?? 0;
                  return (
                    <tr key={c.id} className="hover:bg-gray-800/30 transition-colors">
                      <td className="px-5 py-3">
                        {c.job_id ? (
                          <Link href={`/jobs/${c.job_id}`} className="font-medium text-blue-400 hover:text-blue-300 hover:underline">
                            {c.lead_reference}
                          </Link>
                        ) : (
                          <span className="font-medium text-gray-300">{c.lead_reference}</span>
                        )}
                        <p className="text-gray-600 text-xs">#{c.id}</p>
                      </td>
                      <td className="px-5 py-3 text-gray-300">
                        {c.client_name || "—"}
                        {c.client_postcode && <span className="text-gray-600 text-xs block">{c.client_postcode}</span>}
                      </td>
                      <td className="px-5 py-3 text-gray-400 text-xs uppercase">{c.source}</td>
                      <td className="px-5 py-3 text-gray-300">{signals}</td>
                      <td className="px-5 py-3"><JobStatusBadge status={c.job_status} /></td>
                      <td className="px-5 py-3 text-gray-300">
                        <TrafficDot light={c.traffic_light} />
                        {c.traffic_light || "—"}
                      </td>
                      <td className="px-5 py-3"><OutcomeBadge sent={c.outcome_sent} status={c.status} /></td>
                      <td className="px-5 py-3 text-gray-500 text-xs">
                        {c.created_at ? new Date(c.created_at).toLocaleDateString("en-GB") : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
