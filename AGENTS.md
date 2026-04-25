# Repository Guidelines

## Project Structure & Module Organization

This repository contains the Psi0 humanoid VLA model, training scripts, deployment tools, and baseline integrations. Core Python packages live under `src/`, especially `src/psi` for Psi0 model, data, tokenizer, training, and deployment code. Baseline implementations are split between `baselines/` shell wrappers and package code in `src/act`, `src/dp`, `src/gr00t`, `src/openpi`, `src/h_rdt`, `src/egovla`, and `src/InternVLA-M1`. Use `scripts/data/` for LeRobot/raw-data conversion and `scripts/train/psi0/` for Psi0 training entrypoints. Documentation and workflows are in `README.md`, `docs/`, `examples/`, and `real/`. Static media, robot assets, and stats are under `assets/` and `real/assets/`.

## Build, Test, and Development Commands

- `uv venv .venv-psi --python 3.10`: create the expected Python 3.10 environment.
- `source .venv-psi/bin/activate`: activate the local environment.
- `GIT_LFS_SKIP_SMUDGE=1 uv sync --all-groups --index-strategy unsafe-best-match --active`: install root dependencies.
- `python -c "import psi; print(psi.__version__)"`: smoke-test the Psi0 import.
- `python -c "from psi.data.lerobot.compat import LEROBOT_LAYOUT; print(LEROBOT_LAYOUT)"`: verify LeRobot compatibility.
- `bash scripts/train/psi0/finetune-real-psi0.sh <task>` or `bash scripts/train/psi0/finetune-simple-psi0.sh <task>`: launch fine-tuning.
- `uv run --active --group psi --group serve serve_psi0 ...`: serve a trained checkpoint; see `README.md` for full arguments.

## Coding Style & Naming Conventions

Use Python 3.10 syntax, four-space indentation, `snake_case` for functions/modules, and `PascalCase` for classes. Keep CLI scripts and shell wrappers task-oriented, with names matching existing patterns: `finetune-*.sh`, `serve_*.sh`, `raw_to_*.py`. Prefer typed dataclasses/config objects where nearby code uses them. There is no root formatter config; `src/gr00t` uses Ruff with 100-character lines, double quotes, import sorting, and `E/F/I` lint rules.

## Testing Guidelines

There is no central pytest suite at the repository root. For broad validation, use `python scripts/test_regression.py` when required datasets, caches, and GPU runtime are available. For package-specific tests, run the local subproject command, for example `cd src/openpi/openpi-client && uv run pytest`. Add focused tests near the package being changed and use `*_test.py` naming where that package already follows it.

## Commit & Pull Request Guidelines

Recent commits use short, lowercase, descriptive messages such as `fix readme`, `add task_description_dict`, and `fix raw to lerobot script`. Keep commits focused and mention the changed subsystem when helpful. Pull requests should summarize motivation, list commands or smoke tests run, call out dataset/checkpoint assumptions, and include screenshots or logs for visualization, deployment, or training changes.

## Security & Configuration Tips

Copy `.env.sample` to `.env` and keep tokens, cache paths, and W&B credentials local. Do not commit generated data, checkpoints, `.runs`, caches, or machine-specific paths.
