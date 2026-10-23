import { useEffect, useState } from "react";

const VARS = ["--surface", "--text", "--text-2", "--muted", "--grid", "--axis", "--series-1", "--series-2",
  "--series-3", "--series-4"] as const;

export type ChartColors = Record<(typeof VARS)[number], string>;

function read(): ChartColors {
  const cs = getComputedStyle(document.documentElement);
  return Object.fromEntries(VARS.map((v) => [v, cs.getPropertyValue(v).trim()])) as ChartColors;
}

/** Couleurs du thème courant, relues à chaque bascule clair/sombre. */
export function useChartColors(): ChartColors {
  const [colors, setColors] = useState(read);
  useEffect(() => {
    const obs = new MutationObserver(() => setColors(read()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);
  return colors;
}
