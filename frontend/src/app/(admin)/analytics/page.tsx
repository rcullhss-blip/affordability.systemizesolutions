"use client";
import { useEffect, useState } from "react";
import { getLenderAnalytics } from "@/lib/api";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import Link from "next/link";

export default function AnalyticsPage() {
  const [lenders, setLenders] = useState<any[]>([]);

  useEffect(() => {
    getLenderAnalytics().then(setLenders).catch(() => {});
  }, []);

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
            <h3 className="text-base font-semibold text-white mb-4">Lender Table</h3>
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
        </>
      )}
    </div>
  );
}
