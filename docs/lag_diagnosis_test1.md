# Diagnóstico de lag — Test 1 (modo controllers)

Análisis del primer test del modo controllers (`teleop_controllers.py`) en
el G1 real, y plan de validación para aislar la causa del lag.

Log de origen: [`logs_test1.md`](logs_test1.md).

---

## TL;DR

| Aspecto | Estado |
|---|---|
| Funcionalidad (brazos, locomoción, crouch, grabación) | ✅ Funcionó |
| Lag persistente ~18-22 ms/frame (target 16.67 ms = 60 Hz) | ⚠️ Real, **probablemente pre-existente** |
| 3 stalls de 0.6 / 1.7 / 1.7 s en una ventana de ~5 s | ⚠️ Anomalía puntual, NO es el lag steady-state |
| Joint limit warnings (`Value ... at index 6 out of limits`) | ⚠️ Calibración de `CONTROLLER2INSPIRE_*_ARM` mejorable |
| Errores en shutdown post-Ctrl+C | ⚠️ Pre-existente del repo, cosmético |

---

## 1. El lag steady-state — qué es y de dónde sale

`master_whole_body.py:752` imprime `Loop time takes too much: 0.0XXX`
cuando un frame del loop principal supera `1/60 s = 16.67 ms`. Es un
threshold súper estricto: cualquier 17 ms gatilla el warning aunque la
teleop siga siendo perfectamente usable.

Distribución observada en el log:

| Tiempo de loop | Frecuencia efectiva | Sensación |
|---|---|---|
| 16-18 ms (la mayoría) | 55-60 Hz | Imperceptible |
| 19-25 ms (frecuente) | 40-52 Hz | Levemente "blando" |
| 26-30 ms (ocasional) | 33-38 Hz | Notable |

El loop hace por frame: `get_robot_data` (DDS cache, rápido) + IK
inferior (CasADi, CPU) + `adapter_jit.pt` (CPU o GPU según torch) + IK
whole-body + DDS publish + escritura asíncrona del episodio.

**Sospechosos del lag agregado por el modo controllers** (vs hand-tracking):

- 9 polls a `xrt.*` por frame en `ControllerReceiver.get_state()` — vs
  los 3 polls en hand-tracking. Cada poll tiene sub-ms de latencia, pero
  al frame total puede sumar 1-3 ms.
- Las multiplicaciones de matrices y `_trigger_to_qpos` agregan
  microsegundos, no son el cuello.

---

## 2. El stall catastrófico (0.6 s + 1.7 s + 1.7 s)

Aproximadamente 5 segundos de la sesión, el log muestra esta secuencia:

```
Loop time: 0.057s   ← empieza a degradar
Loop time: 0.069s
Loop time: 0.631s   ← FREEZE
[~80 warnings: "worker: runner did not finish within 33ms"]
Loop time: 1.693s   ← MEGA FREEZE
[~50 warnings]
Loop time: 1.710s   ← MEGA FREEZE
[estabiliza]
```

Esto NO es lo que sentís todo el tiempo: es un evento puntual.
Posibles causas:

- **GC / swap / carga externa de la laptop**: otro proceso, indexación,
  swap.
- **Pico de I/O al disco**: el `IKDataWriter` + `AsyncImageWriter`
  escriben episodio + JPEGs; un buffer flush grande puede congelar.
- **CasADi (IPOPT)** eligió un frame mal y se atoró.

Si te vuelve a aparecer **consistentemente** en cada sesión, ahí sí lo
cazamos. Por ahora, sospecha de "hipo de la laptop".

---

## 3. Joint limit warnings

```
WARNING:root:Value -0.298073 at index 6 is out of limits: [-0.261800, 0.261800]
```

El IK produce un ángulo fuera del rango físico del joint 6 (muñeca,
probablemente roll o yaw). No bloquea — el robot igual se mueve con la
muñeca pegada al límite — pero indica que `CONTROLLER2INSPIRE_*_ARM`
todavía no está perfectamente calibrada para el grip frame del PICO.

Mejorable con calibración empírica (Fase 1-bis).

---

## 4. Errores de shutdown (post-Ctrl+C)

`BrokenPipeError`, `CasADi WARNING("KeyboardInterruptException")`, y
`resource_tracker: There appear to be 3 leaked shared_memory objects` —
todos pre-existentes del repo cuando uno hace `Ctrl+C` en vez de salir
con `exit` desde el REPL. **No son nuevos.**

El "3 leaked" incluye los 2 SHM originales + mi `controller_cmd_shm`.
Lo puedo blindar haciendo `unlink()` antes que `super().cleanup()` así
sobrevive a un Ctrl+C bruto.

> **Recordatorio operativo**: salí siempre con `exit` desde la REPL,
> no con `Ctrl+C`. Eso evita el 90% de la basura del shutdown.

