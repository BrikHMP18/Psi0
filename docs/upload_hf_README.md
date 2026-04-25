# Upload G1 Data to Hugging Face in LeRobot Format

Runs after `docs/record_data_README.md`.

## 0. Inputs

```text
real/teleop/data/<task_set>/<category>/<task>/episode_0/data.json
real/teleop/data/<task_set>/<category>/<task>/episode_1/data.json
```

```bash
export TASK_SET=wbcd_pilot
export CATEGORY=logistics
export TASK=pick_item_from_top_shelf_and_place_into_cart
```

`TASK` must match the sanitized folder name created by `taskcreator.py`.

## 1. Environment

Uses the project's canonical `.venv-psi` (see main `README.md` → Installation). All deps (`pandas`, `pyarrow`, `huggingface_hub`, `imageio`) are pulled by `uv sync --all-groups`.

```bash
cd ./Psi0
source .venv-psi/bin/activate

cp .env.sample .env   # set PSI_HOME and HF_TOKEN
set -a; source .env; set +a
```

## 2. Register task description

`raw_to_lerobot.py` requires `scripts/data/task_description_dict.json` to contain the exact `TASK` key.

```bash
export RAW_CATEGORY_DIR="$PWD/real/teleop/data/$TASK_SET/$CATEGORY"

python - <<'PY'
import json, os
from pathlib import Path

task = os.environ["TASK"]
metadata = Path(os.environ["RAW_CATEGORY_DIR"]) / task / "metadata" / "metadata.json"
description = json.loads(metadata.read_text())["description"]

path = Path("scripts/data/task_description_dict.json")
data = json.loads(path.read_text()) if path.exists() else {}
data[task] = description
path.write_text(json.dumps(data, indent=4) + "\n")
print(f"registered {task}: {description}")
PY
```

## 3. Convert to LeRobot

`--data-root` is the **category** folder, not the task folder.

```bash
export OUT_ROOT="$PSI_HOME/data/real"
mkdir -p "$OUT_ROOT"

python scripts/data/raw_to_lerobot.py \
  --data-root="$RAW_CATEGORY_DIR" \
  --work-dir="$OUT_ROOT" \
  --robot-type=g1 \
  --task="$TASK" \
  --num-workers=4
```

Output:

```text
$OUT_ROOT/$TASK/
├── data/chunk-000/episode_000000.parquet
├── videos/chunk-000/egocentric/episode_000000.mp4
└── meta/
```

## 4. Stats and patch

```bash
python scripts/data/calc_modality_stats.py --task-dir="$OUT_ROOT/$TASK"
cp "$OUT_ROOT/$TASK/meta/stats.json" "$OUT_ROOT/$TASK/meta/stats_psi0.json"
python scripts/data/patch_lerobot_meta.py "$OUT_ROOT/$TASK"
```

## 5. Quick validation

```bash
python - <<'PY'
import json, os
from pathlib import Path
import pandas as pd

root = Path(os.environ["OUT_ROOT"]) / os.environ["TASK"]
for f in ("info.json", "episodes.jsonl", "tasks.jsonl", "stats.json"):
    assert (root / "meta" / f).is_file(), f

parquets = sorted((root / "data").glob("*/*.parquet"))
videos = sorted((root / "videos").glob("*/*/*.mp4"))
assert parquets and videos

df = pd.read_parquet(parquets[0])
required = {"states", "action", "timestamp", "frame_index", "episode_index", "task_index", "next.done"}
missing = required.difference(df.columns)
assert not missing, f"missing columns: {missing}"

info = json.loads((root / "meta" / "info.json").read_text())
print(f"OK: {root} (episodes={info['total_episodes']} frames={info['total_frames']})")
PY
```

## 6. Upload to Hugging Face

```bash
export HF_REPO_ID="<your-hf-user-or-org>/$TASK"
export HF_PRIVATE=0   # omit or set to 1 for private

python - <<'PY'
import os
from pathlib import Path
from huggingface_hub import create_repo, create_tag, upload_large_folder

repo_id = os.environ["HF_REPO_ID"]
folder = Path(os.environ["OUT_ROOT"]) / os.environ["TASK"]
private = os.environ.get("HF_PRIVATE", "1") not in {"0", "false", "False", "no", "NO"}

create_repo(repo_id, repo_type="dataset", private=private, exist_ok=True)
upload_large_folder(repo_id=repo_id, repo_type="dataset", folder_path=str(folder))

try:
    create_tag(repo_id, tag="v2.1", repo_type="dataset")
except Exception as exc:
    print(f"tag skipped: {exc}")

print(f"https://huggingface.co/datasets/{repo_id}")
PY
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `Task description is empty` | Add the exact `TASK` key to `scripts/data/task_description_dict.json`. |
| `No episodes matched robot type 'g1'` | Each raw `episode_N/data.json` must have `"robot_type": "g1"`. |
| Converter finds no episodes | `--data-root` should be the category folder, not the task folder. |
| Upload auth fails | Reload `.env` with `set -a; source .env; set +a`; verify `HF_TOKEN` has write access. |
