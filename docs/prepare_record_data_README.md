# Recording Data on Unitree G1

Recording-only. LeRobot conversion is in `docs/upload_hf_README.md`.

Assumes Ubuntu 22.04+, `conda`, `uv`, `git`, `git-lfs`, `build-essential`, plus FFmpeg dev headers (PyAV builds from source):

```bash
sudo apt install -y ffmpeg pkg-config \
    libavdevice-dev libavfilter-dev libavformat-dev \
    libavcodec-dev libavutil-dev libswscale-dev libswresample-dev
```

## TL;DR

```bash
# Terminal A — on G1 onboard PC, over SSH
conda activate vision && python realsense_server.py
```

```bash
# Terminal B — on the laptop, from ./Psi0
cd real/teleop
conda activate psi_deploy
export CYCLONEDDS_URI="<CycloneDDS><Domain><General><NetworkInterfaceAddress>192.168.123.123</NetworkInterfaceAddress></General></Domain></CycloneDDS>"
python main.py --robot g1 --pico_streamer
# s = start | q = save | d = discard | exit = quit
```

Defaults: `--pico_ip 192.168.0.128`, `--task_name default_task`.

## 1. Clone

Pick a workspace where Psi0 and its sibling repos live side by side.

```bash
cd "$WORKSPACE"
git clone https://github.com/BrikHMP18/Psi0.git
cd Psi0
git submodule update --init --recursive
```

## 2. Conda env

```bash
cd real
conda env create -f psi_deploy_env.yaml
conda activate psi_deploy
cd ..
```

The YAML omits two things you also need.

GStreamer plugins (required for `--pico_streamer`):

```bash
conda install -y -c conda-forge \
    pygobject gobject-introspection gst-python \
    gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-plugins-ugly x264
```

