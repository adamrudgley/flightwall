# FlightWall Setup Guide
## 64×32 HUB75 LED Matrix · Pi Zero 2W · Adafruit RGB Matrix Bonnet

---

## Hardware Assembly (No Soldering)

### What you have
- Raspberry Pi Zero 2W (with pre-soldered headers)
- Adafruit RGB Matrix Bonnet (ADA3211)
- 64×32 HUB75 RGB LED matrix panel (2.5mm pitch)
- 5V 4A DC power supply (2.1mm barrel jack)

### Assembly steps

1. **Attach the Bonnet to the Pi Zero**
   - Align the Bonnet's 40-pin female header over the Pi Zero's male GPIO pins
   - Press down firmly and evenly until fully seated
   - The Bonnet should sit flush on top of the Pi Zero

2. **Connect the LED panel to the Bonnet**
   - The panel has a 16-pin HUB75 ribbon cable
   - Connect it to the IDC connector on the Bonnet (labelled HUB75)
   - Pin 1 (red stripe on ribbon) goes to pin 1 on the connector
   - The connector is keyed — it only goes in one way

3. **Connect power**
   - Plug the 5V 4A barrel jack into the Bonnet's power input jack
   - The Bonnet splits power to both the Pi Zero and the LED panel
   - Do NOT also plug a USB cable into the Pi for power — use the barrel jack only

4. **That's it — no soldering required**

---

## Part 1 — Raspberry Pi Zero 2W Setup

### 1.1 Flash Raspberry Pi OS Lite

On your Mac, download **Raspberry Pi Imager** from raspberrypi.com/software

1. Open Imager
2. Choose OS → **Raspberry Pi OS Lite (64-bit)**
3. Choose Storage → your SD card
4. Click the **gear icon** (⚙) and set:
   - Hostname: `flightwall`
   - Enable SSH: yes
   - Username: `pi` / Password: your choice
   - Configure WiFi: your network name and password
   - Locale: Australia/Brisbane
5. Click **Write**

### 1.2 First boot

Insert SD card into Pi Zero, plug in power via the barrel jack.
Wait 60 seconds, then SSH in from your Mac:

```bash
ssh pi@flightwall.local
```

### 1.3 Update the system

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-pillow git libgraphicsmagick++-dev libwebp-dev
```

### 1.4 Install the RGB Matrix library

This is Adafruit's fork of hzeller's rpi-rgb-led-matrix:

```bash
cd ~
git clone https://github.com/adafruit/rpi-rgb-led-matrix.git
cd rpi-rgb-led-matrix

# Build the Python bindings
make build-python PYTHON=$(which python3)
sudo make install-python PYTHON=$(which python3)
```

This takes about 5 minutes on a Pi Zero.

### 1.5 Disable audio (required for the matrix library)

The RGB matrix library uses the same hardware PWM as the Pi's audio.
Audio must be disabled:

```bash
sudo nano /boot/firmware/config.txt
```

Find this line and comment it out:
```
# dtparam=audio=on
```

Save with `Ctrl+O`, `Enter`, `Ctrl+X`, then reboot:

```bash
sudo reboot
```

### 1.6 Install Python dependencies

```bash
pip3 install requests Pillow --break-system-packages
```

---

## Part 2 — Deploy the FlightWall Script

### 2.1 Copy files to the Pi Zero

On your Mac:
```bash
scp flightwall.py pi@flightwall.local:~/flightwall.py
```

### 2.2 Test without the LED matrix first (preview mode)

Before connecting hardware, test the script runs correctly.
On the Pi Zero:

```bash
cd ~
python3 flightwall.py
```

If `rpi-rgb-led-matrix` isn't installed yet, it runs in **preview mode** and saves PNG files — you can SCP these back to your Mac to verify the layout looks right:

```bash
# On Mac
scp pi@flightwall.local:~/preview_*.png ~/Desktop/
```

### 2.3 Test with the LED matrix

Once hardware is connected, run with sudo (required for GPIO access):

```bash
sudo python3 flightwall.py
```

You should see the display light up. If it shows no aircraft, wait up to 3 minutes for new observations to arrive or check the ThinkCentre API is reachable:

```bash
curl http://192.168.68.53:5050/current?radius_km=5
```

### 2.4 Troubleshooting the display

**Flickering or garbled display:**
Open `flightwall.py` and increase `gpio_slowdown`:
```python
options.gpio_slowdown = 4   # try 2, 3, or 4
```

**Display too bright/dim:**
```python
ACTIVE_BRIGHTNESS = 60   # 0-100
```

**Wrong colours:**
Some panels have swapped R/G/B. Try adding to options:
```python
options.led_rgb_sequence = "RBG"   # or "BGR", "GRB"
```

---

## Part 3 — Run as a Service (Auto-start)

### 3.1 Create the systemd service

```bash
sudo tee /etc/systemd/system/flightwall.service > /dev/null << EOF
[Unit]
Description=FlightWall LED Display
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/flightwall.py
Restart=always
RestartSec=10
User=root

[Install]
WantedBy=multi-user.target
EOF
```

### 3.2 Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable flightwall
sudo systemctl start flightwall
```

### 3.3 Check it's running

```bash
sudo systemctl status flightwall
sudo journalctl -u flightwall -f   # watch logs live
```

---

## Part 4 — Update the ThinkCentre

The Pi Zero needs the new `/current` endpoint on your ThinkCentre.
On your Mac:

```bash
# Copy updated receiver.py
scp receiver.py adam@192.168.68.53:~/adsb-tracker/receiver/receiver.py
scp receiver.py adam@192.168.68.53:~/adsb-tracker/thinkcentre/receiver/receiver.py

# Rebuild
ssh adam@192.168.68.53
cd ~/adsb-tracker
docker compose build --no-cache receiver
docker compose up -d receiver
```

Verify the endpoint works:
```bash
curl "http://192.168.68.53:5050/current?radius_km=5&minutes=3"
```

---

## What the Display Shows

```
┌────────────────────────────────────────────────────────────────┐
│ QFA15                                              21:14       │  ← callsign + time
│────────────────────────────────────────────────────────────────│
│ BNE  ->  LAX                                                   │  ← route
│ Qantas                                                         │  ← airline (scrolls)
│────────────────────────────────────────────────────────────────│
│ ↑35k ft                                          480 kts       │  ← altitude + speed
└────────────────────────────────────────────────────────────────┘
```

- **Callsign** — cyan
- **Route** — white, e.g. BNE → LAX
- **Airline** — grey, scrolls if too long
- **Altitude** — amber, with ↑↓→ climb/descent indicator
- **Speed** — green
- **No aircraft** — pulsing dot with clock

Cycles through all overhead aircraft every 8 seconds.
Polls for new aircraft every 30 seconds.

---

## Wiring Reference (Adafruit RGB Matrix Bonnet)

| Component     | Connection              |
|---------------|-------------------------|
| Pi Zero GPIO  | Bonnet 40-pin header    |
| LED Panel     | Bonnet HUB75 IDC port   |
| Power supply  | Bonnet 2.1mm barrel jack|

The Bonnet handles all wiring between the Pi Zero and the panel.
No additional wiring needed.
