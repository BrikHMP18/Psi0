# Playbook — WBCD 2026 Track 1 (Logistics Picking)

Robot: Unitree G1. Flujo: teleop (PICO + trackers) → demos → fine-tune Ψ₀ → deploy con RTC.

## 1. Modelo

**Ψ₀** (este repo). Elegido por:
- Action space 36 DOF nativo G1 (14 hand + 14 arm + 8 lower-body).
- ~80 demos bastan para fine-tune por tarea.
- RTC en `scripts/deploy/serve_psi0-rtc.sh` oculta latencia (~160 ms forward pass).
- Checkpoints pre-entrenados en HF: `USC-PSI-Lab/psi-model`.

Fallbacks: OpenPI π0.5 (`baselines/pi05`) o GR00T N1.6 (`src/gr00t`). Mismo formato LeRobot.

## 2. Hardware

### 2.1 Setup oficial del paper (Fig. 5, §VIII)

| Componente | Rol |
|---|---|
| G1 + Dex3-1 (14 DOF manos) | Robot |
| RealSense D435i head | Visión egocéntrica |
| PICO 4 Ultra headset | Pose cabeza |
| 2× wrist trackers | IK brazos (multi-target) |
| 1× waist tracker | vx, vy |
| 2× foot trackers | vyaw, pyaw |
| MANUS gloves | Retargeting thumb+index+middle a Dex3 |

### 2.2 Inventario

| Componente | Estado | Nota |
|---|---|---|
| G1 | ✅ | 29 DOF |
| Dex3-1 | 🛒 Presupuestado | Igual que el paper, mapea a `HandType.UNITREE_DEX3` |
| RealSense D435i | ✅ Stock en G1 | Consumida por `real/teleop/image_server/realsense_server.py` |
| PICO 4 headset | ✅ | Soportado en `vr_pico.py` |
| PICO controllers (2) | ✅ | Triggers analógicos 0–1 vía `xrt.get_*_trigger()` |
| PICO trackers (5) | ✅ | 2 wrist + 1 waist + 2 foot. Coinciden con el paper |
| Jetson Thor | ✅ | 2,070 FP4 TFLOPS, 128 GB, 130 W. **Tethered, no onboard** (§2.3) |
| Cluster training | ✅ | Sin restricciones |
| Router/switch LAN | 🛒 Comprar | Subnet `192.168.123.x` |
| MANUS gloves | ❌ Descartado | Ver §2.5 |

### 2.3 Deploy — Jetson Thor tethered

**Decisión: cable Cat6a 10 m blindado, Thor en mesa externa.**

Razones:
- No altera centro de masa del G1 (2–3 kg en la espalda descalibran AMO).
- Alimentación de pared > batería para sesiones largas.
- 130 W de disipación fuera del robot.
- Iteración sin desmontar nada.

Cable suspendido desde arriba (boom articulado) → G1 puede caminar, inclinarse y acuclillarse sin enredos. Tráfico (ZMQ imágenes + DDS SDK2) cabe en GigE. Latencia LAN <3 ms.

Onboard queda como v2: mover Thor a la espalda sin cambios de código, solo IPs → `localhost`.

Build: JetPack aarch64. PyTorch/CUDA wheels oficiales de NVIDIA. Flash-attn compila en 1–2 días.

### 2.4 Topología

```
  ┌──────────────────────────────┐        ┌─────────────────────────┐
  │  G1 (piso)                   │        │  Jetson Thor (mesa)     │
  │  PC 192.168.123.164          │  Cat6a │  192.168.123.x          │
  │  ┌────────────────────┐      │  10 m  │  ┌───────────────────┐  │
  │  │ realsense_server   │ ZMQ:5556 ────▶│  │ psi-inference_rtc │  │
  │  └────────────────────┘      │        │  │ (IK+WBC+SDK2)     │  │
  │           ▲                  │        │  └─────────┬─────────┘  │
  │           │  DDS (SDK2)   ◀──────────────┐         │ WS:8014    │
  │           │                  │        │  │         ▼            │
  │  ┌────────┴──────────┐       │        │  │  ┌──────────────┐    │
  │  │ motores + IMU     │       │        │  └─▶│ serve_psi0-rtc│    │
  │  └───────────────────┘       │        │     │ (VLA, GPU)    │    │
  └──────────────────────────────┘        │     └───────────────┘    │
                                          └─────────────────────────┘

  Teleop (solo recolección):
  PICO 4 + 5 trackers ──XRoboToolkit──▶ Thor o host externo
```

