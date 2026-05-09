"""Définition du tool `get_weather` pour le LLM (palier 3a.1).

Le LLM voit `GET_WEATHER_TOOL` comme une fonction qu'il peut invoquer
avec `(location, date?)`. Le code exécute via `execute(args)` et renvoie
une chaîne *destinée au LLM*. Le LLM compose ensuite la réponse user
en français naturel (le round-trip est géré par `core/agent.py`).
"""

import logging
from datetime import datetime, timezone, date

from integrations._invoke_rule import INVOKE_RULE as _INVOKE_RULE
from .client import (
    GeocodingError, ForecastError,
    geocode, fetch_daily,
)

logger = logging.getLogger("GAB.integrations.weather.tool")


GET_WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": (
            _INVOKE_RULE +
            "Outil de consultation météo via Open-Meteo (gratuit). À INVOQUER "
            "dès qu'un user demande la météo d'un lieu/date — JAMAIS inventer "
            "des températures ou des conditions, toujours appeler cet outil.\n\n"
            "Cas d'usage typiques :\n"
            "  • « il fait beau samedi à Lyon ? » → invoque get_weather "
            "    avec location='Lyon' et date='YYYY-MM-DD' du samedi en cours.\n"
            "  • « quel temps il fait à Paris ? » → invoque sans date (= "
            "    aujourd'hui).\n"
            "  • « météo demain ? » → invoque avec la date de demain et la "
            "    ville inférée du contexte (event en cours, fait sémantique, "
            "    sinon redemande à l'user).\n\n"
            "LIMITES : forecast jusqu'à 16 jours dans le futur. Pas de météo "
            "passée (lève une erreur). Si la ville n'est pas trouvée, l'outil "
            "renvoie un message d'erreur — REFORMULE-LE simplement à l'user, "
            "ne fais pas semblant de connaître.\n\n"
            "RÈGLE D'OR pour `location` : tu passes DIRECTEMENT ce que "
            "l'utilisateur a dit, même si c'est un département (« Var », "
            "« 83 », « Alpes-Maritimes ») ou une région (« Bretagne », "
            "« PACA », « Île-de-France »). L'outil reconnaît tous les "
            "départements et régions français et les rabat sur leur ville "
            "chef-lieu. Tu n'as JAMAIS à demander un code postal ou une "
            "ville plus précise — invoque l'outil et laisse-le résoudre. "
            "Tu ne demandes une précision QUE si l'outil retourne une "
            "erreur de géocodage."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": (
                        "Nom du lieu en clair tel que l'utilisateur l'a "
                        "donné : ville (« Lyon », « Annecy »), département "
                        "(« Var », « 83 »), région (« Bretagne », « PACA ») "
                        "ou code postal (« 83000 »). L'outil fait son propre "
                        "géocodage et reconnaît les départements/régions FR."
                    ),
                },
                "date": {
                    "type": "string",
                    "description": (
                        "Date au format ISO YYYY-MM-DD. Si absent, aujourd'hui. "
                        "Doit être ≤ aujourd'hui + 15 jours. Convertis « demain », "
                        "« samedi », « ce week-end » en date absolue avant d'appeler."
                    ),
                },
            },
            "required": ["location"],
        },
    },
}


def _parse_date_arg(raw: str | None) -> date:
    if not raw:
        return datetime.now(timezone.utc).date()
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ValueError(f"date illisible : `{raw}` (attendu YYYY-MM-DD)") from exc


def _format_for_llm(loc: dict, daily: dict) -> str:
    """Phrase concise destinée au LLM pour qu'il reformule à l'user."""
    place = loc["label"]
    if loc.get("admin1") and loc["admin1"] != place:
        place = f"{place} ({loc['admin1']})"
    if loc.get("country"):
        place = f"{place}, {loc['country']}"
    parts = [
        f"Météo {place} le {daily['date']}",
        f"conditions : {daily['weather_label']}",
    ]
    if daily["t_max"] is not None and daily["t_min"] is not None:
        parts.append(f"{daily['t_min']:.0f}–{daily['t_max']:.0f} °C")
    if daily["precipitation_mm"] is not None and daily["precipitation_mm"] > 0:
        parts.append(f"précipitations {daily['precipitation_mm']:.1f} mm")
    if daily["wind_max_kmh"] is not None:
        parts.append(f"vent jusqu'à {daily['wind_max_kmh']:.0f} km/h")
    parts.append("(source : Open-Meteo)")
    return ". ".join(parts) + "."


async def execute(args: dict) -> str:
    """Point d'entrée appelé par `core/agent.py` quand le LLM invoque
    `get_weather`. Renvoie TOUJOURS une string — succès ou erreur — pour
    que le LLM puisse reformuler à l'user.
    """
    location = (args.get("location") or "").strip()
    if not location:
        return "Erreur : aucun lieu fourni. Demande à l'utilisateur de préciser."

    try:
        target = _parse_date_arg(args.get("date"))
    except ValueError as exc:
        return f"Erreur : {exc}."

    try:
        loc = await geocode(location)
    except GeocodingError as exc:
        return f"Erreur géocodage : {exc}. Demande à l'utilisateur de reformuler."
    except Exception as exc:
        logger.warning("get_weather geocode KO : %s", exc)
        return "Erreur : service de géocodage indisponible. Réessayer plus tard."

    try:
        daily = await fetch_daily(
            lat     = loc["latitude"],
            lon     = loc["longitude"],
            target_date = target,
            tz_name = loc["timezone"] or "auto",
        )
    except ForecastError as exc:
        return f"Erreur météo : {exc}."
    except Exception as exc:
        logger.warning("get_weather forecast KO : %s", exc)
        return "Erreur : service météo indisponible. Réessayer plus tard."

    text = _format_for_llm(loc, daily)
    logger.info("get_weather → %s", text)
    return text
