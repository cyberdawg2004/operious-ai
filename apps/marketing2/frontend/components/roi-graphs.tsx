"use client";

import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { NumberTicker } from "@/components/ui/number-ticker";

const costData = [
  { tier: "Tier 1 BPO", traditional: 18000, operious: 7500 },
  { tier: "Tier 1+2 BPO", traditional: 32000, operious: 9500 },
  { tier: "Enterprise BPO", traditional: 48000, operious: 10000 },
];

const resolutionData = [
  { category: "Password / Access", human: 8, operious: 1.2 },
  { category: "Shipping Inquiry", human: 12, operious: 0.9 },
  { category: "Warranty Claim", human: 18, operious: 3.2 },
  { category: "Refund Request", human: 14, operious: 2.1 },
  { category: "Technical Issue", human: 22, operious: 4.8 },
  { category: "Language Support", human: 26, operious: 3.5 },
];

const escalationData = [
  { week: "Week 1", rate: 22 },
  { week: "Week 2", rate: 18 },
  { week: "Week 3", rate: 14 },
  { week: "Week 4", rate: 11 },
  { week: "Week 6", rate: 8 },
  { week: "Week 8", rate: 6 },
];

const languageRows = [
  ["Arabic (ar)", "97%", "Native", true, true],
  ["English (en)", "99%", "-", true, true],
  ["Indonesian", "94%", "Native", true, true],
  ["Spanish", "96%", "Native", true, true],
  ["French", "95%", "Native", true, true],
  ["Chinese (ZH)", "93%", "Native", true, true],
] as const;

function ChartFrame({
  title,
  children,
  annotation,
}: {
  title: string;
  children: React.ReactNode;
  annotation?: string;
}) {
  return (
    <article className="rounded-md border border-[#1A2744] bg-[#0B1120] p-5">
      <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <h3 className="text-[18px] font-semibold text-[#D8E4F4]">{title}</h3>
        {annotation && (
          <span className="rounded border border-[#C9A84C]/25 bg-[#C9A84C]/10 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-[#C9A84C]">
            {annotation}
          </span>
        )}
      </div>
      {children}
    </article>
  );
}