Cámaras: **1 stream egocentric** a 640×480@30fps, publicado vía ZMQ:5556. Sin wrist cameras (ver `scripts/data/raw_to_lerobot.py:549-560`).

### 2.5 Sin MANUS — decisión y estrategia

**El repo NO tiene alternativa oficial a MANUS.**

| Vía | Estado en repo | Juicio del paper |
|---|---|---|
| MANUS gloves | Parámetro `manus_receiver=None` en `vr.py:42`, integración no liberada | Oficial |
| PICO hand skeleton | Funcional en `vr_pico.py:79-80` → 3 fingertips → `hand_retargeting.retarget()` | "unstable, occlusion-prone" (§VIII-B) |
| Trigger analógico | No existe, a implementar | — |

**Estrategia adoptada: replicar el paper 1:1 sustituyendo solo MANUS → PICO hand skeleton.**

| Prioridad | Modo | Input | Uso |
|---|---|---|---|
| Primario | `skeleton` | PICO hand tracking (26 joints) → 3 fingertips → `hand_retargeting.retarget()` → 7 DOF/mano | **Default para todas las demos**. Replica el paper con único swap MANUS→PICO skeleton |
| Backup | `trigger` | `xrt.get_*_trigger()` ∈ [0,1] → lerp `OPEN_POSE` ↔ `CLOSED_POSE` | **Solo si skeleton falla** sistemáticamente en algún ítem durante los 20 demos piloto (oclusión, out-of-view) |

**Criterio de activación del backup:** si en piloto un ítem muestra >30% de demos con hand tracking degradado (fingertips NaN, saltos bruscos, oclusión por el propio brazo), se cambia ese ítem a modo `trigger`. No optimizar por ítem a priori.

**Implementación:**
- `skeleton`: ya funciona sin cambios.
- `trigger`: ~25 líneas en `vr_pico.py` + `real/assets/unitree_hand/hand_poses.py` con `OPEN_POSE`/`CLOSED_POSE` derivados de joint limits de `unitree_dex3_*.urdf`. Flag `hand_mode` seleccionable al iniciar demo. Se implementa en fase 1 aunque no se use de inmediato — estar listo ahorra tiempo si piloto lo pide.
- No toca `hand_retargeting.py`, data format, ni modelo. Rollback 5 min.

### 2.6 Estado de integración de trackers en el repo

| Input del paper | En `vr_pico.py` |
|---|---|
| Head pose | ✅ `xrt.get_headset_pose()` |
| Hand skeleton | ✅ fallback sin MANUS |
| Wrist trackers → IK | ⚠️ SDK expone `get_motion_tracker_pose()`, no conectado |
| Waist → vx, vy | ❌ Usa joystick del controller del robot |
| Foot → vyaw, pyaw | ❌ Idem |

Fallback funcional hasta completar integración: head + hand tracking + joystick para locomoción.

## 3. Pipeline

```
Teleop → raw frames + data.json
  ↓
scripts/data/raw_to_lerobot.py        # raw → LeRobot
scripts/data/calc_modality_stats.py   # stats
  ↓
scripts/train/psi0/finetune-real-psi0.sh $task   # cluster
  ↓
scripts/deploy/serve_psi0-rtc.sh      # Thor: modelo
real/scripts/deploy_psi0-rtc.sh       # Thor: cliente RTC
```

## 4. Data collection

3 tareas separadas (no monolíticas):

