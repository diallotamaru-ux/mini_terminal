import { HeatmapChart } from "echarts/charts";
import { GridComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import { useChartColors } from "./theme";

echarts.use([HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent, CanvasRenderer]);

/*
 * Palette divergente bleu (corrélation négative) / gris (0) / rouge (positive).
 * Chaque bras est une rampe d'une seule teinte, à luminosité monotone, validée
 * (validate_palette.js --ordinal) sur le fond clair et sur le fond sombre. Le bras
 * rouge reprend la luminosité et la saturation OKLCH du bras bleu (teinte 24,9°).
 * En sombre, l'intensité croît avec la clarté (le fond est sombre).
 */
const DIVERGING = {
  light: ["#0d366b", "#184f95", "#256abf", "#3987e5", "#86b6ef", "#f0efec",
          "#ea9a93", "#d75853", "#b13f3c", "#892b2a", "#621b1a"],
  dark: ["#b7d3f6", "#6da7ec", "#2a78d6", "#184f95", "#383835",
         "#892b2a", "#c74845", "#e4857e", "#f4c2be"],
};

const fr = (v: number) => v.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function CorrelationHeatmap({ labels, values }: { labels: string[]; values: (number | null)[][] }) {
  const el = useRef<HTMLDivElement>(null);
  const c = useChartColors();
  const n = labels.length;
  const size = Math.max(220, Math.min(560, n * 52 + 120));

  useEffect(() => {
    if (!el.current) return;
    const dark = document.documentElement.dataset.theme !== "light";
    const chart = echarts.init(el.current, undefined, { renderer: "canvas" });
    const data: [number, number, number | null][] = [];
    values.forEach((row, i) => row.forEach((v, j) => data.push([j, n - 1 - i, v])));
    const short = labels.map((l) => (l.length > 14 ? `${l.slice(0, 13)}…` : l));
    chart.setOption({
      animation: false,
      grid: { left: 4, right: 8, top: 4, bottom: 4, containLabel: true },
      xAxis: { type: "category", data: short, axisLabel: { color: c["--text-2"], rotate: 45, fontSize: 11 },
        axisLine: { show: false }, axisTick: { show: false }, splitArea: { show: false } },
      yAxis: { type: "category", data: [...short].reverse(), axisLabel: { color: c["--text-2"], fontSize: 11 },
        axisLine: { show: false }, axisTick: { show: false } },
      visualMap: { min: -1, max: 1, calculable: false, show: false,
        inRange: { color: dark ? DIVERGING.dark : DIVERGING.light } },
      tooltip: {
        backgroundColor: c["--surface"], borderColor: c["--grid"], textStyle: { color: c["--text"] },
        formatter: (p: { value: [number, number, number | null] }) => {
          const [j, k, v] = p.value;
          const div = document.createElement("div");
          const strong = document.createElement("strong");
          strong.textContent = v === null ? "manquant" : fr(v);
          const lbl = document.createElement("div");
          lbl.textContent = `${labels[n - 1 - k]} / ${labels[j]}`;
          lbl.style.opacity = "0.75";
          div.append(strong, lbl);
          return div;
        },
      },
      series: [{
        type: "heatmap", data,
        // 2 px d'espace entre les cases, couleur du fond.
        itemStyle: { borderColor: c["--surface"], borderWidth: 2 },
        label: { show: n <= 10, fontSize: 10, formatter: (p: { value: [number, number, number | null] }) =>
          p.value[2] === null ? "" : fr(p.value[2]),
          color: c["--text"], textBorderColor: c["--surface"], textBorderWidth: 2 },
        emphasis: { itemStyle: { borderColor: c["--text"], borderWidth: 1 } },
      }],
    });
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [labels, values, c, n]);

  const dark = typeof document !== "undefined" && document.documentElement.dataset.theme !== "light";
  const ramp = dark ? DIVERGING.dark : DIVERGING.light;
  return (
    <div>
      <div ref={el} style={{ height: size, maxWidth: size + 120 }} role="img" aria-label="Carte de chaleur des corrélations" />
      <div className="mt-2 flex items-center gap-2 text-xs text-muted" aria-hidden>
        <span>−1</span>
        <span className="h-2.5 w-40 rounded" style={{ background: `linear-gradient(to right, ${ramp.join(",")})` }} />
        <span>+1</span>
        <span className="ml-2">bleu : évoluent en sens contraire · gris : indépendantes · rouge : évoluent ensemble</span>
      </div>
    </div>
  );
}
