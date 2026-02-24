import argparse
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

mcp = FastMCP(
    name="yakulingo-weather-mcp",
    instructions=(
        "Use search_weather to retrieve latest weather information "
        "for a requested location."
    ),
    stateless_http=True,
    json_response=True,
)


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


@mcp.tool()
async def search_weather(location: str, days: int = 1) -> str:
    query = str(location or "").strip()
    if not query:
        return "location is required."

    safe_days = max(1, min(7, int(days or 1)))
    timeout = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        geo_res = await client.get(
            GEOCODE_URL,
            params={
                "name": query,
                "count": 1,
                "language": "ja",
                "format": "json",
            },
        )
        geo_res.raise_for_status()
        geo_data = geo_res.json() if geo_res.content else {}
        geo_results = geo_data.get("results") if isinstance(geo_data, dict) else None
        if not isinstance(geo_results, list) or not geo_results:
            return f"location not found: {query}"

        row = geo_results[0] if isinstance(geo_results[0], dict) else {}
        lat = _to_float(row.get("latitude"))
        lon = _to_float(row.get("longitude"))
        if lat is None or lon is None:
            return f"location not found: {query}"

        forecast_res = await client.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "timezone": "auto",
                "forecast_days": safe_days,
                "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            },
        )
        forecast_res.raise_for_status()
        forecast = forecast_res.json() if forecast_res.content else {}

    payload = {
        "provider": "open-meteo",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "resolved_location": {
            "name": row.get("name"),
            "country": row.get("country"),
            "admin1": row.get("admin1"),
            "latitude": lat,
            "longitude": lon,
            "timezone": forecast.get("timezone") if isinstance(forecast, dict) else None,
        },
        "current": (forecast.get("current") if isinstance(forecast, dict) else {}) or {},
        "daily": (forecast.get("daily") if isinstance(forecast, dict) else {}) or {},
    }
    return json.dumps(payload, ensure_ascii=False)


def create_app() -> Starlette:
    streamable_http_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_: Starlette):
        async with mcp.session_manager.run():
            yield

    async def health(_: Any) -> JSONResponse:
        return JSONResponse({"ok": True, "service": "yakulingo-weather-mcp"})

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Mount("/", app=streamable_http_app),
        ],
        lifespan=lifespan,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="YakuLingo local weather MCP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    uvicorn.run(create_app(), host=args.host, port=args.port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
