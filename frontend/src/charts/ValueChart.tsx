import { AreaSeries, ColorType, createChart, LineSeries, LineStyle, type Time } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import type { History } from "../api/types";
import { date, money } from "../lib/format";
import { useChartColors } from "./theme";

/**
 * Valeur du portefeuille et apports nets cumulés, en euros. Un seul axe :
 * les deux séries sont des montants. Une valeur manquante crée un trou
 * dans la courbe, jamais une chute à zéro.
 */
export default function ValueChart({ history, height = 300 }: { history: History; height?: number }) {
  const el = useRef<HTMLDivElement>(null);
  const c = useChartColors();
  const [hover, setHover] = useState<{ t: string; v: number | null; n: number | null } | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const chart = createChart(el.current, {
      height,
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: c["--surface"] }, textColor: c["--muted"],
        fontFamily: "system-ui, sans-serif", attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: c["--grid"] } },
      rightPriceScale: { borderColor: c["--axis"] },
      timeScale: { borderColor: c["--axis"] },
      crosshair: { horzLine: { visible: false, labelVisible: false }, vertLine: { color: c["--muted"], width: 1 } },
      localization: { locale: "fr-FR", priceFormatter: (p: number) => money(Math.round(p)) },
      handleScroll: false,
      handleScale: false,
    });
    const value = chart.addSeries(AreaSeries, {
      lineColor: c["--series-1"], lineWidth: 2,
      topColor: `${c["--series-1"]}40`, bottomColor: `${c["--series-1"]}05`,
      priceLineVisible: false, lastValueVisible: false,
    });
    const invested = chart.addSeries(LineSeries, {
      color: c["--text-2"], lineWidth: 2, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    const pts = (arr: (number | null)[]) =>
      history.dates.map((d, i) => (arr[i] === null ? { time: d as Time } : { time: d as Time, value: arr[i] as number }));
    value.setData(pts(history.value));
    invested.setData(pts(history.net_contributions));
    chart.timeScale().fitContent();

    const idx = new Map(history.dates.map((d, i) => [d, i]));
    chart.subscribeCrosshairMove((p) => {
      if (!p.time) return setHover(null);
      const i = idx.get(String(p.time));
      if (i === undefined) return setHover(null);
      setHover({ t: history.dates[i], v: history.value[i], n: history.net_contributions[i] });
    });
    return () => chart.remove();
  }, [history, c, height]);

  const last = history.dates.length - 1;
  const shown = hover ?? (last >= 0 ? { t: history.dates[last], v: history.value[last], n: history.net_contributions[last] } : null);

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-ink-2" aria-live="polite">
        {shown && <span className="text-muted">{date(shown.t)}</span>}
        <span className="flex items-center gap-1.5">
          <svg width="16" height="4" aria-hidden><line x1="0" y1="2" x2="16" y2="2" stroke={c["--series-1"]} strokeWidth="2" /></svg>
          Valeur <strong className="num text-ink">{shown ? money(shown.v) : ""}</strong>
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="16" height="4" aria-hidden><line x1="0" y1="2" x2="16" y2="2" stroke={c["--text-2"]} strokeWidth="2" strokeDasharray="4 3" /></svg>
          Apports nets cumulés <strong className="num text-ink">{shown ? money(shown.n) : ""}</strong>
        </span>
      </div>
      <div ref={el} style={{ height }} />
    </div>
  );
}
