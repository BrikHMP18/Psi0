# Recording Data on Unitree G1

Setup for collecting teleop episodes from any Ubuntu laptop. Recording itself does not use the GPU — works on NVIDIA, AMD, or integrated graphics. Recording-only; LeRobot conversion and training are out of scope.

Assumes you already have: Ubuntu 22.04+, `conda`, `uv`, `git`, `git-lfs`, `build-essential`.

System libs required by PyAV (compiled from source during section 2):

```bash
sudo apt install -y ffmpeg pkg-config \
    libavdevice-dev libavfilter-dev libavformat-dev \
    libavcodec-dev libavutil-dev libswscale-dev libswresample-dev
```

> **Order matters.** Run sections 1 → 9 once (install). Section 10 is smoke tests. Section 12 is the recording session you run every time after that. The TL;DR below only works **after** sections 1–9 are done.

---

## 0. TL;DR (only works after install is complete)

```bash
# Terminal A — on G1 onboard PC, over SSH
conda activate vision && python realsense_server.py
```

```bash
# Terminal B — on the laptop, from the repo root (./Psi0)
cd real/teleop
conda activate psi_deploy
export CYCLONEDDS_URI="<CycloneDDS><Domain><General><NetworkInterfaceAddress>192.168.123.123</NetworkInterfaceAddress></General></Domain></CycloneDDS>"
python main.py --robot g1 --pico_streamer
# s = start | q = save | d = discard | exit = quit
```

`--pico_ip` defaults to `192.168.0.128` and `--task_name` to `default_task`. Override with `--pico_ip 192.168.X.Y` and `--task_name my_task` when needed.

---

## 1. Clone

Pick any workspace directory (`$WORKSPACE`) where Psi0 and its sibling repos will live side by side. Subsequent sections assume this layout.

```bash
cd "$WORKSPACE"
git clone https://github.com/BrikHMP18/Psi0.git
cd Psi0
git submodule update --init --recursive
```

---

## 2. Conda env

```bash
cd real
conda env create -f psi_deploy_env.yaml
conda activate psi_deploy
cd ..
```

The env bundles `torch+cuda` wheels; they install on AMD/integrated GPUs and silently run CPU-only. Recording does not use the GPU.

### 2a. Missing deps not in the YAML

The YAML omits `pygobject` and the GStreamer plugins. `worker.py:96-103` uses `appsrc → videoconvert → x264enc → h264parse → appsink`, which need plugins-base/good/bad/ugly plus x264:

```bash
conda install -y -c conda-forge \
    pygobject gobject-introspection gst-python \
    gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-plugins-ugly x264
```

Without the plugins, `import worker` works but `--pico_streamer` fails inside `Gst.parse_launch()`.

### 2b. libstdc++ activate hook (required)

XRoboToolkit's `.so` is linked against the system `libstdc++` and pins it before `pinocchio` loads, causing `CXXABI_1.3.15 not found`. Force the env's libstdc++ on every activate:

```bash
mkdir -p "$CONDA_PREFIX/etc/conda/activate.d" "$CONDA_PREFIX/etc/conda/deactivate.d"

cat > "$CONDA_PREFIX/etc/conda/activate.d/libstdcxx.sh" <<'EOF'
export _PSI_OLD_LD_PRELOAD="${LD_PRELOAD:-}"
if [ -n "${LD_PRELOAD:-}" ]; then
  export LD_PRELOAD="$CONDA_PREFIX/lib/libstdc++.so.6:$LD_PRELOAD"
else
  export LD_PRELOAD="$CONDA_PREFIX/lib/libstdc++.so.6"
fi
EOF

cat > "$CONDA_PREFIX/etc/conda/deactivate.d/libstdcxx.sh" <<'EOF'
if [ -n "${_PSI_OLD_LD_PRELOAD+x}" ]; then
  if [ -n "$_PSI_OLD_LD_PRELOAD" ]; then
    export LD_PRELOAD="$_PSI_OLD_LD_PRELOAD"
  else
    unset LD_PRELOAD
  fi
  unset _PSI_OLD_LD_PRELOAD
fi
EOF

conda deactivate && conda activate psi_deploy
```

---

