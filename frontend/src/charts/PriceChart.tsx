import { ColorType, createChart, LineSeries, type Time } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import { date, num } from "../lib/format";
import { useChartColors } from "./theme";

/** Cours de clôture hebdomadaires, dans la devise de cotation. Une seule série : pas de légende. */
export default function PriceChart({ points, currency, height = 220 }: {
  points: { time: string; value: number }[];
  currency: string;
  height?: number;
}) {
  const el = useRef<HTMLDivElement>(null);
  const c = useChartColors();
  const [hover, setHover] = useState<{ time: string; value: number } | null>(null);

  useEffect(() => {
    if (!el.current || !points.length) return;
    const chart = createChart(el.current, {
      height,
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: c["--surface"] }, textColor: c["--muted"],
        fontFamily: "system-ui, sans-serif", attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: c["--grid"] } },
      rightPriceScale: { borderColor: c["--axis"] },
      timeScale: { borderColor: c["--axis"] },
      crosshair: { horzLine: { visible: false, labelVisible: false }, vertLine: { color: c["--muted"], width: 1 } },
      localization: { locale: "fr-FR", priceFormatter: (p: number) => num(p, 2) },
      handleScroll: false,
      handleScale: false,
    });
    const line = chart.addSeries(LineSeries, { color: c["--series-1"], lineWidth: 2, priceLineVisible: false,
      lastValueVisible: false });
    line.setData(points.map((p) => ({ time: p.time as Time, value: p.value })));
    chart.timeScale().fitContent();
    const idx = new Map(points.map((p) => [p.time, p]));
    chart.subscribeCrosshairMove((p) => setHover(p.time ? idx.get(String(p.time)) ?? null : null));
    return () => chart.remove();
  }, [points, c, height]);

  const shown = hover ?? points[points.length - 1];
  return (
    <div>
      <div className="mb-2 text-xs text-ink-2" aria-live="polite">
        {shown && <>Clôture du vendredi {date(shown.time)} : <strong className="num text-ink">{num(shown.value, 2)} {currency}</strong></>}
      </div>
      <div ref={el} style={{ height }} role="img" aria-label={`Cours hebdomadaire sur 5 ans, en ${currency}`} />
    </div>
  );
}
