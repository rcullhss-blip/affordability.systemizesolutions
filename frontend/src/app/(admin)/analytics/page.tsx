"use client";
import { useEffect, useState } from "react";
import { getLenderAnalytics, getAnalyticsSummary, getRiskIndicators } from "@/lib/api";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import Link from "next/link";

const INDICATOR_LABELS: Record<string, string> = {
  DEBT_STACKING: "Debt stacking — multiple concurrent facilities",
  ACTIVE_ADVERSE_AT_LENDING: "Adverse markers on file at time of lending",
  HIGH_UTILISATION: "High credit utilisation (>90%)",
  ELEVATED_UTILISATION: "Elevated credit utilisation (75–90%)",
  REPEAT_BORROWING: "Repeat borrowing with the same lender",
  DEFAULT_REGISTERED: "Default registered by the lender",
  REPEATED_MISSED_PAYMENTS: "Repeated missed payments",
  MISSED_PAYMENT: "Missed payment marker(s)",
  MULTIPLE_HARD_SEARCHES: "Multiple hard searches before lending",
  HARD_SEARCHES: "Hard searches before lending",
  PAYDAY_LOAN: "Payday / high-cost short-term credit",
  ACTIVE_CCJ: "Active County Court Judgment",
  MULTIPLE_CCJS: "Multiple CCJs",
  PUBLIC_RECORD_INSOLVENCY: "Insolvency (IVA / bankruptcy)",
  POSSIBLE_DEBT_PURCHASER: "Possible debt purchaser (manual review)",
  OUTSIDE_LIMITATION: "Outside 6-year limitation period",
};

export default function AnalyticsPage() {
  const [lenders, setLenders] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [indicators, setIndicators] = useState<any[]>([]);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    getLenderAnalytics().then(setLenders).catch(() => {});
  }, []);

  function toggleAdvanced() {
    const next = !showAdvanced;
    setShowAdvanced(next);
    if (next && !summary) {
      getAnalyticsSummary().then(setSummary).catch(() => {});
      getRiskIndicators().then(setIndicators).catch(() => {});
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 p-8">
      <div className="mb-6">
        <Link href="/" className="text-gray-500 hover:text-white text-sm">← Dashboard</Link>
        <h2 className="text-2xl font-bold text-white mt-2">Lender Analytics</h2>
        <p className="text-gray-500 text-sm">Intelligence across all processed reports</p>
      </div>

      {lenders.length > 0 && (
        <>
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 mb-6">
            <h3 className="text-base font-semibold text-white mb-4">Claim Rate by Lender (Top 20)</h3>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={lenders} margin={{ top: 5, right: 10, left: 0, bottom: 60 }}>
                <XAxis dataKey="lender" tick={{ fill: "#6b7280", fontSize: 11 }} angle={-45} textAnchor="end" />
                <YAxis tick={{ fill: "#6b7280", fontSize: 11 }} unit="%" />
                <Tooltip
                  contentStyle={{ background: "#111827", border: "1px solid #374151", borderRadius: 8 }}
                  labelStyle={{ color: "#fff" }}
                />
                <Bar dataKey="claim_rate_pct" name="Claim Rate %" radius={[4, 4, 0, 0]}>
                  {lenders.map((entry, i) => (
                    <Cell
                      key={i}
                      fill={entry.claim_rate_pct >= 60 ? "#22c55e" : entry.claim_rate_pct >= 30 ? "#f59e0b" : "#ef4444"}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h3 className="text-base font-semibold text-white mb-2">Lender Table</h3>
            <div className="text-xs text-gray-500 mb-4 grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-1">
              <span><b className="text-gray-300">Total</b> — number of times this lender appeared across all reports</span>
              <span><b className="text-green-400">Green</b>/<b className="text-yellow-400">Amber</b>/<b className="text-red-400">Red</b> — claim strength: Strong / Borderline / Weak</span>
              <span><b className="text-gray-300">Claim Rate</b> — % of appearances that are strong (Green) claims</span>
              <span><b className="text-gray-300">Avg Score</b> — average claim-strength score (0–100)</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-800 text-gray-500 text-left">
                    <th className="pb-3 pr-4">Lender</th>
                    <th className="pb-3 pr-4">Total</th>
                    <th className="pb-3 pr-4 text-green-400">Green</th>
                    <th className="pb-3 pr-4 text-yellow-400">Amber</th>
                    <th className="pb-3 pr-4 text-red-400">Red</th>
                    <th className="pb-3 pr-4">Claim Rate</th>
                    <th className="pb-3">Avg Score</th>
                  </tr>
                </thead>
                <tbody>
                  {lenders.map((l, i) => (
                    <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                      <td className="py-3 pr-4 font-medium text-white">{l.lender}</td>
                      <td className="py-3 pr-4 text-gray-300">{l.total_accounts}</td>
                      <td className="py-3 pr-4 text-green-400">{l.green}</td>
                      <td className="py-3 pr-4 text-yellow-400">{l.amber}</td>
                      <td className="py-3 pr-4 text-red-400">{l.red}</td>
                      <td className="py-3 pr-4">
                        <span className={`font-semibold ${l.claim_rate_pct >= 60 ? "text-green-400" : l.claim_rate_pct >= 30 ? "text-yellow-400" : "text-red-400"}`}>
                          {l.claim_rate_pct}%
                        </span>
                      </td>
                      <td className="py-3 text-gray-300">{l.avg_claim_score}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="mt-6 text-center">
            <button
              onClick={toggleAdvanced}
              className="px-5 py-2.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-white text-sm font-medium border border-gray-700"
            >
              {showAdvanced ? "Hide Advanced Analytics ▲" : "Show Advanced Analytics ▼"}
            </button>
          </div>

          {showAdvanced && (
            <div className="mt-6 space-y-6">
              {summary && (
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
                  {[
                    ["Reports assessed", summary.total_assessments, "text-white"],
                    ["Strong (Green)", summary.green, "text-green-400"],
                    ["Borderline (Amber)", summary.amber, "text-yellow-400"],
                    ["Weak (Red)", summary.red, "text-red-400"],
                    ["LOCs generated", summary.locs_generated, "text-white"],
                  ].map(([label, val, cls]: any, i: number) => (
                    <div key={i} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
                      <div className={`text-2xl font-bold ${cls}`}>{Number(val || 0).toLocaleString()}</div>
                      <div className="text-xs text-gray-500 mt-1">{label}</div>
                    </div>
                  ))}
                </div>
              )}

              <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
                <h3 className="text-base font-semibold text-white mb-1">Most Common Affordability Indicators</h3>
                <p className="text-xs text-gray-500 mb-4">
                  Which issues are driving claims across all reports — the evidence appearing most often on file.
                </p>
                <div className="space-y-2">
                  {indicators.map((ind, i) => {
                    const max = indicators[0]?.count || 1;
                    const pct = Math.max(2, Math.round((ind.count / max) * 100));
                    return (
                      <div key={i} className="flex items-center gap-3">
                        <div className="w-72 shrink-0 text-xs text-gray-300 truncate" title={INDICATOR_LABELS[ind.indicator] || ind.indicator}>
                          {INDICATOR_LABELS[ind.indicator] || ind.indicator}
                        </div>
                        <div className="flex-1 bg-gray-800 rounded h-4 overflow-hidden">
                          <div className="h-full bg-blue-600" style={{ width: `${pct}%` }} />
                        </div>
                        <div className="w-20 text-right text-xs text-gray-400">{Number(ind.count).toLocaleString()}</div>
                      </div>
                    );
                  })}
                  {indicators.length === 0 && <p className="text-xs text-gray-600">Loading…</p>}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
