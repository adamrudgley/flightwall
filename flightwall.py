#!/usr/bin/env python3
"""
flightwall.py
Displays live overhead aircraft on a 64x32 HUB75 RGB LED matrix.

Two pages per aircraft, cycling automatically:
  Page 1 — Airline logo + callsign + aircraft type
  Page 2 — Route + altitude + speed

Hardware:
  - Raspberry Pi Zero 2W
  - Adafruit RGB Matrix Bonnet
  - 64x32 HUB75 RGB LED matrix panel (2.5mm pitch)
  - 5V 4A power supply

Dependencies:
  pip3 install Pillow requests --break-system-packages
  (rpi-rgb-led-matrix installed separately — see setup guide)

Airline logos:
  Place small PNGs (ideally 16x16 or 18x18, transparent background) in
  ./logos/ named by ICAO airline code, e.g. logos/QFA.png, logos/UAE.png,
  logos/VOZ.png, logos/JST.png. If a logo isn't found, a coloured
  monogram badge is generated automatically using the airline initials.
"""

import time
import math
import requests
import logging
import os
import hashlib
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# ── CONFIG ────────────────────────────────────────────────────────────────────
THINKCENTRE_API   = "http://192.168.68.53:5050"
ADSBDB_API        = "https://api.adsbdb.com/v0/callsign"

POLL_INTERVAL     = 30       # seconds between API polls
PAGE_DWELL_TIME   = 4        # seconds to show each page
ACTIVE_BRIGHTNESS = 80

MATRIX_WIDTH      = 64
MATRIX_HEIGHT     = 32

LOGO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logos")

# ── COLOURS ───────────────────────────────────────────────────────────────────
BLACK   = (0,   0,   0)
CYAN    = (0,   200, 220)
WHITE   = (220, 220, 220)
AMBER   = (255, 170, 0)
GREEN   = (0,   200, 80)
RED     = (220, 50,  50)
GREY    = (60,  80,  100)
DIM     = (20,  40,  60)