function CheckDot() {
  return (
    <span
      aria-label="Included"
      className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-[#2A5CAA] text-[11px] font-bold text-white"
    >
      ✓
    </span>
  );
}

export function RoiGraphs() {
  const [chartsReady, setChartsReady] = useState(false);

  useEffect(() => {
    const frameId = window.requestAnimationFrame(() => setChartsReady(true));

    return () => window.cancelAnimationFrame(frameId);
  }, []);

  return (
    <section className="bg-[#05080F] px-4 py-20 text-[#D8E4F4] sm:px-8 sm:py-24 lg:px-16">
      <div className="mx-auto max-w-[1280px]">
        <p
          className="text-[10px] uppercase tracking-[0.18em] text-[#C9A84C]"
          style={{ fontFamily: "var(--font-ibm-plex-mono)" }}
        >
          ROI and risk reduction
        </p>
        <div className="mt-5 grid gap-5 lg:grid-cols-[0.9fr_1.1fr] lg:items-end">
          <h2
            className="max-w-[780px] text-[38px] font-bold leading-tight sm:text-[54px]"
            style={{ fontFamily: "var(--font-cormorant-sc)" }}
          >
            The operational and financial case for governed AI operations.
          </h2>
          <p className="text-[15px] leading-relaxed text-[#7A90B4]">
            Figures below represent representative enterprise deployment scenarios.
            Actual outcomes depend on workflow complexity, volume, and configuration.
          </p>
        </div>

        <div className="mt-10 grid gap-5 xl:grid-cols-2">
          <ChartFrame
            title="Monthly operational cost per 3,000 daily contacts"
            annotation="58%-79% cost reduction"
          >
            <div className="h-[320px]">
              {chartsReady ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={costData} margin={{ top: 10, right: 10, left: 0, bottom: 10 }}>
                  <CartesianGrid stroke="#1A2744" vertical={false} />
                  <XAxis dataKey="tier" tick={{ fill: "#7A90B4", fontSize: 12 }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fill: "#7A90B4", fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={(value) => `$${Number(value) / 1000}k`} />
                  <Tooltip
                    cursor={{ fill: "rgba(42,92,170,0.12)" }}
                    contentStyle={{
                      background: "#05080F",
                      border: "1px solid #1A2744",
                      borderRadius: 8,
                      color: "#D8E4F4",
                    }}
                    formatter={(value, name) => [`$${Number(value).toLocaleString()}`, name === "traditional" ? "Traditional BPO" : "Operious"]}
                  />
                  <Bar dataKey="traditional" name="Traditional BPO" fill="#64748B" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="operious" name="Operious" fill="#2A5CAA" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
              ) : (
                <div className="h-full rounded-md border border-[#1A2744] bg-[#05080F]" />
              )}
            </div>
            <p className="mt-3 text-[12px] text-[#7A90B4]">
              Representative scenario data. Not a guaranteed outcome.
            </p>
          </ChartFrame>

          <ChartFrame title="Operational decision auditability">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="rounded-md border border-[#1A2744] bg-[#05080F] p-5">
                <p className="text-[12px] uppercase tracking-[0.16em] text-[#7A90B4]">
                  Traditional Operations
                </p>
                <div className="mt-5 text-[56px] font-bold text-[#64748B]">
                  <NumberTicker value={12} />%
                </div>
                <p className="mt-3 text-[15px] text-[#D8E4F4]">
                  of decisions produce structured audit evidence
                </p>
                <p className="mt-2 text-[13px] leading-relaxed text-[#7A90B4]">
                  Primarily escalations and compliance reviews.
                </p>
              </div>
              <div className="rounded-md border border-[#2A5CAA]/40 bg-[#05080F] p-5 shadow-[0_0_48px_rgba(42,92,170,0.12)]">
                <p className="text-[12px] uppercase tracking-[0.16em] text-[#C9A84C]">
                  Operious
                </p>
                <div className="mt-5 text-[56px] font-bold text-[#2A5CAA]">
                  <NumberTicker value={100} />%
                </div>
                <p className="mt-3 text-[15px] text-[#D8E4F4]">
                  of decisions produce structured audit evidence
                </p>
                <p className="mt-2 text-[13px] leading-relaxed text-[#7A90B4]">
                  By architecture, not by policy.
                </p>
              </div>
            </div>
            <p className="mt-3 text-[12px] text-[#7A90B4]">
              Representative enterprise scenario data.
            </p>
          </ChartFrame>

          <ChartFrame title="Average resolution time by contact category">
            <div className="h-[330px]">
              {chartsReady ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={resolutionData} margin={{ top: 10, right: 10, left: -8, bottom: 50 }}>
                  <CartesianGrid stroke="#1A2744" vertical={false} />
                  <XAxis dataKey="category" angle={-24} textAnchor="end" interval={0} tick={{ fill: "#7A90B4", fontSize: 11 }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fill: "#7A90B4", fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={(value) => `${value}m`} />
                  <Tooltip
                    contentStyle={{
                      background: "#05080F",
                      border: "1px solid #1A2744",
                      borderRadius: 8,
                      color: "#D8E4F4",
                    }}
                    formatter={(value, name) => [`${Number(value)} min`, name === "human" ? "Human Agent" : "Operious"]}
                  />
                  <Line type="monotone" dataKey="human" stroke="#64748B" strokeWidth={2} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="operious" stroke="#2A5CAA" strokeWidth={2.5} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
              ) : (
                <div className="h-full rounded-md border border-[#1A2744] bg-[#05080F]" />
              )}
            </div>
            <p className="mt-3 text-[12px] text-[#7A90B4]">
              Representative scenario data. Not a guaranteed outcome.
            </p>
          </ChartFrame>

          <ChartFrame
            title="Escalation rate over 60-day pilot deployment"
            annotation="Policy calibration"
          >
            <div className="h-[330px]">
              {chartsReady ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={escalationData} margin={{ top: 10, right: 10, left: -8, bottom: 10 }}>
                  <defs>
                    <linearGradient id="escalationFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#2A5CAA" stopOpacity={0.24} />
                      <stop offset="100%" stopColor="#2A5CAA" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#1A2744" vertical={false} />
                  <XAxis dataKey="week" tick={{ fill: "#7A90B4", fontSize: 12 }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fill: "#7A90B4", fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={(value) => `${value}%`} />
                  <Tooltip
                    contentStyle={{
                      background: "#05080F",
                      border: "1px solid #1A2744",
                      borderRadius: 8,
                      color: "#D8E4F4",
                    }}
                    formatter={(value) => [`${Number(value)}%`, "Escalation rate"]}
                  />
                  <Area type="monotone" dataKey="rate" stroke="#2A5CAA" strokeWidth={2.5} fill="url(#escalationFill)" />
                </AreaChart>
              </ResponsiveContainer>
              ) : (
                <div className="h-full rounded-md border border-[#1A2744] bg-[#05080F]" />
              )}
            </div>
            <p className="mt-3 text-[12px] text-[#7A90B4]">
              Escalation reduction reflects policy calibration over the pilot period,
              not a guaranteed outcome. Representative deployment data.
            </p>
          </ChartFrame>
        </div>

        <ChartFrame title="Operational language coverage" annotation="Representative matrix">
          <div className="mt-2 overflow-x-auto">
            <table className="min-w-[720px] w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-[#1A2744] text-[11px] uppercase tracking-[0.14em] text-[#7A90B4]">
                  <th className="py-3 pr-4">Language</th>
                  <th className="py-3 pr-4">Detection</th>
                  <th className="py-3 pr-4">Translation</th>
                  <th className="py-3 pr-4">Voice</th>
                  <th className="py-3">Chat</th>
                </tr>
              </thead>
              <tbody>
                {languageRows.map(([language, detection, translation, voice, chat]) => (
                  <tr key={language} className="border-b border-[#1A2744]/70 text-[14px] text-[#D8E4F4] last:border-b-0">
                    <td className="py-4 pr-4 font-medium">{language}</td>
                    <td className="py-4 pr-4"><CheckDot /> <span className="ml-2">{detection}</span></td>
                    <td className="py-4 pr-4">{translation === "-" ? <span className="text-[#7A90B4]">-</span> : <><CheckDot /> <span className="ml-2">{translation}</span></>}</td>
                    <td className="py-4 pr-4">{voice && <CheckDot />}</td>
                    <td className="py-4">{chat && <CheckDot />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-[12px] text-[#7A90B4]">
            Representative language coverage matrix for enterprise deployment planning.
          </p>
        </ChartFrame>
      </div>
    </section>
  );
}
