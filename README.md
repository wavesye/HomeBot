# Homebot

English | [简体中文](README.zh-CN.md)

Homebot is a Raspberry Pi based home robot project for remote control, video monitoring and autonomous robotics experiments.

Current version: **v0.7.1**

---

## See It in Action

<table>
  <tr>
    <td align="center"><b>Camera & Speed Control</b></td>
    <td align="center"><b>Camera Demo</b></td>
    <td align="center"><b>Driving Demo</b></td>
  </tr>
  <tr>
    <td><img src="assets/AppManual.gif" width="300"></td>
    <td><img src="assets/CameraView.gif" width="300"></td>
    <td><img src="assets/HumanView.gif" width="200"></td>
  </tr>
</table>

Current features:

- Browser remote control
- Mobile control over local Wi-Fi
- Camera preview
- Dual motor drive
- Independent left/right PWM calibration
- Heartbeat + Watchdog safety stop
- Mock motor mode for development without hardware

---

## Quick Start

### Install

```bash
git clone https://github.com/wavesye/HomeBot.git
cd HomeBot

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### Run on your computer

```bash
python -m server.run
```

Open:

```text
http://localhost:8000
```

The default mode uses a virtual motor, so no Raspberry Pi is required.

### Run on Raspberry Pi

```bash
python -m server.run --lan --motor drv8833-dual
```

With Raspberry Pi CSI Camera:

```bash
python -m server.run \
  --lan \
  --motor drv8833-dual \
  --camera picamera2
```

---

## How It Works

```text
Browser
   │
   ▼
JavaScript
   │
   │ HTTP
   ▼
FastAPI
   │
   ▼
Motor Controller
   │
   ▼
Raspberry Pi GPIO
   │
   ▼
DRV8833
   │
   ├── Left Motor
   └── Right Motor
```

A movement command follows this path:

```text
Forward
   ↓
POST /api/move
   ↓
FastAPI
   ↓
Motor Controller
   ↓
DRV8833
   ↓
Motors
```

The browser also sends periodic heartbeats while the robot is moving.

```text
Move
 ↓
command_id
 ↓
Heartbeat
 ↓
Watchdog
 ↓
Heartbeat lost
 ↓
STOP
```

If the browser disconnects or heartbeats stop, the backend automatically stops the motors.

### Project Structure

```text
HomeBot/
├── server/
│   ├── main.py       # API, control state and watchdog
│   ├── run.py        # Server startup
│   ├── camera.py     # Camera
│   ├── motor.py      # Motor abstraction
│   ├── drv8833.py    # Single motor driver
│   └── drive.py      # Dual motor control
│
├── web/
│   ├── index.html
│   ├── style.css
│   └── app.js        # Controls, heartbeat and camera
│
├── tests/
├── docs/
└── README.md
```

---

## Hardware Setup

### Hardware

| Component     | Choice                               | Purpose                  |
| ------------- | ------------------------------------ | ------------------------ |
| Main computer | Raspberry Pi 4B                      | Runs Homebot backend     |
| Motor driver  | DRV8833                              | Drives two DC motors     |
| Motors        | 2 × DC geared motors                 | Differential drive       |
| Camera        | Raspberry Pi CSI Camera / USB Camera | Video preview            |
| Pi power      | USB power bank                       | Powers Raspberry Pi      |
| Motor power   | AA battery pack                      | Independent motor supply |
| Chassis       | Two-wheel robot chassis              | Robot platform           |

The Raspberry Pi and motors use separate power supplies, while the Raspberry Pi and DRV8833 share a common ground.

### Wiring

Basic architecture:

```text
                 ┌────────────────────┐
                 │  Raspberry Pi 4B   │
                 │                    │
                 │ GPIO ──────────────┼──────────────┐
                 │                    │              │
                 │ GND ───────────────┼──────────┐   │
                 └────────────────────┘          │   │
                                                 │   │
                                      ┌──────────▼───▼──────┐
                                      │      DRV8833        │
                                      │                     │
                         Motor Power ─▶│ VM                  │
                                      │                     │
                                      │ AOUT1 / AOUT2       │
                                      │      │              │
                                      │      ▼              │
                                      │  Left Motor         │
                                      │                     │
                                      │ BOUT1 / BOUT2       │
                                      │      │              │
                                      │      ▼              │
                                      │  Right Motor        │
                                      └─────────────────────┘
```

Power layout:

```text
USB Power Bank
      │
      ▼
Raspberry Pi

AA Battery Pack
      │
      ▼
DRV8833
      │
      ├── Left Motor
      └── Right Motor

Raspberry Pi GND ───── DRV8833 GND
```

Camera:

```text
Raspberry Pi
     │
     │ CSI
     ▼
Camera Module
```

Detailed GPIO pin assignments and hardware testing procedures are kept in local documentation (excluded from this repository):

```text
docs/
├── v0.6-bench.md
├── v0.7-drive.md
├── v0.7.1-calibration.md
└── pi-camera.md
```

This README only shows the overall hardware architecture. Obtain and follow the detailed wiring documentation before powering the motors.

---

## Built With

### Software

- **Python**
- **FastAPI**
- **Uvicorn**
- **HTML / CSS / JavaScript**
- **OpenCV**
- **Picamera2**

### Hardware

- **Raspberry Pi**
- **DRV8833**
- **GPIO Zero / lgpio**
- **CSI / USB Camera**
- **DC geared motors**

### Core Concepts

Homebot currently uses several mechanisms that will also be useful for later autonomous control:

```text
REST API
Motor abstraction
Heartbeat
Watchdog
Control epoch
Camera input
PWM motor control
```

The separation between the web interface, control logic and hardware drivers makes it possible to replace manual control with higher-level control algorithms later.

---

## What's Next

```text
Remote Control
      ↓
Camera
      ↓
Dual Motor Drive
      ↓
PWM Calibration
      ↓
Video Streaming
      ↓
Computer Vision
      ↓
Autonomous Driving
      ↓
Navigation
```
