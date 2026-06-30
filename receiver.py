#!/usr/bin/env python3
"""
receiver.py — Flask API
  POST /ingest   — accepts aircraft batches from the Pi collector
  GET  /flights  — returns flights near Camp Hill for the web app
  GET  /track    — returns lat/lon track for a specific callsign
  GET  /health   — health check
"""
import os
import logging
import psycopg2
import psycopg2.extras
from flask import Flask, request, jsonify
from flask_cors import CORS

DB_DSN = (
    f"host={os.environ.get('DB_HOST', 'postgres')} "
    f"dbname={os.environ.get('DB_NAME', 'adsb_db')} "
    f"user={os.environ.get('DB_USER', 'adsb')} "
    f"password={os.environ.get('DB_PASSWORD', 'adsb_secret')}"
)

HOME_LAT = -27.4942
HOME_LON  = 153.0772

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

INGEST_COLS = (
    "ts","icao","callsign","lat","lon","alt_baro","alt_geom",
    "ground_speed","track","vert_rate","squawk","category","rssi",
    "messages","seen",
)

# short_type prefixes considered "heavy" or "large"
HEAVY_TYPES  = ("H2J","H4J","H3J","H2T","H4T")   # widebody jets/turboprops
LARGE_TYPES  = ("L2J","L4J","L2T","L4T")          # narrowbody jets/turboprops


def get_db():
    return psycopg2.connect(DB_DSN)


@app.route("/ingest", methods=["POST"])
def ingest():
    batch = request.get_json(force=True)
    if not isinstance(batch, list) or not batch:
        return jsonify({"error": "expected a non-empty JSON array"}), 400
    rows = [tuple(ac.get(c) for c in INGEST_COLS) for ac in batch]
    try:
        with get_db() as conn, conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                f"INSERT INTO observations ({','.join(INGEST_COLS)}) VALUES %s",
                rows,
            )
        log.info(f"Inserted {len(rows)} rows")
        return jsonify({"inserted": len(rows)}), 201
    except Exception as e:
        log.error(f"DB error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/flights")
def flights():
    """
    Query params:
      hour_start  int        0-23    default 0
      hour_end    int        0-23    default 23
      min_alt     int        feet    default 0
      max_alt     int        feet    default 60000
      radius_km   float      km      default 15
      date        YYYY-MM-DD         optional
      size        str        all/heavy/large  default all
    """
    try:
        hour_start = int(request.args.get("hour_start", 0))
        hour_end   = int(request.args.get("hour_end",   23))
        min_alt    = int(request.args.get("min_alt",     0))
        max_alt    = int(request.args.get("max_alt",  60000))
        radius_km  = float(request.args.get("radius_km", 15))
        date_str   = request.args.get("date", None)
        size       = request.args.get("size", "all")  # all / heavy / large

        lat_delta = radius_km / 111.0
        lon_delta = radius_km / (111.0 * 0.887)
        lat_min, lat_max = HOME_LAT - lat_delta, HOME_LAT + lat_delta
        lon_min, lon_max = HOME_LON - lon_delta, HOME_LON + lon_delta

        # Build size filter
        size_filter = ""
        if size == "heavy":
            placeholders = ",".join(["%s"] * len(HEAVY_TYPES))
            size_filter  = f"AND a.short_type IN ({placeholders})"
            size_params  = list(HEAVY_TYPES)
        elif size == "large":
            combined     = HEAVY_TYPES + LARGE_TYPES
            placeholders = ",".join(["%s"] * len(combined))
            size_filter  = f"AND a.short_type IN ({placeholders})"
            size_params  = list(combined)
        else:
            size_params  = []

        date_filter, date_params = "", []
        if date_str:
            date_filter = "AND DATE(o.ts AT TIME ZONE 'Australia/Brisbane') = %s"
            date_params = [date_str]

        params = [min_alt, max_alt, lat_min, lat_max, lon_min, lon_max,
                  hour_start, hour_end] + size_params + date_params

        sql = f"""
            SELECT
                o.callsign,
                o.icao,
                COALESCE(NULLIF(a.manufacturer,''),'Unknown') AS manufacturer,
                COALESCE(NULLIF(a.model,''),       'Unknown') AS model,
                COALESCE(a.short_type,'')                     AS short_type,
                MIN(o.alt_baro)                               AS min_alt_ft,
                MAX(o.alt_baro)                               AS max_alt_ft,
                ROUND(MAX(o.ground_speed)::numeric,0)         AS max_speed_kts,
                MIN(o.ts AT TIME ZONE 'Australia/Brisbane')   AS first_seen,
                MAX(o.ts AT TIME ZONE 'Australia/Brisbane')   AS last_seen,
                COUNT(*)                                      AS observations,
                -- Loudness score: heavier + lower = louder
                ROUND((
                    CASE COALESCE(a.short_type,'')
                        WHEN 'H4J' THEN 100
                        WHEN 'H2J' THEN 90
                        WHEN 'H3J' THEN 90
                        WHEN 'H4T' THEN 80
                        WHEN 'H2T' THEN 75
                        WHEN 'L4J' THEN 65
                        WHEN 'L2J' THEN 60
                        ELSE 50
                    END
                ) * (1.0 - LEAST(MIN(o.alt_baro), 40000) / 40000.0)
                ) AS loudness_score
            FROM observations o
            LEFT JOIN aircraft_db a ON LOWER(o.icao) = a.icao
            WHERE o.callsign IS NOT NULL
              AND o.alt_baro BETWEEN %s AND %s
              AND o.lat BETWEEN %s AND %s
              AND o.lon BETWEEN %s AND %s
              AND EXTRACT(HOUR FROM o.ts AT TIME ZONE 'Australia/Brisbane')
                  BETWEEN %s AND %s
              AND COALESCE(a.model,'') NOT IN ('Count','count','')
              {size_filter}
              {date_filter}
            GROUP BY o.callsign, o.icao, a.manufacturer, a.model, a.short_type
            ORDER BY loudness_score DESC, min_alt_ft ASC
        """

        with get_db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        results = [
            {
                "callsign":      r["callsign"],
                "icao":          r["icao"],
                "manufacturer":  r["manufacturer"],
                "model":         r["model"],
                "short_type":    r["short_type"],
                "min_alt_ft":    r["min_alt_ft"],
                "max_alt_ft":    r["max_alt_ft"],
                "max_speed_kts": float(r["max_speed_kts"]) if r["max_speed_kts"] else None,
                "first_seen":    r["first_seen"].strftime("%Y-%m-%d %H:%M") if r["first_seen"] else None,
                "last_seen":     r["last_seen"].strftime("%H:%M") if r["last_seen"] else None,
                "observations":  r["observations"],
                "loudness_score": int(r["loudness_score"]) if r["loudness_score"] else 0,
            }
            for r in rows
        ]

        return jsonify({"flights": results, "count": len(results)})

    except Exception as e:
        log.error(f"Flights query error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/track")
