import { BarChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import { pct } from "../lib/format";
import { useChartColors } from "./theme";

echarts.use([BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

export interface PairedRow {
  label: string;
  a: number | null;          // première série (ex. poids)
  b: number | null;          // seconde série (ex. contribution au risque)
}

/**
 * Barres horizontales appariées, deux séries en parts (créneaux 1 et 2 de la palette,
 * légende toujours visible). Une seule série si `nameA` est absent.
 */
export default function PairedBars({ rows, nameA, nameB, format = (v: number) => pct(v, 1) }: {
  rows: PairedRow[];
  nameA?: string;
  nameB: string;
  format?: (v: number) => string;          // parts en % par défaut ; nombres pour des composantes
}) {
  const el = useRef<HTMLDivElement>(null);
  const c = useChartColors();
  const height = Math.max(80, rows.length * (nameA ? 38 : 26) + 40);

  useEffect(() => {
    if (!el.current || !rows.length) return;
    const chart = echarts.init(el.current, undefined, { renderer: "canvas" });
    const rev = [...rows].reverse();
    const series = [];
    if (nameA) series.push({ name: nameA, data: rev.map((r) => r.a), color: c["--series-1"] });
    series.push({ name: nameB, data: rev.map((r) => r.b), color: nameA ? c["--series-2"] : c["--series-1"] });
    chart.setOption({
      animation: false,
      legend: nameA ? { top: 0, left: 0, textStyle: { color: c["--text-2"] }, itemWidth: 12, itemHeight: 8 } : undefined,
      grid: { left: 4, right: 60, top: nameA ? 28 : 4, bottom: 4, containLabel: true },
      xAxis: { type: "value", show: false },
      yAxis: { type: "category", data: rev.map((r) => r.label), axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: c["--text-2"], fontSize: 12, width: 150, overflow: "truncate" } },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: c["--surface"],
        borderColor: c["--grid"], textStyle: { color: c["--text"] },
        valueFormatter: (v: number | null) => (v === null ? "manquant" : format(v)) },
      series: series.map((s) => ({
        type: "bar", name: s.name, data: s.data, barWidth: 10, barGap: "20%",
        itemStyle: { color: s.color, borderRadius: 3 },
        label: { show: true, position: "right", color: c["--text-2"], fontSize: 11,
          formatter: (p: { value: number | null }) => (p.value === null ? "" : format(p.value)) },
      })),
    });
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [rows, nameA, nameB, c, format]);

  return <div ref={el} style={{ height }} role="img" aria-label={nameA ? `${nameA} et ${nameB}` : nameB} />;
}