## 3. Unitree SDK2 — Python (lab fork)

The repo's `real/README.md:24` instructs installing the lab's fork (`physical-superintelligence-lab/unitree_sdk2_python`) without explaining what differs from the official. Use it as the reference path. If you already have the official `unitreerobotics/unitree_sdk2_python` working, try it first and only switch to the fork if you hit import or message-type mismatches.

```bash
cd ..
git clone git@github.com:physical-superintelligence-lab/unitree_sdk2_python.git
cd unitree_sdk2_python && pip install -e . && cd ../Psi0
```

---

## 4. XRoboToolkit (PICO SDK)

```bash
cd ..
git clone https://github.com/YanjieZe/XRoboToolkit-PC-Service-Pybind.git
cd XRoboToolkit-PC-Service-Pybind
mkdir -p tmp lib include && cd tmp
git clone https://github.com/XR-Robotics/XRoboToolkit-PC-Service.git
cd XRoboToolkit-PC-Service/RoboticsService/PXREARobotSDK && bash build.sh
cd ../../../..
cp tmp/XRoboToolkit-PC-Service/RoboticsService/PXREARobotSDK/PXREARobotSDK.h include/
cp -r tmp/XRoboToolkit-PC-Service/RoboticsService/PXREARobotSDK/nlohmann include/nlohmann/
cp tmp/XRoboToolkit-PC-Service/RoboticsService/PXREARobotSDK/build/libPXREARobotSDK.so lib/
conda install -y -c conda-forge pybind11
pip uninstall -y xrobotoolkit_sdk
python setup.py install
cd ../Psi0
```

Verify:

```bash
python -c "import xrobotoolkit_sdk as xrt; xrt.init(); xrt.close(); print('xrt OK')"
```

