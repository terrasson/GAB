"""Wrapper async sur Open-Meteo (gratuit, sans clé) :

- `geocode(name)` → premier résultat (lat, lon, label) via
  geocoding-api.open-meteo.com.
- `fetch_daily(lat, lon, target_date)` → météo journalière pour la
  date demandée (forecast jusqu'à 16 jours).

Pas d'archive (météo passée) en v1 — endpoint `archive-api` séparé,
hors scope.

Référence WMO weather codes :
https://open-meteo.com/en/docs#weathervariables
"""

import logging
from datetime import date, datetime, timezone, timedelta

import httpx

logger = logging.getLogger("GAB.integrations.weather")


_GEOCODE_URL  = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_HTTP_TIMEOUT = 10.0


# ── WMO weather code → texte FR concis ────────────────────────────────────


_WMO_FR = {
    0:  "ciel clair",
    1:  "principalement clair",
    2:  "partiellement nuageux",
    3:  "couvert",
    45: "brouillard",
    48: "brouillard givrant",
    51: "bruine légère",
    53: "bruine modérée",
    55: "bruine dense",
    56: "bruine verglaçante légère",
    57: "bruine verglaçante dense",
    61: "pluie légère",
    63: "pluie modérée",
    65: "pluie forte",
    66: "pluie verglaçante légère",
    67: "pluie verglaçante forte",
    71: "neige légère",
    73: "neige modérée",
    75: "neige forte",
    77: "grains de neige",
    80: "averses légères",
    81: "averses modérées",
    82: "averses violentes",
    85: "averses de neige légères",
    86: "averses de neige fortes",
    95: "orage",
    96: "orage avec grêle légère",
    99: "orage avec grêle forte",
}


def describe_weather_code(code: int) -> str:
    return _WMO_FR.get(code, f"conditions inconnues (code {code})")


# ── Geocoding ─────────────────────────────────────────────────────────────


class GeocodingError(Exception):
    """Levée quand on ne trouve pas la ville demandée."""


async def geocode(name: str) -> dict:
    """Retourne le premier résultat geocoding pour `name`. Lève
    `GeocodingError` si rien trouvé.

    Renvoie un dict : `{label, latitude, longitude, country, timezone}`.
    """
    name = (name or "").strip()
    if not name:
        raise GeocodingError("nom de lieu vide")
    params = {"name": name, "count": 1, "language": "fr", "format": "json"}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(_GEOCODE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    results = data.get("results") or []
    if not results:
        raise GeocodingError(f"aucun lieu trouvé pour « {name} »")
    r = results[0]
    return {
        "label":     r.get("name") or name,
        "country":   r.get("country") or "",
        "admin1":    r.get("admin1") or "",
        "latitude":  float(r["latitude"]),
        "longitude": float(r["longitude"]),
        "timezone":  r.get("timezone") or "auto",
    }


# ── Forecast ──────────────────────────────────────────────────────────────


class ForecastError(Exception):
    """Erreur lors de la récupération du forecast."""


async def fetch_daily(
    lat: float,
    lon: float,
    target_date: date,
    tz_name: str = "auto",
) -> dict:
    """Renvoie la météo journalière pour `target_date` (au plus 16 jours).

    Sortie : `{date, weather_code, weather_label, t_max, t_min,
    precipitation_mm, wind_max_kmh}`. Lève `ForecastError` si la date
    n'est pas couverte par la réponse.
    """
    today = datetime.now(timezone.utc).date()
    delta = (target_date - today).days
    if delta < 0:
        raise ForecastError("date dans le passé non supportée (v1)")
    if delta > 15:
        raise ForecastError("date au-delà de l'horizon (16 jours)")

    params = {
        "latitude":  lat,
        "longitude": lon,
        "daily":     ",".join([
            "weathercode",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "windspeed_10m_max",
        ]),
        "timezone": tz_name,
        "start_date": target_date.isoformat(),
        "end_date":   target_date.isoformat(),
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(_FORECAST_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    if not dates:
        raise ForecastError("aucune donnée renvoyée par Open-Meteo")
    if dates[0] != target_date.isoformat():
        raise ForecastError(
            f"date demandée {target_date} non disponible "
            f"(retourné : {dates[0]})"
        )

    code = int((daily.get("weathercode") or [0])[0])
    return {
        "date":             target_date.isoformat(),
        "weather_code":     code,
        "weather_label":    describe_weather_code(code),
        "t_max":            (daily.get("temperature_2m_max") or [None])[0],
        "t_min":            (daily.get("temperature_2m_min") or [None])[0],
        "precipitation_mm": (daily.get("precipitation_sum") or [None])[0],
        "wind_max_kmh":     (daily.get("windspeed_10m_max") or [None])[0],
    }
