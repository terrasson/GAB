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
import unicodedata
from datetime import date, datetime, timezone, timedelta

import httpx

logger = logging.getLogger("GAB.integrations.weather")


_GEOCODE_URL  = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_HTTP_TIMEOUT = 10.0


# ── Alias FR : départements / régions → ville chef-lieu ────────────────────
#
# Open-Meteo ne sait pas géocoder les noms de département ("Var" →
# Varna en Bulgarie 🤦) ni les régions françaises ("Bretagne" →
# Bretagne-de-Marsan). On rabat ces noms vers la ville chef-lieu
# AVANT d'appeler l'API, de façon transparente pour l'utilisateur.
# La normalisation `_norm_fr` retire les accents et la casse pour
# robustesse (« Côte-d'Or » == « cote dor »). Couvre les 101
# départements + variantes courantes (numéros, abréviations PACA) +
# 13 régions métropolitaines.

def _norm_fr(s: str) -> str:
    s = (s or "").strip().lower()
    s = "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )
    # Uniformise les séparateurs (tirets / espaces / apostrophes) en espace.
    for ch in ("-", "'", "_", "."):
        s = s.replace(ch, " ")
    return " ".join(s.split())


# Map des 101 départements français → ville chef-lieu (préfecture).
# Les codes département sont aussi acceptés (« 06 », « 83 »).
_FR_DEPT_TO_CITY: dict[str, str] = {
    "ain": "Bourg-en-Bresse", "01": "Bourg-en-Bresse",
    "aisne": "Laon", "02": "Laon",
    "allier": "Moulins", "03": "Moulins",
    "alpes de haute provence": "Digne-les-Bains", "04": "Digne-les-Bains",
    "hautes alpes": "Gap", "05": "Gap",
    "alpes maritimes": "Nice", "06": "Nice",
    "ardeche": "Privas", "07": "Privas",
    "ardennes": "Charleville-Mézières", "08": "Charleville-Mézières",
    "ariege": "Foix", "09": "Foix",
    "aube": "Troyes", "10": "Troyes",
    "aude": "Carcassonne", "11": "Carcassonne",
    "aveyron": "Rodez", "12": "Rodez",
    "bouches du rhone": "Marseille", "13": "Marseille",
    "calvados": "Caen", "14": "Caen",
    "cantal": "Aurillac", "15": "Aurillac",
    "charente": "Angoulême", "16": "Angoulême",
    "charente maritime": "La Rochelle", "17": "La Rochelle",
    "cher": "Bourges", "18": "Bourges",
    "correze": "Tulle", "19": "Tulle",
    "corse du sud": "Ajaccio", "2a": "Ajaccio",
    "haute corse": "Bastia", "2b": "Bastia",
    "corse": "Ajaccio",
    "cote d or": "Dijon", "21": "Dijon",
    "cotes d armor": "Saint-Brieuc", "22": "Saint-Brieuc",
    "creuse": "Guéret", "23": "Guéret",
    "dordogne": "Périgueux", "24": "Périgueux",
    "doubs": "Besançon", "25": "Besançon",
    "drome": "Valence", "26": "Valence",
    "eure": "Évreux", "27": "Évreux",
    "eure et loir": "Chartres", "28": "Chartres",
    "finistere": "Quimper", "29": "Quimper",
    "gard": "Nîmes", "30": "Nîmes",
    "haute garonne": "Toulouse", "31": "Toulouse",
    "gers": "Auch", "32": "Auch",
    "gironde": "Bordeaux", "33": "Bordeaux",
    "herault": "Montpellier", "34": "Montpellier",
    "ille et vilaine": "Rennes", "35": "Rennes",
    "indre": "Châteauroux", "36": "Châteauroux",
    "indre et loire": "Tours", "37": "Tours",
    "isere": "Grenoble", "38": "Grenoble",
    "jura": "Lons-le-Saunier", "39": "Lons-le-Saunier",
    "landes": "Mont-de-Marsan", "40": "Mont-de-Marsan",
    "loir et cher": "Blois", "41": "Blois",
    "loire": "Saint-Étienne", "42": "Saint-Étienne",
    "haute loire": "Le Puy-en-Velay", "43": "Le Puy-en-Velay",
    "loire atlantique": "Nantes", "44": "Nantes",
    "loiret": "Orléans", "45": "Orléans",
    "lot": "Cahors", "46": "Cahors",
    "lot et garonne": "Agen", "47": "Agen",
    "lozere": "Mende", "48": "Mende",
    "maine et loire": "Angers", "49": "Angers",
    "manche": "Saint-Lô", "50": "Saint-Lô",
    "marne": "Châlons-en-Champagne", "51": "Châlons-en-Champagne",
    "haute marne": "Chaumont", "52": "Chaumont",
    "mayenne": "Laval", "53": "Laval",
    "meurthe et moselle": "Nancy", "54": "Nancy",
    "meuse": "Bar-le-Duc", "55": "Bar-le-Duc",
    "morbihan": "Vannes", "56": "Vannes",
    "moselle": "Metz", "57": "Metz",
    "nievre": "Nevers", "58": "Nevers",
    "nord": "Lille", "59": "Lille",
    "oise": "Beauvais", "60": "Beauvais",
    "orne": "Alençon", "61": "Alençon",
    "pas de calais": "Arras", "62": "Arras",
    "puy de dome": "Clermont-Ferrand", "63": "Clermont-Ferrand",
    "pyrenees atlantiques": "Pau", "64": "Pau",
    "hautes pyrenees": "Tarbes", "65": "Tarbes",
    "pyrenees orientales": "Perpignan", "66": "Perpignan",
    "bas rhin": "Strasbourg", "67": "Strasbourg",
    "haut rhin": "Colmar", "68": "Colmar",
    "rhone": "Lyon", "69": "Lyon",
    "haute saone": "Vesoul", "70": "Vesoul",
    "saone et loire": "Mâcon", "71": "Mâcon",
    "sarthe": "Le Mans", "72": "Le Mans",
    "savoie": "Chambéry", "73": "Chambéry",
    "haute savoie": "Annecy", "74": "Annecy",
    "paris": "Paris", "75": "Paris",
    "seine maritime": "Rouen", "76": "Rouen",
    "seine et marne": "Melun", "77": "Melun",
    "yvelines": "Versailles", "78": "Versailles",
    "deux sevres": "Niort", "79": "Niort",
    "somme": "Amiens", "80": "Amiens",
    "tarn": "Albi", "81": "Albi",
    "tarn et garonne": "Montauban", "82": "Montauban",
    "var": "Toulon", "83": "Toulon",
    "vaucluse": "Avignon", "84": "Avignon",
    "vendee": "La Roche-sur-Yon", "85": "La Roche-sur-Yon",
    "vienne": "Poitiers", "86": "Poitiers",
    "haute vienne": "Limoges", "87": "Limoges",
    "vosges": "Épinal", "88": "Épinal",
    "yonne": "Auxerre", "89": "Auxerre",
    "territoire de belfort": "Belfort", "90": "Belfort",
    "essonne": "Évry-Courcouronnes", "91": "Évry",
    "hauts de seine": "Nanterre", "92": "Nanterre",
    "seine saint denis": "Bobigny", "93": "Bobigny",
    "val de marne": "Créteil", "94": "Créteil",
    "val d oise": "Cergy", "95": "Cergy",
    "guadeloupe": "Basse-Terre", "971": "Basse-Terre",
    "martinique": "Fort-de-France", "972": "Fort-de-France",
    "guyane": "Cayenne", "973": "Cayenne",
    "la reunion": "Saint-Denis", "974": "Saint-Denis",
    "reunion": "Saint-Denis",
    "mayotte": "Mamoudzou", "976": "Mamoudzou",
}