def track():
    callsign = request.args.get("callsign","").upper().strip()
    date_str = request.args.get("date","")
    if not callsign or not date_str:
        return jsonify({"error": "callsign and date required"}), 400
    try:
        sql = """
            SELECT
                ts AT TIME ZONE 'Australia/Brisbane' AS local_ts,
                lat, lon, alt_baro, ground_speed, track, vert_rate
            FROM observations
            WHERE callsign = %s
              AND lat IS NOT NULL AND lon IS NOT NULL
              AND DATE(ts AT TIME ZONE 'Australia/Brisbane') = %s
            ORDER BY ts ASC
        """
        with get_db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (callsign, date_str))
            rows = cur.fetchall()
        points = [
            {
                "ts":    r["local_ts"].strftime("%H:%M:%S"),
                "lat":   float(r["lat"]),
                "lon":   float(r["lon"]),
                "alt":   r["alt_baro"],
                "speed": float(r["ground_speed"]) if r["ground_speed"] else None,
                "track": float(r["track"]) if r["track"] else None,
                "vrate": r["vert_rate"],
            }
            for r in rows
        ]
        return jsonify({"callsign": callsign, "date": date_str, "points": points, "count": len(points)})
    except Exception as e:
        log.error(f"Track error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    log.info("Receiver starting on :5050")
    app.run(host="0.0.0.0", port=5050)


@app.route("/current")
def current():
    """
    Returns aircraft currently overhead (seen in last N minutes).
    Query params:
      minutes    int    default 3
      radius_km  float  default 5
      min_alt    int    default 1000
    """
    try:
        minutes   = int(request.args.get("minutes",  3))
        radius_km = float(request.args.get("radius_km", 5))
        min_alt   = int(request.args.get("min_alt", 1000))

        lat_delta = radius_km / 111.0
        lon_delta = radius_km / (111.0 * 0.887)

        sql = """
            SELECT DISTINCT ON (o.callsign)
                o.callsign,
                o.icao,
                COALESCE(NULLIF(a.manufacturer,''),'Unknown') AS manufacturer,
                COALESCE(NULLIF(a.model,''),       'Unknown') AS model,
                COALESCE(a.short_type,'')                     AS short_type,
                o.alt_baro,
                o.ground_speed,
                o.track,
                o.vert_rate,
                o.lat,
                o.lon,
                o.ts AT TIME ZONE 'Australia/Brisbane' AS local_ts
            FROM observations o
            LEFT JOIN aircraft_db a ON LOWER(o.icao) = a.icao
            WHERE o.ts > NOW() - INTERVAL '%s minutes'
              AND o.callsign IS NOT NULL
              AND o.alt_baro > %s
              AND o.lat BETWEEN %s AND %s
              AND o.lon BETWEEN %s AND %s
            ORDER BY o.callsign, o.ts DESC
        """
        params = (
            minutes, min_alt,
            HOME_LAT - lat_delta, HOME_LAT + lat_delta,
            HOME_LON - lon_delta, HOME_LON + lon_delta,
        )

        with get_db() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        results = [
            {
                "callsign":     r["callsign"],
                "icao":         r["icao"],
                "manufacturer": r["manufacturer"],
                "model":        r["model"],
                "short_type":   r["short_type"],
                "alt_baro":     r["alt_baro"],
                "ground_speed": float(r["ground_speed"]) if r["ground_speed"] else None,
                "track":        float(r["track"]) if r["track"] else None,
                "vert_rate":    r["vert_rate"],
                "lat":          float(r["lat"]) if r["lat"] else None,
                "lon":          float(r["lon"]) if r["lon"] else None,
                "last_seen":    r["local_ts"].strftime("%H:%M:%S") if r["local_ts"] else None,
            }
            for r in rows
        ]

        return jsonify({"aircraft": results, "count": len(results)})

    except Exception as e:
        log.error(f"Current query error: {e}")
        return jsonify({"error": str(e)}), 500