A libstdc++ activate hook (XRoboToolkit's `.so` causes `CXXABI_1.3.15 not found`):

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

## 3. Unitree SDK2 — Python (lab fork)

```bash
cd ..
git clone git@github.com:physical-superintelligence-lab/unitree_sdk2_python.git
cd unitree_sdk2_python && pip install -e . && cd ../Psi0
```

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

Verify: `python -c "import xrobotoolkit_sdk as xrt; xrt.init(); xrt.close(); print('xrt OK')"`

Also install **XRoboToolkit-PC-Service** on the laptop (https://github.com/XR-Robotics).

## 5. real/ package

```bash
cd real && pip install -e . && cd ..
```

## 6. Env file

```bash
cp .env.sample .env
# Set PSI_HOME to a writable path with ≥ 50 GB free.
source .env
```

## 7. Network

Wired LAN required — DDS over Wi-Fi is unreliable.

```bash
ip a                                     # find wired interface name
sudo ip addr add 192.168.123.123/24 dev <IFACE>
ping -c 3 192.168.123.164                # G1 PC
export CYCLONEDDS_URI="<CycloneDDS><Domain><General><NetworkInterfaceAddress>192.168.123.123</NetworkInterfaceAddress></General></Domain></CycloneDDS>"
```

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

The server binds `192.168.123.164:5556` (hardcoded in `realsense_server.py`).

## 9. PICO headset

1. Install **XRoboToolkit-Unity-Client** APK on the PICO (https://github.com/XR-Robotics/XRoboToolkit-Unity-Client/releases).
2. PICO + laptop on the same Wi-Fi.
3. PICO app: enable **Head**, **Controller**, **Hand** under Tracking Session, toggle **Send** on.
4. Under **Remote Vision Session**, select `ZEDMINI`, click **Listen**, enter the laptop's IP.
5. Note the PICO IP — pass it as `--pico_ip` if not `192.168.0.128`.
6. Put controllers down; PICO auto-switches to hand tracking.

## 10. Smoke tests

RealSense:
```bash
python -c "
import zmq
s = zmq.Context().socket(zmq.REQ); s.connect('tcp://192.168.123.164:5556')
s.send(b''); p = s.recv_multipart()
print(f'rgb={len(p[0])} ir={len(p[1])} depth={len(p[2])}')"
```

PICO:
```bash
python -c "
import xrobotoolkit_sdk as xrt, time
xrt.init(); time.sleep(0.5); print(xrt.get_headset_pose()); xrt.close()"
```

G1 DDS (robot powered, dev mode `L2+B` then `L2+R2`, suspended):
```bash
python -c "
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
ChannelFactoryInitialize(0); print('DDS OK')"
```

## 11. Task metadata

Episodes are written into `real/teleop/data/<task_set>/<category>/<task>/episode_N/`. The tree comes from `task_defs/*.json` processed by `taskcreator.py` — not from `--task_name` (which is only a log label).

1. Edit or copy `real/teleop/task_defs/example.json` → `real/teleop/task_defs/<task_set>.json`. A 3-task pilot is provided in `task_defs/wbcd_pilot.json`.
2. Generate the metadata tree:

```bash
cd real/teleop
python taskcreator.py
ls data/   # one top-level dir per task_defs/<name>.json
```

Verify `data/<task_set>/<category>/<task>/metadata/metadata.json` exists.

## 12. No Dex3-1 hands attached

Pipeline still runs. PICO hand skeleton is captured; Dex3 commands are computed and written to `data.json` under `actions.right_angles` / `actions.left_angles`. Robot motors ignore them. Data is reusable when Dex3 arrives. Dex3 motor warnings are expected.

## 13. Record

> Safety: keep distance. Power on and enter dev mode: `L2 + B` then `L2 + R2` (older firmware: `L1 + A` then `L2 + R2`). Hang the G1 from a rig so the feet barely touch the ground before launching teleop.

```bash
cd real/teleop
conda activate psi_deploy
export CYCLONEDDS_URI="<CycloneDDS><Domain><General><NetworkInterfaceAddress>192.168.123.123</NetworkInterfaceAddress></General></Domain></CycloneDDS>"
python main.py --robot g1 --pico_streamer --task_name pilot_pick
```

### Pre-record validation (do not press `s` yet)

The teleop loop runs continuously from launch — `s` only starts writing to disk. Validate the full stack first:

1. Robot stands up in ready pose.
2. Terminal prints `master and worker waiting for starting signal`.
3. Don the headset and confirm the G1 RealSense POV is visible.
4. Virtual hands appear around your real hands (PICO hand tracking active).
5. Slowly move your arms — the robot mirrors them.

Recording with a broken teleop loop produces unusable episodes.

### Recording commands

| Key | Action |
|---|---|
| `s` | Start episode (or the next one after `q`/`d`). |
| `q` | Save + stop. Master merges `robot_data.jsonl` + `ik_data.jsonl` → `data.json`. Press `s` for the next episode. |
| `d` | Discard + stop. Merge skipped; orphan `episode_N/` auto-deleted on the next `s`. |
| `exit` | Shutdown. |

No mid-episode pause. To pause, press `q` (save) or `d` (discard); `s` afterwards starts a new episode.

Output after `q`:

```
real/teleop/data/<task_set>/<category>/<task>/episode_N/
├── color/frame_NNNNNN.jpg
├── depth/frame_NNNNNN.npy.lzma
├── robot_data.jsonl
├── ik_data.jsonl
└── data.json
```

~2–4 GB per 5-min episode. Target: 40 episodes per task.

## 14. Troubleshooting

| Symptom | Fix |
|---|---|
| `Failed to build 'av'` / `No package 'libavdevice' found` | Missing FFmpeg dev headers. Install the apt packages at the top, then `conda env update -n psi_deploy -f real/psi_deploy_env.yaml`. |
| `ImportError: ... CXXABI_1.3.15 not found` | libstdc++ activate hook from §2 not applied. |
| `ModuleNotFoundError: No module named 'gi'` / `no element "x264enc"` | GStreamer plugins from §2 missing. |
| `s` crashes with `TypeError: ... NoneType` on `os.makedirs` | §11 not run. Run `python taskcreator.py`. |
| `data.json` not created after episode | You pressed `d`, or master crashed. Check the `.jsonl` files; run `python -m teleop.merger <episode_dir>` manually if needed. |
| `--help` only shows `Vuer.*` args | Cosmetic — Vuer hijacks argparse on import. The args still work. |
| ZMQ smoke test hangs | `realsense_server.py` not running, or 5556 blocked on G1 PC. |
| PICO not detected | Same Wi-Fi, "Send" toggle, restart XRoboToolkit-PC-Service. |
| DDS silent | `CYCLONEDDS_URI` not exported in this shell. |
