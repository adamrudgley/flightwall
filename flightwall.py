#!/usr/bin/env python3
"""
flightwall.py
Displays live overhead aircraft on a 64x32 HUB75 RGB LED matrix.

Hardware:
  - Raspberry Pi Zero 2W
  - Adafruit RGB Matrix Bonnet
  - 64x32 HUB75 RGB LED matrix panel (2.5mm pitch)
  - 5V 4A power supply

Dependencies:
  pip3 install Pillow requests
  (rpi-rgb-led-matrix installed separately — see setup guide)
"""

import time
import math
import requests
import logging
import os
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# ── CONFIG ────────────────────────────────────────────────────────────────────
THINKCENTRE_API  = "http://192.168.68.53:5050"
ADSBDB_API       = "https://api.adsbdb.com/v0/callsign"

POLL_INTERVAL    = 30       # seconds between API polls
DWELL_TIME       = 8        # seconds to show each aircraft
IDLE_BRIGHTNESS  = 50       # 0-100
ACTIVE_BRIGHTNESS= 80

MATRIX_WIDTH     = 64
MATRIX_HEIGHT    = 32

# ── COLOURS ───────────────────────────────────────────────────────────────────
BLACK   = (0,   0,   0)
CYAN    = (0,   200, 220)
WHITE   = (220, 220, 220)
AMBER   = (255, 170, 0)
GREEN   = (0,   200, 80)
RED     = (220, 50,  50)
GREY    = (60,  80,  100)
DIM     = (20,  40,  60)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── FONT LOADING ──────────────────────────────────────────────────────────────
FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")