Also install **XRoboToolkit-PC-Service** on the laptop (https://github.com/XR-Robotics).

---

## 5. real/ package

```bash
cd real && pip install -e . && cd ..
```

---

## 6. Env file

```bash
cp .env.sample .env
# Set PSI_HOME to a writable path with ≥ 50 GB free.
# HF_TOKEN / WANDB_* not needed for recording.
source .env
```

---

## 7. Network

```bash
ip a                                     # find wired interface name (e.g. enp4s0)
sudo ip addr add 192.168.123.123/24 dev <IFACE>
ping -c 3 192.168.123.164                # G1 PC
export CYCLONEDDS_URI="<CycloneDDS><Domain><General><NetworkInterfaceAddress>192.168.123.123</NetworkInterfaceAddress></General></Domain></CycloneDDS>"
```

Replace `<IFACE>` with the real interface name from `ip a`. Wired LAN required — DDS over Wi-Fi will not work reliably.

---

## 8. G1 onboard PC: image server

```bash
ssh unitree@192.168.123.164
conda create -n vision python=3.8 -y
conda activate vision
pip install pyrealsense2 opencv-python pyzmq numpy
exit
```

From the laptop:

```bash
scp real/teleop/image_server/realsense_server.py unitree@192.168.123.164:~/
```

On the G1 PC:

```bash
conda activate vision && python realsense_server.py
```

The script binds `192.168.123.164:5556` (hardcoded, `realsense_server.py:74`). Edit that line if your G1 PC IP differs.

---

## 9. PICO headset

1. Install **XRoboToolkit-Unity-Client** APK on the PICO (https://github.com/XR-Robotics/XRoboToolkit-Unity-Client/releases).
2. PICO + laptop on the same Wi-Fi.
3. In the PICO app: enable **Head**, **Controller**, **Hand** under Tracking Session, toggle **Send** on.
4. Under **Remote Vision Session**, select `ZEDMINI`, click **Listen**, and enter the laptop's IP. Without this you won't see the robot's POV inside the headset.
5. Note the PICO IP — pass it as `--pico_ip` in section 12 if it's not `192.168.0.128`.
6. Put controllers down; PICO auto-switches to hand tracking.

---

## 10. Smoke tests

**RealSense:**
```bash
python -c "
import zmq
s = zmq.Context().socket(zmq.REQ); s.connect('tcp://192.168.123.164:5556')
s.send(b''); p = s.recv_multipart()
print(f'rgb={len(p[0])} ir={len(p[1])} depth={len(p[2])}')"
```

**PICO:**
```bash
python -c "
import xrobotoolkit_sdk as xrt, time
xrt.init(); time.sleep(0.5); print(xrt.get_headset_pose()); xrt.close()"
```

**G1 DDS** (robot powered, dev mode `L2+B` then `L2+R2`, suspended):
```bash
python -c "
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
ChannelFactoryInitialize(0); print('DDS OK')"
```

---

## 11. Task metadata (REQUIRED before recording)

`manager.py` writes episodes into `real/teleop/data/<task_json>/<category>/<title>/episode_N/`. That directory tree is **not** chosen by `--task_name` — it comes from `task_defs/*.json` processed by `taskcreator.py`. Without this step, `progress.py:get_next()` returns `None` and `s` (start) crashes on `os.makedirs(None)`.

1. Edit or copy `real/teleop/task_defs/example.json` → `real/teleop/task_defs/<your_set>.json` with your tasks (title, category, objects, description). For WBCD logistics-picking, a 3-task pilot is provided in `real/teleop/task_defs/wbcd_pilot.json`.
2. Generate the metadata tree (processes every JSON in `task_defs/`):

```bash
cd real/teleop
python taskcreator.py
ls data/   # should list every task_defs/<name>.json as a top-level dir
```

Verify `data/<your_set>/<category>/<title>/metadata/metadata.json` exists.

`--task_name` on `main.py` is **only a log label** — it does not select the output folder. The next episode picked is whichever task in `data/` has the most progress and is incomplete (`progress.py:get_next()`).

---

## 13. No Dex3-1 hands attached

Pipeline still runs. PICO hand skeleton is captured (`real/teleop/vr_pico.py:79–80`); Dex3 commands are computed and written to `data.json` under `actions.right_angles` / `actions.left_angles`. Robot motors ignore them. Data is reusable when Dex3 arrives — no re-recording. Dex3 motor warnings in logs are expected.

---

## 14. Record

> ⚠️ **Safety first** (`real/README.md:180-185`): keep distance from the robot. Power it on and enter dev mode with the remote: **`L2 + B`** then **`L2 + R2`** (older firmware: `L1 + A` then `L2 + R2`). **Hang the G1 from a rig so the feet barely touch the ground** before launching teleop.

```bash
cd real/teleop
conda activate psi_deploy
export CYCLONEDDS_URI="<CycloneDDS><Domain><General><NetworkInterfaceAddress>192.168.123.123</NetworkInterfaceAddress></General></Domain></CycloneDDS>"
python main.py --robot g1 --pico_streamer --task_name pilot_pick
```

Add `--pico_ip 192.168.X.Y` if your PICO is not at `192.168.0.128`. `--task_name` is just a log label — the actual task being recorded comes from §11 (task_defs + taskcreator). Wait for `master and worker waiting for starting signal`. Don the headset.

| Key | Action |
|---|---|
| `s` | start episode |
| `q` | save (triggers `merger.py` → `data.json`) |
| `d` | discard (no merge; `.jsonl` files remain orphan) |
| `exit` | shutdown |

**During recording**, `worker.py` writes `robot_data.jsonl` and `master_whole_body.py` writes `ik_data.jsonl`. On `q`, `merger.py` combines them into the final `data.json` (`master_whole_body.py:288`). On `d`, the merge is skipped and the orphan files stay until you delete them or the next session overwrites the directory.

**Output structure (after `q`):**

```
real/teleop/data/<task_json>/<category>/<title>/episode_N/
├── color/frame_NNNNNN.jpg          # 640×480 BGR @ 30 fps
├── depth/frame_NNNNNN.npy.lzma     # numpy uint16, LZMA compressed
├── robot_data.jsonl                # raw state stream (kept)
├── ik_data.jsonl                   # raw IK/action stream (kept)
└── data.json                       # merged, used by raw_to_lerobot.py
```

~2–4 GB per 5-min episode. The `real/README.md:198` target is **40 episodes per task** (also the default in `progress.py:12`).

---

## 15. Troubleshooting

| Symptom | Fix |
|---|---|
| `No such file or directory: Psi0/real/teleop` | You're already inside `Psi0`. Use `cd real/teleop`. |
| `EnvironmentNameNotFound: psi_deploy` | Section 2 hasn't been run yet. The env is created by `conda env create -f real/psi_deploy_env.yaml`. |
| `Failed to build 'av'` / `No package 'libavdevice' found` | Missing FFmpeg dev headers. Install the apt packages listed under "System libs" at the top, then `conda env update -n psi_deploy -f real/psi_deploy_env.yaml`. |
| `Cannot uninstall <pkg> ... no RECORD file` | Conda installed it transitively; pip can't downgrade. `pip install --ignore-installed <pkg>==<version>` then re-run `conda env update`. Repeat per offending package. |
| `ImportError: ... CXXABI_1.3.15 not found` | Section 2b activate hook not applied. Re-run §2b. |
| `ModuleNotFoundError: No module named 'gi'` | Section 2a not run. `conda install -n psi_deploy -c conda-forge pygobject gobject-introspection gst-python -y`. |
| `ImportError: cannot import name 'VR_Pico'` | Wrong class name. Real classes in `vr_pico.py`: `PicoReceiver`, `VuerPreprocessor`, `PicoTeleop`. |
| `--help` only shows `Vuer.*` args | Cosmetic — Vuer hijacks argparse formatter on import. The args (`--robot`, `--task_name`, `--pico_streamer`, `--pico_ip`) are still registered and work. |
| `data.json` not created after episode | You pressed `d` (discard) instead of `q`, or master crashed before merge. Check `robot_data.jsonl` and `ik_data.jsonl` exist; manually run `python -m teleop.merger <episode_dir>` if needed. |
| `s` crashes with `TypeError: expected str, bytes ... got NoneType` on `os.makedirs` | §11 not run. `data/` is empty, `progress.py:get_next()` returned `None`. Run `python taskcreator.py` first. |
| `Gst.parse_launch` fails / `no element "x264enc"` | Section 2a's GStreamer plugins missing. Re-run the full conda install in §2a (includes `gst-plugins-base/good/bad/ugly` + `x264`). |
| `bash: syntax error near unexpected token 'newline'` | You left literal placeholders like `<PICO_IP>` or `<task>` in a command. Replace them with real values, or omit the flag (defaults exist). |
| `ImportError: flash_attn` | Skip `flash_attn` install; training-only |
| OOM / heavy swap | Close browser, dockers; record one episode at a time; lower `OMP_NUM_THREADS` to 4 in `.env` |
| `ping 192.168.123.164` fails | Wrong `<IFACE>` in section 7 |
| ZMQ smoke test hangs | `realsense_server.py` not running, or 5556 blocked on G1 PC |
| PICO not detected | Same Wi-Fi, "Send" toggle, restart XRoboToolkit-PC-Service |
| DDS silent | `CYCLONEDDS_URI` not exported in this shell |
| Dex3 motor errors | Expected when no Dex3 attached |
| `setup.py install` fails (XRoboToolkit) | `conda install -c conda-forge pybind11`; verify `lib/libPXREARobotSDK.so` exists |

---

## Reference files

| Path | Role |
|---|---|
| `real/teleop/main.py` | Entry point (CLI defaults: `--pico_ip 192.168.0.128`, `--task_name default_task`) |
| `real/teleop/manager.py` | Command loop (`s`/`q`/`d`/`exit`) |
| `real/teleop/vr_pico.py` | PICO headset + hand skeleton |
| `real/teleop/image_server/realsense_server.py` | G1 PC, ZMQ:5556 REP |
| `real/teleop/taskcreator.py` | Generates `data/<task>/<cat>/<title>/metadata/` from `task_defs/*.json` (REQUIRED before recording) |
| `real/teleop/progress.py` | `ProgressTracker.get_next()` picks the next episode dir |
| `real/teleop/merger.py` | Merges `robot_data.jsonl` + `ik_data.jsonl` → `data.json` on `q` |
| `real/psi_deploy_env.yaml` | Conda env spec (incomplete — see §2a) |
| `real/README.md` | Original install reference |
| `playbook.md` | WBCD strategy, no-MANUS rationale |
