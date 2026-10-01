"""Fetch current weather from Open-Meteo (free, no API key) and store it in PostgreSQL.

Usage:
    python weather_to_postgres.py --city Pune --lat 18.5204 --lon 73.8567

Database connection comes from the DATABASE_URL environment variable, e.g.
    postgresql://postgres:yourpassword@localhost:5432/weather
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv(dotenv_path=r"C:\Users\Yeshwanth\Downloads\scheduler-server (1)\scheduler-server\.env")

import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")

API = "https://api.open-meteo.com/v1/forecast"
FIELDS = [
    "temperature_2m", "apparent_temperature", "relative_humidity_2m", "precipitation",
    "cloud_cover", "pressure_msl", "wind_speed_10m", "wind_direction_10m", "weather_code",
]

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS weather_readings (
    id              BIGSERIAL PRIMARY KEY,
    city            TEXT             NOT NULL,
    latitude        DOUBLE PRECISION NOT NULL,
    longitude       DOUBLE PRECISION NOT NULL,
    observed_at     TIMESTAMPTZ      NOT NULL,   -- time of the reading (UTC)
    fetched_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),
    temperature_c   DOUBLE PRECISION,
    feels_like_c    DOUBLE PRECISION,
    humidity_pct    DOUBLE PRECISION,
    precipitation_mm DOUBLE PRECISION,
    cloud_cover_pct DOUBLE PRECISION,
    pressure_hpa    DOUBLE PRECISION,
    wind_speed_kmh  DOUBLE PRECISION,
    wind_dir_deg    DOUBLE PRECISION,
    weather_code    INTEGER,
    UNIQUE (city, observed_at)                    -- re-runs never create duplicates
);
"""

INSERT_SQL = """
INSERT INTO weather_readings
    (city, latitude, longitude, observed_at, temperature_c, feels_like_c, humidity_pct,
     precipitation_mm, cloud_cover_pct, pressure_hpa, wind_speed_kmh, wind_dir_deg, weather_code)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (city, observed_at) DO NOTHING
"""


def fetch(lat: float, lon: float) -> dict:
    query = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "current": ",".join(FIELDS), "timezone": "UTC",
    })
    with urllib.request.urlopen(f"{API}?{query}", timeout=20) as resp:
        return json.load(resp)["current"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="Pune")
    ap.add_argument("--lat", type=float, default=18.5204)
    ap.add_argument("--lon", type=float, default=73.8567)
    a = ap.parse_args()

    try:
        c = fetch(a.lat, a.lon)
    except Exception as e:
        print(f"Weather API request failed: {e}")
        return 1

    observed_at = datetime.fromisoformat(c["time"]).replace(tzinfo=timezone.utc)

    try:
        with closing(psycopg2.connect(DATABASE_URL, connect_timeout=10)) as raw, raw as conn, conn.cursor() as cur:
            cur.execute(CREATE_SQL)
            cur.execute(INSERT_SQL, (
                a.city, a.lat, a.lon, observed_at,
                c["temperature_2m"], c["apparent_temperature"], c["relative_humidity_2m"],
                c["precipitation"], c["cloud_cover"], c["pressure_msl"],
                c["wind_speed_10m"], c["wind_direction_10m"], c["weather_code"],
            ))
            inserted = cur.rowcount
    except Exception as e:
        print(f"Database error: {e}")
        return 1

    print(f"{a.city}: {c['temperature_2m']}°C, humidity {c['relative_humidity_2m']}%, "
          f"wind {c['wind_speed_10m']} km/h at {observed_at:%Y-%m-%d %H:%M} UTC "
          f"({'saved' if inserted else 'already stored, skipped'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
