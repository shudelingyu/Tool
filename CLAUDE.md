# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

This is a robotics/industrial tool suite for managing surgical robotic arms. It consists of several independent Python desktop applications, each packaged into standalone EXEs via PyInstaller (visible in each tool's `dist/` folder with `_internal` directories).

There is no build system, package manager, or virtual environment — each script is a standalone entry point. The launcher (`launcher/launcher.py`) is the central hub that discovers and launches all other tools.

## Tools and their purposes

| Tool | Entry point | GUI framework | Key capability |
|------|-----------|--------------|----------------|
| **launcher** | `launcher/launcher.py` | customtkinter | Tool management panel; discovers and launches tools via `programs.json` |
| **xmlTool** | `xmlTool/xmltool.py` | tkinter (ttk) | Batch CRUD on XML `<variable>` elements, local or via SSH |
| **instTool** | `instTool/InstTool.py` | tkinter | TCP socket control of robotic instruments; camera preview via OpenCV |
| **jointMonitor** | `jointMonitor/JointMonitor.py` | tkinter (ttk) | SSH-based real-time joint angle monitoring; saves to `.cst` files |
| **logAnalysis** | `logAnalysis/logAnalysis.py` | PyQt5 + pyqtgraph | Offline/online log parsing, plotting with drag-and-drop, parquet caching |

The `data/` directory stores `.cst` joint angle files (space-delimited text with a header line) consumed by `jointMonitor`.

## Shared patterns

- **SSH**: `xmlTool`, `jointMonitor`, and `logAnalysis` all use `paramiko` for SSH connections. Each defines its own `SSHClient` wrapper class — they are NOT shared; changes to one do not affect others.
- **Threading**: All GUI tools run blocking I/O (SSH, TCP, file loading) in `threading.Thread(daemon=True)` threads and marshal results back to the main thread via `root.after(0, callback)` (tkinter) or `pyqtSignal` (PyQt5).
- **Remote log paths**: `jointMonitor` and `logAnalysis` both read from `/data/log/rt/` on remote Linux machines. `jointMonitor` reads `mmsArm{N}/mmsArm{N}` and `{Name}DataModel/{Name}DataModel`. `logAnalysis` reads the same paths plus `mmsBoom/mmsBoom` and `LOUT/LOUT`.
- **Encoding handling**: `xmlTool` uses `chardet` to detect encoding of XML files before reading. `logAnalysis` uses `utf-8` with `errors='ignore'`.

## Key dependencies (no requirements.txt exists)

- `paramiko` — SSH for xmlTool, jointMonitor, logAnalysis
- `chardet` — encoding detection for xmlTool
- `PyQt5` + `pyqtgraph` + `pandas` + `numpy` + `pyarrow` — logAnalysis
- `opencv-python` (cv2) + `Pillow` — instTool camera
- `customtkinter` — launcher

## Running individual tools

All tools are run directly as Python scripts:

```bash
python launcher/launcher.py        # Launcher panel
python xmlTool/xmltool.py          # XML parameter tool
python instTool/InstTool.py        # Instrument control
python jointMonitor/JointMonitor.py # Joint monitor
python logAnalysis/logAnalysis.py  # Log analysis platform
```

There are no tests, linters, or CI configured in this repository.

## Data format reference

- **`.cst` files** (jointMonitor output): Space-delimited text. First line is a header (e.g., `name J1 J2 J3 J4 J5 J6 J7 J8`). Subsequent lines are `prefix: val1 val2 ... valN` where prefix is `actpos`, `addlpos`, or `view_angle`.
- **XML variable format** (xmlTool): `<variable name="Name">value</variable>` inside container elements like `<MtmObject>`, `<PsmObject>`, `<ControllerObject>`, `<MotionObject>`.
- **Log line format** (logAnalysis): `[YYYY-MM-DD HH:MM:SS.ffffff] data...` where data is either comma-separated (slave/boom: 142 or 92 fields; 36 fields for boom) or space-separated key-value pairs (master: `cur_q`, `cur_qabs`, `tar_q`, etc.). ADS lines use `[ADS]:<model>,key:val1,val2` format.

## EXE packaging

Each tool's `dist/` directory contains a PyInstaller-built EXE with all dependencies bundled in `_internal/`. When modifying source, the corresponding EXE must be rebuilt with PyInstaller to take effect. The launcher's `programs.json` points to these EXE paths.