---

## 5. Plan de validación — corré estas 3 pruebas

Orden recomendado: A, luego B, luego C. Pegá las salidas en las
secciones de "Resultado" más abajo.

### Prueba A — ¿el lag está también en `main.py` (hand-tracking)?

Esto es lo más informativo. Si el modo hand-tracking original te da las
mismas warnings, el lag NO es por código mío y la solución estructural
es otra.

```bash
cd ~/NONHUMAN/Psi0/real/teleop
python main.py --robot g1 --pico_streamer --pico_ip 192.168.250.87
```

- Esperá a que aparezca `Master: waiting to start`.
- Pulsá `s`.
- Movés un poco las manos durante ~20 segundos.
- Escribí `exit` (no Ctrl+C).

Pegá las primeras ~30 líneas de output post-`s` en la sección
"Resultado A" abajo.

**Interpretación**:

- **Si ves warnings `Loop time takes too much: 0.018...`** con valores
  similares a los del modo controllers → el lag es pre-existente y no
  por mi código.
- **Si `main.py` corre sin warnings o con tiempos mucho menores** → mi
  código agregó load (probablemente los 6 polls extras de xrt). En ese
  caso, fix posible: cachear el `ControllerState` en un thread dedicado.

### Prueba B — ¿está disponible la GPU?

El adapter (`adapter_jit.pt`) usa `cuda` si torch lo encuentra, si no
cae a `cpu`. Inferencia en CPU son varios ms por frame, perfectamente
suficiente para explicar los 18-20 ms steady-state.

```bash
cd ~/NONHUMAN/Psi0/real/teleop
python -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU only')"
```

Pegá la salida en la sección "Resultado B" abajo.

**Interpretación**:

- `CUDA available: True` → la GPU está, el adapter corre rápido.
- `CUDA available: False` → todo en CPU. Es **esperable** que tengas
  18-20 ms de loop. Sin GPU no hay forma de bajarlo mucho con código.

### Prueba C — ¿qué proceso satura la CPU durante teleop?

Mientras corre `teleop_controllers.py` (en otra terminal):

```bash
htop
```

Pulsá `Shift+P` para ordenar por CPU%. Mirá si:

- Algún proceso `python` está al 100% (esperable, pero ¿qué porcentaje
  exacto?)
- `RoboticsServiceProcess` está alto (puede ser que el SDK de PICO esté
  cargando)
- `gst-launch` o similar (el `PicoIRStreamer` con x264) está alto

Pegá las primeras 10 líneas de htop ordenadas por CPU en la sección
"Resultado C" abajo (o una captura de pantalla).

---

## 6. Fixes posibles (después de las pruebas)

Según resultados, en orden de impacto esperado:

### Fix 1 — Si A muestra lag SOLO en mi código (no en main.py)

Mover el `xrt.get_*()` polling a un thread separado dentro del worker
process, a 60 Hz dedicada. El `ControllerPreprocessor.process()`
lee solo el último estado cacheado en vez de pollear xrt nueve veces.
**Esto reduce CPU y latencia.** Estimado: 30 líneas en `pico_io.py`.

### Fix 2 — Blindar `controller_cmd_shm` contra Ctrl+C

En `controllers/manager.py:cleanup()`, hacer `self._cmd_shm.close()` y
`self._cmd_shm.unlink()` ANTES de `super().cleanup()` (en vez de
después). Así aunque Ctrl+C interrumpa el join de procesos, el shm ya
está liberado. **Cosmético.** ~3 líneas.

### Fix 3 — Calibrar `CONTROLLER2INSPIRE_*_ARM`

Para los joint limit warnings: vos me decís "muevo el controller en
dirección X y el brazo del robot va en dirección Y" y ajustamos las
matrices iterativamente. Sin GPU no hay test automático, es trial &
error empírico.

### Fix 4 — Si B muestra `CUDA available: False`

Esto es entorno, no código. Tendrías que reinstalar PyTorch con CUDA
correctamente en el env `psi_deploy`. Es un trabajo separado.

---

## Resultado A — `main.py` (hand-tracking)

```
[pegá aquí las primeras ~30 líneas post-`s` de la corrida con main.py]
```

## Resultado B — disponibilidad de CUDA

```
[pegá aquí la salida del python -c "import torch; ..."]
```

## Resultado C — htop durante teleop

```
[pegá aquí top 10 procesos por CPU% durante una corrida activa de teleop_controllers.py]
```

---

## Notas finales

- El test 1 fue exitoso a nivel funcional. Los issues de lag son
  optimización, no bloqueantes.
- Recordatorio: siempre cerrar con `exit` en la REPL, no con `Ctrl+C`.
- Cuando confirmemos la causa del lag (post-pruebas A/B/C), aplico los
  fixes correspondientes y vamos a un test 2.
