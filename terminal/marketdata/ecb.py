"""
Taux de la Banque centrale européenne (ECB Data Portal). Seul fichier qui appelle la BCE.

    €STR  : EST/B.EU000A2X2A25.WT   (depuis le 01/10/2019)
    EONIA : EON/D.EONIA_TO.RATE     (1999 - 31/12/2021)
"""

from __future__ import annotations

import csv
import io
import urllib.error
import urllib.request
from datetime import date

import pandas as pd

from ..errors import ProviderUnavailable
from .base import PriceSeries, clean_series
from .rates import SERIES, RateProvider

BASE = "https://data-api.ecb.europa.eu/service/data/"
KEYS = {"estr": "EST/B.EU000A2X2A25.WT", "eonia": "EON/D.EONIA_TO.RATE"}
SOURCE = "BCE (ECB Data Portal)"


class EcbRates(RateProvider):
    name = "bce"
    simulated = False

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def _get(self, url: str) -> str:
        req = urllib.request.Request(url, headers={"Accept": "text/csv", "User-Agent": "mini-terminal"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 404:                  # aucune observation sur la période
                return ""
            raise ProviderUnavailable("bce", f"HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ProviderUnavailable("bce", str(e)) from e

    def overnight(self, series: str, start: date, end: date) -> PriceSeries:
        if series not in SERIES:
            raise ProviderUnavailable("bce", f"série inconnue {series}")
        text = self._get(f"{BASE}{KEYS[series]}?format=csvdata&startPeriod={start.isoformat()}"
                         f"&endPeriod={end.isoformat()}")
        rows = list(csv.DictReader(io.StringIO(text))) if text.strip() else []
        try:
            values = {pd.Timestamp(r["TIME_PERIOD"]): float(r["OBS_VALUE"]) for r in rows if r.get("OBS_VALUE")}
        except (KeyError, ValueError) as e:
            raise ProviderUnavailable("bce", f"réponse illisible : {e}") from e
        return PriceSeries(series.upper(), clean_series(pd.Series(values, dtype=float)), SOURCE)
