import { BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef } from "react";

import type { AllocationItem } from "../api/types";
import { MISSING, money, pct } from "../lib/format";
import { useChartColors } from "./theme";

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

/**
 * Répartition en barres horizontales, une seule teinte (une seule série :
 * pas de légende, le titre de la carte la nomme). Valeur et poids écrits en
 * clair à droite de chaque barre. Les lignes sans valeur sont listées à part.
 */
export default function AllocationBars({ items }: { items: AllocationItem[] }) {
  const el = useRef<HTMLDivElement>(null);
  const c = useChartColors();
  const known = useMemo(() => items.filter((i) => i.value_eur !== null), [items]);
  const missing = items.filter((i) => i.value_eur === null);
  const height = Math.max(60, known.length * 30 + 10);

  useEffect(() => {
    if (!el.current || !known.length) return;
    const chart = echarts.init(el.current, undefined, { renderer: "canvas" });
    const rows = [...known].reverse();                 // plus grande barre en haut
    chart.setOption({
      animation: false,
      grid: { left: 4, right: 150, top: 4, bottom: 4, containLabel: true },
      xAxis: { type: "value", show: false },
      yAxis: {
        type: "category", data: rows.map((r) => r.label),
        axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: c["--text-2"], fontSize: 12, width: 160, overflow: "truncate" },
      },
      tooltip: {
        trigger: "item",
        backgroundColor: c["--surface"], borderColor: c["--grid"], textStyle: { color: c["--text"] },
        formatter: (p: { dataIndex: number }) => {
          const r = rows[p.dataIndex];
          const div = document.createElement("div");
          const strong = document.createElement("strong");
          strong.textContent = `${money(r.value_eur)} · ${pct(r.weight, 1)}`;
          const lbl = document.createElement("div");
          lbl.textContent = r.label;
          lbl.style.opacity = "0.75";
          div.append(strong, lbl);
          return div;
        },
      },
      series: [{
        type: "bar", barWidth: 14,
        data: rows.map((r) => Number(r.value_eur)),
        itemStyle: { color: c["--series-1"], borderRadius: [0, 4, 4, 0] },
        emphasis: { itemStyle: { opacity: 0.85 } },
        label: {
          show: true, position: "right", color: c["--text-2"], fontSize: 12,
          formatter: (p: { dataIndex: number }) => `${money(rows[p.dataIndex].value_eur)}  ${pct(rows[p.dataIndex].weight, 1)}`,
        },
      }],
    });
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el.current);
    return () => {
      ro.disconnect();
      chart.dispose();
    };
  }, [known, c]);

  return (
    <div>
      {known.length > 0 ? <div ref={el} style={{ height }} role="img" aria-label="Répartition" /> :
        <p className="text-sm text-muted">Aucune valeur connue.</p>}
      {missing.length > 0 && (
        <p className="mt-2 text-xs text-warn">
          Valeur {MISSING} : {missing.map((m) => m.label).join(", ")}. Les poids des autres lignes sont calculés
          sans elles.
        </p>
      )}
      <details className="mt-2 text-xs text-muted">
        <summary className="cursor-pointer">Voir le tableau</summary>
        <table className="data mt-1">
          <thead><tr><th>Ligne</th><th className="r">Valeur</th><th className="r">Poids</th></tr></thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.key}><td>{i.label}</td><td className="r num">{money(i.value_eur)}</td><td className="r num">{pct(i.weight, 1)}</td></tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