MONOGRAM_PALETTE = [
    (200, 30, 40), (30, 100, 200), (220, 140, 0), (0, 150, 110),
    (160, 40, 180), (0, 130, 200), (200, 90, 20), (90, 150, 30),
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── FONT LOADING ──────────────────────────────────────────────────────────────
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

def load_font(size=8):
    paths = [
        os.path.join(FONT_DIR, "tom-thumb.bdf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                if p.endswith(".bdf"):
                    return ImageFont.load(p)
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

FONT_SM  = load_font(7)
FONT_MED = load_font(8)
FONT_LG  = load_font(10)

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


# ── AIRLINE LOGO HANDLING ─────────────────────────────────────────────────────
_logo_cache = {}

def airline_code_from_callsign(callsign):
    """First 3 letters of the callsign are the ICAO airline code, e.g. QFA15 -> QFA."""
    if not callsign:
        return None
    letters = "".join(c for c in callsign if c.isalpha())
    return letters[:3].upper() if len(letters) >= 3 else None


def monogram_colour(code):
    h = int(hashlib.md5(code.encode()).hexdigest(), 16)
    return MONOGRAM_PALETTE[h % len(MONOGRAM_PALETTE)]


def get_logo(callsign, airline_name=None, size=20):
    """
    Returns a PIL Image (RGBA, size x size) for the airline logo.
    Looks for logos/<ICAO_CODE>.png first; falls back to a generated
    coloured monogram badge using the airline initials.
    """
    code = airline_code_from_callsign(callsign) or "???"
    cache_key = f"{code}_{size}"
    if cache_key in _logo_cache:
        return _logo_cache[cache_key]

    logo_path = os.path.join(LOGO_DIR, f"{code}.png")
    if os.path.exists(logo_path):
        try:
            img = Image.open(logo_path).convert("RGBA")
            img = img.resize((size, size), Image.LANCZOS)
            _logo_cache[cache_key] = img
            return img
        except Exception as e:
            log.warning(f"Failed to load logo {logo_path}: {e}")

    initials = code[:2] if code != "???" else "??"
    colour = monogram_colour(code)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([0, 0, size - 1, size - 1], fill=colour + (255,))
    bbox = draw.textbbox((0, 0), initials, font=FONT_SM)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) // 2, (size - th) // 2 - 1), initials, font=FONT_SM, fill=(255, 255, 255, 255))

    _logo_cache[cache_key] = img
    return img


# ── DISPLAY HELPERS ───────────────────────────────────────────────────────────
def draw_text(draw, x, y, text, font, color, max_width=None):
    if max_width:
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


# ── PAGE 1: LOGO + CALLSIGN + TYPE ────────────────────────────────────────────
def render_page1(ac, route, frame=0):
    img  = Image.new("RGB", (MATRIX_WIDTH, MATRIX_HEIGHT), BLACK)
    draw = ImageDraw.Draw(img)

    callsign = ac.get("callsign", "?")
    ac_type  = short_aircraft_type(ac.get("model", ""))
    airline_name = route.get("airline", {}).get("name") if route else None

    logo = get_logo(callsign, airline_name, size=20)
    img.paste(logo, (2, 6), logo)

    draw_text(draw, 25, 3, callsign, FONT_LG, CYAN, max_width=37)

    if ac_type:
        draw.text((25, 14), ac_type, font=FONT_MED, fill=AMBER)

    name = airline_name or "Unknown airline"
    full = name[:30]
    if len(full) > 10:
        scroll_offset = (frame // 3) % max(1, len(full) - 9)
        visible = full[scroll_offset:scroll_offset + 10]
    else:
        visible = full
    draw.line([(0, 24), (MATRIX_WIDTH, 24)], fill=DIM)
    draw.text((2, 26), visible, font=FONT_SM, fill=GREY)

    return img


# ── PAGE 2: ROUTE + ALT + SPEED ───────────────────────────────────────────────
def render_page2(ac, route, frame=0):
    img  = Image.new("RGB", (MATRIX_WIDTH, MATRIX_HEIGHT), BLACK)
    draw = ImageDraw.Draw(img)

    callsign = ac.get("callsign", "?")
    draw_text(draw, 1, 1, callsign, FONT_SM, CYAN, max_width=36)

    now = datetime.now().strftime("%H:%M")
    t_bbox = draw.textbbox((0, 0), now, font=FONT_SM)
    t_w = t_bbox[2] - t_bbox[0]
    draw.text((MATRIX_WIDTH - t_w - 1, 2), now, font=FONT_SM, fill=GREY)

    draw.line([(0, 9), (MATRIX_WIDTH, 9)], fill=DIM)

    if route and route.get("origin") and route.get("destination"):
        origin = route["origin"].get("iata_code") or route["origin"].get("icao_code", "???")
        dest   = route["destination"].get("iata_code") or route["destination"].get("icao_code", "???")

        draw.text((2, 12), origin, font=FONT_LG, fill=WHITE)
        o_bbox = draw.textbbox((0, 0), origin, font=FONT_LG)
        o_w = o_bbox[2] - o_bbox[0]

        draw.text((2 + o_w + 3, 13), "->", font=FONT_SM, fill=GREY)
        arrow_bbox = draw.textbbox((0, 0), "->", font=FONT_SM)
        arrow_w = arrow_bbox[2] - arrow_bbox[0]

        draw.text((2 + o_w + 3 + arrow_w + 3, 12), dest, font=FONT_LG, fill=WHITE)
    else:
        model = ac.get("model", "")
        text = model[:16] if model and model != "Unknown" else "Route unknown"
        draw.text((2, 14), text, font=FONT_SM, fill=GREY)

    draw.line([(0, 22), (MATRIX_WIDTH, 22)], fill=DIM)

    alt   = format_alt(ac.get("alt_baro"))
    speed = format_speed(ac.get("ground_speed"))
    arrow = vert_rate_arrow(ac.get("vert_rate"))

    draw.text((2, 24), f"{arrow}{alt}", font=FONT_SM, fill=AMBER)

    spd_bbox = draw.textbbox((0, 0), speed, font=FONT_SM)
    spd_w = spd_bbox[2] - spd_bbox[0]
    draw.text((MATRIX_WIDTH - spd_w - 2, 24), speed, font=FONT_SM, fill=GREEN)

    return img


# ── IDLE SCREEN ────────────────────────────────────────────────────────────────
def render_idle_frame(frame=0):
    img  = Image.new("RGB", (MATRIX_WIDTH, MATRIX_HEIGHT), BLACK)
    draw = ImageDraw.Draw(img)

    brightness = int(40 + 30 * math.sin(frame * 0.15))
    pulse_col  = (0, brightness, brightness + 20)

    draw.ellipse([28, 8, 36, 16], outline=pulse_col)
    draw.ellipse([30, 10, 34, 14], fill=pulse_col)

    draw.text((8, 18), "NO AIRCRAFT", font=FONT_SM, fill=DIM)

    now = datetime.now().strftime("%H:%M")
    t_bbox = draw.textbbox((0, 0), now, font=FONT_SM)
    t_w = t_bbox[2] - t_bbox[0]
    draw.text(((MATRIX_WIDTH - t_w) // 2, 25), now, font=FONT_SM, fill=GREY)

    return img


# ── MAIN LOOP ─────────────────────────────────────────────────────────────────
def main():
    try:
        from rgbmatrix import RGBMatrix, RGBMatrixOptions
    except ImportError:
        log.error("rpi-rgb-led-matrix not installed. See setup guide.")
        log.info("Running in PREVIEW mode — saving frames as PNGs")
        run_preview_mode()
        return

    options = RGBMatrixOptions()
    options.rows                      = 32
    options.cols                      = 64
    options.chain_length              = 1
    options.parallel                  = 1
    options.hardware_mapping          = "adafruit-hat"
    options.gpio_slowdown             = 4
    options.brightness                = ACTIVE_BRIGHTNESS
    options.disable_hardware_pulsing  = True
    options.drop_privileges           = False

    matrix = RGBMatrix(options=options)
    canvas = matrix.CreateFrameCanvas()

    log.info("FlightWall starting…")

    aircraft_list = []
    route_map     = {}
    last_poll     = 0
    ac_index      = 0
    page          = 1            # 1 or 2
    frame         = 0
    page_frames   = PAGE_DWELL_TIME * 10  # at ~10fps

    while True:
        now = time.time()

        if now - last_poll > POLL_INTERVAL:
            log.info("Polling for aircraft…")
            aircraft_list = fetch_aircraft()
            log.info(f"Found {len(aircraft_list)} aircraft overhead")
            last_poll = now
            ac_index  = 0
            page      = 1

            for ac in aircraft_list:
                cs = ac.get("callsign")
                if cs and cs not in route_map:
                    route = get_route(cs)
                    route_map[cs] = route
                    if route:
                        o = route.get("origin", {}).get("iata_code", "?")
                        d = route.get("destination", {}).get("iata_code", "?")
                        log.info(f"  {cs}: {o} → {d}")

        if not aircraft_list:
            img = render_idle_frame(frame)
        else:
            if frame > 0 and frame % page_frames == 0:
                if page == 1:
                    page = 2
                else:
                    page = 1
                    ac_index = (ac_index + 1) % len(aircraft_list)

            ac    = aircraft_list[ac_index]
            route = route_map.get(ac.get("callsign"))
            img   = render_page1(ac, route, frame) if page == 1 else render_page2(ac, route, frame)

        canvas.SetImage(img)
        canvas = matrix.SwapOnVSync(canvas)

        frame += 1
        time.sleep(0.1)


def run_preview_mode():
    log.info("Fetching aircraft for preview…")
    aircraft_list = fetch_aircraft()

    if not aircraft_list:
        log.info("No aircraft overhead — rendering idle screen")
        img = render_idle_frame(0)
        img.resize((MATRIX_WIDTH * 6, MATRIX_HEIGHT * 6), Image.NEAREST).save("preview_idle.png")
        log.info("Saved preview_idle.png")
        return

    for i, ac in enumerate(aircraft_list[:3]):
        cs    = ac.get("callsign", "TEST")
        route = get_route(cs)

        img1 = render_page1(ac, route, 0)
        img1.resize((MATRIX_WIDTH * 6, MATRIX_HEIGHT * 6), Image.NEAREST).save(f"preview_{i+1}_{cs}_page1.png")

        img2 = render_page2(ac, route, 0)
        img2.resize((MATRIX_WIDTH * 6, MATRIX_HEIGHT * 6), Image.NEAREST).save(f"preview_{i+1}_{cs}_page2.png")

        log.info(f"Saved preview_{i+1}_{cs}_page1.png and page2.png")


if __name__ == "__main__":
    main()
