"use client";

export function CommandCenterPreview() {
  const sessions = [
    { id: "df6139ba", classification: "charging_issue", confidence: "0.93", lang: "ar → en", status: "ALLOW" },
    { id: "a82c4f01", classification: "warranty_claim", confidence: "0.88", lang: "en", status: "APPROVAL" },
    { id: "7e3b91d5", classification: "refund_request", confidence: "0.71", lang: "ar", status: "ALLOW" },
    { id: "c29f3a88", classification: "replacement_order", confidence: "0.95", lang: "en", status: "ALLOW" },
  ];

  const badgeClass = (status: string) => {
    if (status === "ALLOW") return "bg-green-500/10 text-green-700 border border-green-500/20";
    if (status === "APPROVAL") return "bg-amber-500/10 text-amber-700 border border-amber-500/20";
    return "bg-red-500/10 text-red-700 border border-red-500/20";
  };

  return (
    <div className="w-full h-full bg-[#F8F8FC] rounded-[18px] flex flex-col overflow-hidden text-[#0A0F1C]">
      <div className="flex items-center gap-2 px-4 py-3 bg-white border-b border-[#F0EEF8]">
        <span className="w-3 h-3 rounded-full bg-[#FF453A]" />
        <span className="w-3 h-3 rounded-full bg-[#FFD60A]" />
        <span className="w-3 h-3 rounded-full bg-[#30D158]" />
        <span className="ml-3 text-[9px] font-mono tracking-[0.12em] text-[#9AA0B0] uppercase">
          Operious · Command Center · anker-pilot
        </span>
        <span className="ml-auto bg-[rgba(201,168,76,0.12)] text-[#A8882C] text-[8px] font-mono px-2 py-0.5 rounded">
          3 Active Sessions
        </span>
      </div>
      <div className="flex flex-1 overflow-hidden">
        <div className="w-48 bg-white border-r border-[#F0EEF8] py-2 flex-shrink-0">
          {[
            { label: "Operations Queue", active: true },
            { label: "Conversations", active: false },
            { label: "Approvals", active: false, badge: "2" },
            { label: "Trace Inspector", active: false },
            { label: "Fraud Monitor", active: false },
            { label: "Crisis Control", active: false, danger: true },
          ].map(({ label, active, badge, danger }) => (
            <div
              key={label}
              className={`flex items-center justify-between px-4 py-2 text-[10px] cursor-default transition-colors ${
                active
                  ? "font-semibold text-[#0A0F1C] bg-[rgba(201,168,76,0.06)] border-l-2 border-[#C9A84C]"
                  : danger
                  ? "text-[#DC2626] opacity-75"
                  : "text-[#9AA0B0]"
              }`}
            >
              {label}
              {badge && (
                <span className="bg-[rgba(201,168,76,0.15)] text-[#A8882C] text-[8px] px-1.5 py-0.5 rounded font-mono">
                  {badge}
                </span>
              )}
            </div>
          ))}
        </div>
        <div className="flex-1 p-4 flex flex-col gap-3 overflow-hidden">
          <div className="grid grid-cols-4 gap-2">
            {[
              { n: "3", l: "Active Sessions", color: "#0A0F1C" },
              { n: "47", l: "Resolved Today", color: "#1A7A3A" },
              { n: "2", l: "Pending Approval", color: "#8A6018" },
              { n: "0", l: "DLQ Items", color: "#0A0F1C" },
            ].map(({ n, l, color }) => (
              <div key={l} className="bg-white border border-[#F0EEF8] rounded-xl p-3 text-center">
                <div className="text-lg font-extrabold" style={{ color }}>{n}</div>
                <div className="text-[8px] font-mono uppercase tracking-[0.08em] text-[#9AA0B0] mt-0.5">{l}</div>
              </div>
            ))}
          </div>
          <div className="flex-1 bg-white border border-[#F0EEF8] rounded-xl overflow-hidden">
            <div className="grid grid-cols-[90px_1fr_60px_80px] gap-0 px-3 py-2 bg-[#F8F8FC] border-b border-[#F0EEF8]">
              {["Session", "Classification", "Lang", "Status"].map((h) => (
                <div key={h} className="text-[8px] font-mono uppercase tracking-[0.1em] text-[#9AA0B0]">{h}</div>
              ))}
            </div>
            {sessions.map(({ id, classification, confidence, lang, status }) => (
              <div key={id} className="grid grid-cols-[90px_1fr_60px_80px] gap-0 px-3 py-2.5 border-b border-[#F8F8FC] last:border-0">
                <div className="text-[10px] font-mono text-[#9AA0B0]">{id}</div>
                <div className="text-[11px] text-[#2A3548]">
                  {classification} <span className="text-[#9AA0B0] text-[10px]">· {confidence}</span>
                </div>
                <div className="text-[10px] font-mono text-[#2A5CAA]">{lang}</div>
                <div>
                  <span className={`text-[8px] font-mono px-2 py-0.5 rounded ${badgeClass(status)}`}>
                    {status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
