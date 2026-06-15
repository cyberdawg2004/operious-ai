import { cn } from "@/lib/utils";

export type ChartDatum = {
  label: string;
  value: number;
  color?: string;
};

/**
 * Minimal inline-SVG bar chart for small operational datasets (e.g. ticket
 * volume by day). No charting library dependency — colors come from the
 * design-system chart tokens by default.
 */
export function BarChart({
  data,
  height = 160,
  className,
  formatValue = (value) => String(value),
}: {
  data: ChartDatum[];
  height?: number;
  className?: string;
  formatValue?: (value: number) => string;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));

  return (
    <div className={cn("flex items-end gap-2.5", className)} style={{ height }}>
      {data.map((datum) => {
        const barHeightPct = Math.max(2, (datum.value / max) * 100);
        return (
          <div key={datum.label} className="flex flex-1 flex-col items-center gap-2">
            <span className="text-meta tabular">{formatValue(datum.value)}</span>
            <div className="flex w-full flex-1 items-end">
              <div
                className="w-full rounded-md transition-all"
                style={{
                  height: `${barHeightPct}%`,
                  background: datum.color ?? "var(--chart-blue)",
                  minHeight: 4,
                }}
                role="img"
                aria-label={`${datum.label}: ${formatValue(datum.value)}`}
              />
            </div>
            <span className="text-meta truncate">{datum.label}</span>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Minimal inline-SVG donut chart for status/category breakdowns, with a
 * colored legend. Renders an empty ring when all values are zero.
 */
export function DonutChart({
  data,
  size = 132,
  thickness = 16,
  centerLabel,
  centerValue,
  className,
}: {
  data: ChartDatum[];
  size?: number;
  thickness?: number;
  centerLabel?: string;
  centerValue?: string;
  className?: string;
}) {
  const total = data.reduce((sum, d) => sum + d.value, 0);
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;

  let offset = 0;
  const segments = data.map((datum) => {
    const fraction = total > 0 ? datum.value / total : 0;
    const dash = fraction * circumference;
    const segment = {
      ...datum,
      dashArray: `${dash} ${circumference - dash}`,
      dashOffset: -offset,
    };
    offset += dash;
    return segment;
  });

  return (
    <div className={cn("flex items-center gap-5", className)}>
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="var(--surface-sunken)"
            strokeWidth={thickness}
          />
          {total > 0 &&
            segments.map((segment) => (
              <circle
                key={segment.label}
                cx={size / 2}
                cy={size / 2}
                r={radius}
                fill="none"
                stroke={segment.color ?? "var(--chart-blue)"}
                strokeWidth={thickness}
                strokeDasharray={segment.dashArray}
                strokeDashoffset={segment.dashOffset}
                transform={`rotate(-90 ${size / 2} ${size / 2})`}
                strokeLinecap="butt"
              />
            ))}
        </svg>
        {(centerValue || centerLabel) && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
            {centerValue && (
              <span className="heading-section tabular">{centerValue}</span>
            )}
            {centerLabel && <span className="text-meta">{centerLabel}</span>}
          </div>
        )}
      </div>
      <ul className="flex flex-col gap-2">
        {data.map((datum) => (
          <li key={datum.label} className="flex items-center gap-2 text-body">
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ background: datum.color ?? "var(--chart-blue)" }}
              aria-hidden
            />
            <span className="text-ink-body">{datum.label}</span>
            <span className="ml-auto pl-2 tabular text-ink-tertiary">{datum.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
