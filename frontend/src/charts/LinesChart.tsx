import { AreaSeries, ColorType, createChart, LineSeries, LineStyle, type Time } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import { date } from "../lib/format";
import { useChartColors } from "./theme";

export interface LineDef {
  name: string;
  values: (number | null)[];
  colorVar: "--series-1" | "--series-2" | "--series-3" | "--series-4" | "--text-2";
  dashed?: boolean;
  area?: boolean;
}

/**
 * Plusieurs séries sur une seule échelle (même unité). Légende toujours visible,
 * valeur de chaque série au réticule. Une valeur null crée un trou, jamais un zéro.
 */
export default function LinesChart({ dates, lines, format, height = 260 }: {
  dates: string[];
  lines: LineDef[];
  format: (v: number | null) => string;
  height?: number;
}) {
  const el = useRef<HTMLDivElement>(null);
  const c = useChartColors();
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    if (!el.current || !dates.length) return;
    const chart = createChart(el.current, {
      height,
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: c["--surface"] }, textColor: c["--muted"],
        fontFamily: "system-ui, sans-serif", attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: c["--grid"] } },
      rightPriceScale: { borderColor: c["--axis"] },
      timeScale: { borderColor: c["--axis"] },
      crosshair: { horzLine: { visible: false, labelVisible: false }, vertLine: { color: c["--muted"], width: 1 } },
      localization: { locale: "fr-FR", priceFormatter: (p: number) => format(p) },
      handleScroll: false,
      handleScale: false,
    });
    for (const l of lines) {
      const color = c[l.colorVar];
      const common = { priceLineVisible: false, lastValueVisible: false, lineWidth: 2 as const };
      const s = l.area
        ? chart.addSeries(AreaSeries, { ...common, lineColor: color, topColor: `${color}05`, bottomColor: `${color}40`,
            invertFilledArea: true })
        : chart.addSeries(LineSeries, { ...common, color, lineStyle: l.dashed ? LineStyle.Dashed : LineStyle.Solid });
      s.setData(dates.map((d, i) => (l.values[i] === null || l.values[i] === undefined
        ? { time: d as Time } : { time: d as Time, value: l.values[i] as number })));
    }
    chart.timeScale().fitContent();
    const idx = new Map(dates.map((d, i) => [d, i]));
    chart.subscribeCrosshairMove((p) => setHover(p.time ? idx.get(String(p.time)) ?? null : null));
    return () => chart.remove();
  }, [dates, lines, c, height, format]);

  const i = hover ?? dates.length - 1;
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-ink-2" aria-live="polite">
        {i >= 0 && <span className="text-muted">{date(dates[i])}</span>}
        {lines.map((l) => (
          <span key={l.name} className="flex items-center gap-1.5">
            <svg width="16" height="4" aria-hidden>
              <line x1="0" y1="2" x2="16" y2="2" stroke={c[l.colorVar]} strokeWidth="2" strokeDasharray={l.dashed ? "4 3" : undefined} />
            </svg>
            {l.name} <strong className="num text-ink">{i >= 0 ? format(l.values[i] ?? null) : ""}</strong>
          </span>
        ))}
      </div>
      <div ref={el} style={{ height }} />
    </div>
  );
}
