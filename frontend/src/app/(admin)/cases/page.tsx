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

// Today's date in UK time as YYYY-MM-DD (en-CA formats dates that way).
function ukToday() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/London" }).format(new Date());
}

// A single day can hold hundreds of cases; the unfiltered view keeps the latest 50.
const DAY_LIMIT = 2000;
const ALL_LIMIT = 50;

export default function CasesPage() {
  const [cases, setCases] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>({ total: 0, in_progress: 0, outcome_sent: 0, locs_sent: 0, failed: 0 });
  const [loading, setLoading] = useState(true);
  const [day, setDay] = useState(""); // "" = all days

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      Promise.all([
        getCases(0, day ? DAY_LIMIT : ALL_LIMIT, day || undefined).then((d) => !cancelled && setCases(d)).catch(() => {}),
        getCasesSummary(day || undefined).then((d) => !cancelled && setSummary(d)).catch(() => {}),
      ]).finally(() => !cancelled && setLoading(false));

    setLoading(true);
    load();
    const iv = setInterval(load, 8000);
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, [day]);

  const today = ukToday();
  const dayLabel = day ? new Date(`${day}T12:00:00`).toLocaleDateString("en-GB") : "";
  const btn = (active: boolean) =>
    `rounded-lg border px-3 py-2 text-sm ${
      active ? "bg-blue-600/20 border-blue-600 text-blue-300" : "bg-gray-950 border-gray-700 text-gray-300 hover:border-gray-500"
    }`;

  return (
    <div className="p-8">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-white">Cases</h2>
          <p className="text-gray-500 text-sm mt-1">
            IRL cases from the PCP platform — auto-refreshes every 8s
            {day && <> · showing {dayLabel}</>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => setDay("")} className={btn(!day)}>All</button>
          <button type="button" onClick={() => setDay(today)} className={btn(day === today)}>Today</button>
          <input
            type="date"
            value={day}
            max={today}
            onChange={(e) => setDay(e.target.value)}
            aria-label="Filter cases by day"
            className="rounded-lg bg-gray-950 border border-gray-700 px-3 py-2 text-sm text-gray-300 [color-scheme:dark]"
          />
        </div>
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
          <div className="p-8 text-center text-gray-500 text-sm">{day ? `No cases on ${dayLabel}.` : "No cases yet."}</div>
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
                  <th className="px-5 py-3">{day ? "Time" : "Date"}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                {cases.map((c) => {
                  const signals = c.triage?.fired_signals?.length ?? 0;
                  // created_at is naive UTC from the API; mark it UTC so it displays in local time.
                  const created = c.created_at ? new Date(/[zZ]|[+-]\d\d:\d\d$/.test(c.created_at) ? c.created_at : `${c.created_at}Z`) : null;
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
                        {created
                          ? day
                            ? created.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" })
                            : created.toLocaleDateString("en-GB", { timeZone: "Europe/London" })
                          : "—"}
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