| Task | Postura | Demos | Scoring |
|---|---|---|---|
| `G1_pick_top_shelf_and_place_cart` | Erguido | 80–120 | +5 |
| `G1_pick_middle_shelf_bent_and_place_cart` | Inclinado | 100–150 | +8 |
| `G1_pick_bottom_shelf_crouch_and_place_cart` | Acuclillado | 120–200 | +10 |

Priorizar bottom shelf (más puntos). Cubrir los 10 ítems proporcionalmente. Variar posición inicial ±30 cm, ángulo ±15°. Incluir 10–15% demos "recovery" (casi-caída → re-grip). Demos multi-pick (Track permite sumar).

## 5. Timeline (8 semanas)

| Sem | Hito |
|---|---|
| 1 | Setup env + flash-attn + open-loop eval del pre-trained |
| 2 | Teleop + image server estables; 20 demos piloto |
| 3–4 | Recolección completa (300–470 demos) |
| 5 | Fine-tune de las 3 tareas |
| 6 | Deploy RTC + iterar con failure analysis |
| 7 | Optimizar drops, velocidad, ítems/10min |
| 8 | Competencia |

## 6. Riesgos

- **Drops (−3 pts c/u)**: paso lento + brazo al torso. WBC conservador de `decoupled_wbc` en transporte.
- **Cling wrap / poker cards**: 40+ demos c/u. Si en piloto el `skeleton` degrada con estos ítems por oclusión, activar `trigger` solo para ellos.
- **Latencia**: forward pass ~160 ms en A100, ~200–400 ms en Thor. RTC con `max-delay=8` la oculta. Budget E2E <150 ms round-trip — medir.
- **Trackers no integrados**: arrancar con fallback joystick; integrar waist/foot en v2.
- **Sin MANUS**: `skeleton` primario (replica paper), `trigger` como backup solo si piloto lo justifica (§2.5). Iluminación consistente reduce fallas del skeleton.
- **Cable tethered enredado**: boom suspendido + persona "cable wrangler". Entrenar operador a pausar si AMO reacciona a tensión.
- **Overfitting**: `img-aug` activado + variar iluminación al grabar.

## 7. Checklist

**Hardware**
- [ ] Dex3-1 compradas, montadas, probadas con los 10 ítems
- [x] RealSense D435i (stock G1)
- [ ] Jetson Thor con JetPack + alimentación de pared
- [ ] Cable Cat6a blindado 10 m + boom de suspensión
- [ ] Router/switch LAN en `192.168.123.x`
- [x] Cluster training

**Software**
- [ ] `.env`: `HF_TOKEN`, `WANDB_*`, `PSI_HOME`
- [ ] `uv sync` + `flash_attn==2.7.4.post1` en training host (x86_64)
- [ ] Stack Ψ₀ en Thor (aarch64): PyTorch + CUDA + flash-attn
- [ ] `realsense_server.py` estable >1h
- [ ] Trackers PICO leídos vía `xrt.get_motion_tracker_pose()`
- [ ] Integración waist/foot completada o fallback joystick decidido
- [ ] Modo `trigger` implementado como backup + `OPEN_POSE`/`CLOSED_POSE` calibrados (no se usa por defecto)
- [ ] Flag `hand_mode` por demo (default `skeleton`)
- [ ] 20 demos piloto evaluadas: ¿algún ítem requiere `trigger`?

**Modelo**
- [ ] Checkpoints pre-trained descargados
- [ ] Open-loop eval sobre piloto
- [ ] 3 fine-tunes + respaldo (S3/HF privado)
- [ ] RTC probado con G1 físico desde Thor

**Competencia**
- [ ] Plan B: checkpoint previo + teleop manual
- [ ] Latencia E2E Thor↔G1 <150 ms verificada
- [ ] Cable Cat6a de repuesto + chequeo de continuidad pre-run
- [ ] UPS/protección eléctrica para Thor
- [ ] Backup full stack en laptop secundaria
- [ ] Cable wrangler entrenado
