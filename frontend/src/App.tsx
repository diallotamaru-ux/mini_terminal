import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useSearchParams } from "react-router-dom";

import { useMeta } from "./api/client";
import type { Meta } from "./api/types";
import { SimulatedBanner } from "./components/ui";
import Comptes from "./pages/Comptes";
import Diversification from "./pages/Diversification";
import FicheValorisation from "./pages/FicheValorisation";
import Performance from "./pages/Performance";
import Positions from "./pages/Positions";
import Reglages from "./pages/Reglages";
import Risque from "./pages/Risque";
import TableauDeBord from "./pages/TableauDeBord";
import Transactions from "./pages/Transactions";
import Valorisation from "./pages/Valorisation";

const NAV = [
  { to: "/", label: "Tableau de bord" },
  { to: "/positions", label: "Positions" },
  { to: "/performance", label: "Performance", keepPeriod: true },
  { to: "/risque", label: "Risque", keepPeriod: true },
  { to: "/diversification", label: "Diversification", keepPeriod: true },
  { to: "/valorisation", label: "Valorisation" },
  { to: "/transactions", label: "Transactions" },
  { to: "/comptes", label: "Comptes et titres" },
  { to: "/reglages", label: "Réglages" },
];

type Theme = "dark" | "light";

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.dataset.theme === "light" ? "light" : "dark",
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("mt-theme", theme);
    } catch {
      /* stockage indisponible : le thème reste valable pour la session */
    }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}

/** Vrai si l'application ou une réponse déjà reçue contient des données simulées. */
function useSimulated(): boolean {
  const meta = useMeta();
  const qc = useQueryClient();
  useIsFetching(); // re-rendu quand une requête se termine
  const fromResponses = qc
    .getQueriesData<{ meta?: Meta }>({ queryKey: ["portfolio"] })
    .some(([, d]) => d?.meta?.simulated);
  return Boolean(meta.data?.simulated) || fromResponses;
}

export default function App() {
  const [theme, toggle] = useTheme();
  const simulated = useSimulated();
  const [menu, setMenu] = useState(false);
  // La période choisie suit l'utilisateur entre Performance et Risque.
  const [params] = useSearchParams();
  const periode = params.get("periode");

  return (
    <div className="min-h-screen">
      {simulated && <SimulatedBanner />}
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-2">
          <span className="font-semibold tracking-tight">Mini-terminal</span>
          <button className="ml-auto rounded-md border border-line px-2 py-1 text-sm md:hidden"
                  aria-expanded={menu} onClick={() => setMenu(!menu)}>
            Menu
          </button>
          <nav className={`${menu ? "flex" : "hidden"} absolute left-0 right-0 top-12 z-40 flex-col border-b border-line bg-surface px-4 py-2 md:static md:flex md:flex-row md:border-0 md:p-0`}>
            {NAV.map((n) => (
              <NavLink key={n.to} to={"keepPeriod" in n && periode ? `${n.to}?periode=${periode}` : n.to}
                end={n.to === "/"} onClick={() => setMenu(false)}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm ${isActive ? "bg-surface-2 text-ink" : "text-ink-2 hover:text-ink"}`}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <button className="rounded-md border border-line px-2 py-1 text-sm text-ink-2 hover:text-ink md:ml-auto"
                  onClick={toggle} aria-label="Changer de thème">
            {theme === "dark" ? "Thème clair" : "Thème sombre"}
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-7xl space-y-4 px-4 py-4">
        <Routes>
          <Route path="/" element={<TableauDeBord />} />
          <Route path="/positions" element={<Positions />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/transactions" element={<Transactions />} />
          <Route path="/comptes" element={<Comptes />} />
          <Route path="/risque" element={<Risque />} />
          <Route path="/diversification" element={<Diversification />} />
          <Route path="/valorisation" element={<Valorisation />} />
          <Route path="/valorisation/:ticker" element={<FicheValorisation />} />
          <Route path="/reglages" element={<Reglages />} />
        </Routes>
      </main>
      <footer className="mx-auto max-w-7xl px-4 pb-6 text-xs text-muted">
        Outil d'analyse en lecture seule : aucun ordre, aucune connexion à un courtier, aucun identifiant stocké.
        Les performances passées ne préjugent pas des performances futures.
      </footer>
    </div>
  );
}