# Régions métropolitaines + outre-mer → ville la plus emblématique.
_FR_REGION_TO_CITY: dict[str, str] = {
    "auvergne rhone alpes":     "Lyon",
    "ara":                       "Lyon",
    "bourgogne franche comte":  "Dijon",
    "bfc":                       "Dijon",
    "bretagne":                  "Rennes",
    "centre val de loire":      "Orléans",
    "cvl":                       "Orléans",
    "corse":                     "Ajaccio",
    "grand est":                "Strasbourg",
    "hauts de france":          "Lille",
    "hdf":                       "Lille",
    "ile de france":            "Paris",
    "idf":                       "Paris",
    "normandie":                "Rouen",
    "nouvelle aquitaine":       "Bordeaux",
    "occitanie":                "Toulouse",
    "pays de la loire":         "Nantes",
    "provence alpes cote d azur": "Marseille",
    "paca":                      "Marseille",
    "provence":                  "Marseille",
}

_FR_ALIASES: dict[str, str] = {**_FR_DEPT_TO_CITY, **_FR_REGION_TO_CITY}


def _resolve_fr_alias(name: str) -> str | None:
    """Si `name` est un département ou une région française connue, retourne
    la ville chef-lieu correspondante. Sinon None."""
    return _FR_ALIASES.get(_norm_fr(name))


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

    Pré-résolution FR : si `name` est un département (« Var », « 83 »)
    ou une région (« Bretagne », « PACA »), on rabat sur la ville
    chef-lieu avant d'interroger Open-Meteo. Cf. `_FR_ALIASES`.

    Renvoie un dict : `{label, latitude, longitude, country, timezone}`.
    """
    raw = (name or "").strip()
    if not raw:
        raise GeocodingError("nom de lieu vide")

    query = raw
    aliased = _resolve_fr_alias(raw)
    if aliased:
        logger.info("geocode : alias FR « %s » → « %s »", raw, aliased)
        query = aliased

    params = {"name": query, "count": 1, "language": "fr", "format": "json"}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(_GEOCODE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    results = data.get("results") or []
    if not results:
        raise GeocodingError(f"aucun lieu trouvé pour « {raw} »")
    r = results[0]
    return {
        "label":     r.get("name") or query,
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