def load_font(size=8):
    """Try to load a small bitmap font, fall back to PIL default."""
    paths = [
        os.path.join(FONT_DIR, "tom-thumb.bdf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                if p.endswith(".bdf"):
                    from PIL import BdfFontFile
                    return ImageFont.load(p)
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

FONT_SM  = load_font(7)
FONT_MED = load_font(8)

# ── ROUTE CACHE ───────────────────────────────────────────────────────────────
_route_cache = {}

def get_route(callsign):
    if callsign in _route_cache:
        return _route_cache[callsign]
    try:
        r = requests.get(f"{ADSBDB_API}/{callsign}", timeout=5)
        if r.ok:
            route = r.json().get("response", {}).get("flightroute")
            _route_cache[callsign] = route
            return route
    except Exception as e:
        log.warning(f"Route lookup failed for {callsign}: {e}")
    _route_cache[callsign] = None
    return None


# ── AIRCRAFT DATA ─────────────────────────────────────────────────────────────
def fetch_aircraft():
    try:
        r = requests.get(
            f"{THINKCENTRE_API}/current",
            params={"minutes": 3, "radius_km": 5, "min_alt": 1000},
            timeout=5,
        )
        r.raise_for_status()
        return r.json().get("aircraft", [])
    except Exception as e:
        log.error(f"Failed to fetch aircraft: {e}")
        return []


# ── DISPLAY RENDERING ─────────────────────────────────────────────────────────
def draw_text(draw, x, y, text, font, color, max_width=None):
    """Draw text, truncating to max_width pixels if set."""
    if max_width:
        # Truncate text to fit
        while len(text) > 1:
            bbox = draw.textbbox((0, 0), text, font=font)
            w = bbox[2] - bbox[0]
            if w <= max_width:
                break
            text = text[:-1]
    draw.text((x, y), text, font=font, fill=color)
    return text


def vert_rate_arrow(vrate):
    if vrate is None: return ""
    if vrate > 200:  return "↑"
    if vrate < -200: return "↓"
    return "→"


def format_alt(alt):
    if alt is None: return "—"
    if alt >= 1000: return f"{alt//1000}k ft"
    return f"{alt} ft"


def format_speed(spd):
    if spd is None: return "—"
    return f"{int(spd)} kts"


def short_aircraft_type(model):
    """Convert full model name to a short display code e.g. A330, B787."""
    if not model or model == "Unknown":
        return None
    m = model.upper()
    if   "A380" in m: return "A380"
    elif "A350" in m: return "A350"
    elif "A340" in m: return "A340"
    elif "A330" in m: return "A330"
    elif "A321" in m: return "A321"
    elif "A320" in m: return "A320"
    elif "A319" in m: return "A319"
    elif "A220" in m: return "A220"
    elif "787"  in m: return "B787"
    elif "777"  in m: return "B777"
    elif "767"  in m: return "B767"
    elif "757"  in m: return "B757"
    elif "747"  in m: return "B747"
    elif "737"  in m: return "B737"
    elif "717"  in m: return "B717"
    elif "ERJ"  in m: return "E190"
    elif "E190" in m: return "E190"
    elif "E175" in m: return "E175"
    elif "ATR"  in m: return "ATR72"
    elif "DHC"  in m: return "DASH8"
    elif "AW139" in m:return "H139"
    elif "F28"  in m: return "F100"
    return None


def render_aircraft_frame(ac, route, frame=0):
    """Render a single 64x32 frame for one aircraft."""
    img  = Image.new("RGB", (MATRIX_WIDTH, MATRIX_HEIGHT), BLACK)
    draw = ImageDraw.Draw(img)

    # ── TOP ROW: callsign + aircraft type + time ────────────────────────
    callsign = ac.get("callsign", "?")
    ac_type  = short_aircraft_type(ac.get("model", ""))

    draw_text(draw, 1, 1, callsign, FONT_MED, CYAN, max_width=36)

    # Aircraft type next to callsign
    if ac_type:
        cs_bbox = draw.textbbox((0,0), callsign, font=FONT_MED)
        cs_w = cs_bbox[2] - cs_bbox[0]
        draw.text((cs_w + 4, 2), ac_type, font=FONT_SM, fill=AMBER)

    # Time top-right
    now = datetime.now().strftime("%H:%M")
    t_bbox = draw.textbbox((0,0), now, font=FONT_SM)
    t_w = t_bbox[2] - t_bbox[0]
    draw.text((MATRIX_WIDTH - t_w - 1, 2), now, font=FONT_SM, fill=GREY)

    # Divider line
    draw.line([(0, 10), (MATRIX_WIDTH, 10)], fill=DIM)

    # ── MIDDLE: route ─────────────────────────────────────────────────────
    if route and route.get("origin") and route.get("destination"):
        origin = route["origin"].get("iata_code") or route["origin"].get("icao_code", "???")
        dest   = route["destination"].get("iata_code") or route["destination"].get("icao_code", "???")
        airline = route.get("airline", {}).get("name", "")

        # Origin → Dest
        route_str = f"{origin}  {dest}"
        # Draw origin
        draw.text((1, 12), origin, font=FONT_MED, fill=WHITE)
        # Arrow
        arrow_x = 1 + draw.textbbox((0,0), origin, font=FONT_MED)[2] + 2
        draw.text((arrow_x, 12), "->", font=FONT_SM, fill=GREY)
        # Dest
        dest_x = arrow_x + draw.textbbox((0,0), "->", font=FONT_SM)[2] + 2
        draw.text((dest_x, 12), dest, font=FONT_MED, fill=WHITE)

        # Airline name (scrolling if long) on row below
        if airline:
            # Simple scroll based on frame number
            full = airline[:24]
            scroll_offset = (frame // 2) % max(1, len(full) - 10)
            visible = full[scroll_offset:scroll_offset + 12]
            draw.text((1, 21), visible, font=FONT_SM, fill=GREY)
    else:
        # No route data — show model
        model = ac.get("model", "")
        if model and model != "Unknown":
            draw_text(draw, 1, 12, model[:14], FONT_SM, GREY)
        else:
            draw.text((1, 12), "Route unknown", font=FONT_SM, fill=GREY)

    # Divider
    draw.line([(0, 21), (MATRIX_WIDTH, 21)], fill=DIM)

    # ── BOTTOM ROW: alt + speed ───────────────────────────────────────────
    alt   = format_alt(ac.get("alt_baro"))
    speed = format_speed(ac.get("ground_speed"))
    arrow = vert_rate_arrow(ac.get("vert_rate"))

    alt_str = f"{arrow}{alt}"
    draw.text((1, 23), alt_str, font=FONT_SM, fill=AMBER)

    spd_bbox = draw.textbbox((0,0), speed, font=FONT_SM)
    spd_w = spd_bbox[2] - spd_bbox[0]
    draw.text((MATRIX_WIDTH - spd_w - 1, 23), speed, font=FONT_SM, fill=GREEN)

    return img


def render_idle_frame(count, frame=0):
    """Render the 'no aircraft' idle screen."""
    img  = Image.new("RGB", (MATRIX_WIDTH, MATRIX_HEIGHT), BLACK)
    draw = ImageDraw.Draw(img)

    # Pulsing dot
    brightness = int(40 + 30 * math.sin(frame * 0.15))
    pulse_col  = (0, brightness, brightness + 20)

    draw.ellipse([28, 8, 36, 16], outline=pulse_col)
    draw.ellipse([30, 10, 34, 14], fill=pulse_col)

    draw.text((8, 18), "NO AIRCRAFT", font=FONT_SM, fill=DIM)

    now = datetime.now().strftime("%H:%M")
    t_bbox = draw.textbbox((0,0), now, font=FONT_SM)
    t_w = t_bbox[2] - t_bbox[0]
    draw.text(((MATRIX_WIDTH - t_w)//2, 25), now, font=FONT_SM, fill=GREY)

    return img


# ── MAIN LOOP ─────────────────────────────────────────────────────────────────
def main():
    # Import LED matrix — only available on Pi with rpi-rgb-led-matrix installed
    try:
        from rgbmatrix import RGBMatrix, RGBMatrixOptions
    except ImportError:
        log.error("rpi-rgb-led-matrix not installed. See setup guide.")
        log.info("Running in PREVIEW mode — saving frames as preview.png")
        run_preview_mode()
        return

    options = RGBMatrixOptions()
    options.rows                 = 32
    options.cols                 = 64
    options.chain_length         = 1
    options.parallel             = 1
    options.hardware_mapping     = "adafruit-hat"   # Adafruit RGB Matrix Bonnet
    options.gpio_slowdown        = 4                # increase if flickering (1-4)
    options.brightness           = ACTIVE_BRIGHTNESS
    options.disable_hardware_pulsing = True         # required for Pi Zero
    options.drop_privileges      = False

    matrix = RGBMatrix(options=options)
    canvas = matrix.CreateFrameCanvas()

    log.info("FlightWall starting…")

    aircraft_list = []
    route_map     = {}
    last_poll     = 0
    ac_index      = 0
    frame         = 0
    dwell_frames  = DWELL_TIME * 10  # at ~10fps

    while True:
        now = time.time()

        # Poll for new aircraft every POLL_INTERVAL seconds
        if now - last_poll > POLL_INTERVAL:
            log.info("Polling for aircraft…")
            aircraft_list = fetch_aircraft()
            log.info(f"Found {len(aircraft_list)} aircraft overhead")
            last_poll = now
            ac_index  = 0

            # Kick off route lookups in background
            for ac in aircraft_list:
                cs = ac.get("callsign")
                if cs and cs not in route_map:
                    route = get_route(cs)
                    route_map[cs] = route
                    if route:
                        log.info(f"  {cs}: {route.get('origin',{}).get('iata_code','?')} → {route.get('destination',{}).get('iata_code','?')}")

        # Render frame
        if not aircraft_list:
            img = render_idle_frame(0, frame)
        else:
            # Advance to next aircraft every dwell_frames
            if frame > 0 and frame % dwell_frames == 0:
                ac_index = (ac_index + 1) % len(aircraft_list)

            ac    = aircraft_list[ac_index]
            route = route_map.get(ac.get("callsign"))
            img   = render_aircraft_frame(ac, route, frame)

        # Push to matrix
        canvas.SetImage(img)
        canvas = matrix.SwapOnVSync(canvas)

        frame += 1
        time.sleep(0.1)  # ~10fps


def run_preview_mode():
    """Generate preview PNGs without the LED matrix hardware."""
    log.info("Fetching aircraft for preview…")
    aircraft_list = fetch_aircraft()

    if not aircraft_list:
        log.info("No aircraft overhead — rendering idle screen")
        img = render_idle_frame(0, 0)
        img_big = img.resize((MATRIX_WIDTH * 6, MATRIX_HEIGHT * 6), Image.NEAREST)
        img_big.save("preview_idle.png")
        log.info("Saved preview_idle.png")
        return

    for i, ac in enumerate(aircraft_list[:3]):
        cs    = ac.get("callsign", "TEST")
        route = get_route(cs)
        img   = render_aircraft_frame(ac, route, 0)
        # Scale up 6x so it's visible
        img_big = img.resize((MATRIX_WIDTH * 6, MATRIX_HEIGHT * 6), Image.NEAREST)
        fname = f"preview_{i+1}_{cs}.png"
        img_big.save(fname)
        log.info(f"Saved {fname} — {cs}")


if __name__ == "__main__":
    main()
