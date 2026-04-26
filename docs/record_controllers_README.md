# Teleop con Controllers PICO y Data Collection en Unitree G1

Guia corta, operativa y pensada para copy/paste.

Versión paralela del modo hand-tracking (ver
[`record_hand_tracking_README.md`](record_hand_tracking_README.md)).
Misma laptop, mismo robot, mismo headset, misma red — lo único que
cambia es el **`.py` de entrada** y cómo manejas el robot.

Este flujo fue validado con:

- G1 PC: `192.168.123.164`
- Laptop por Ethernet al G1: `192.168.123.222`
- Laptop por Wi-Fi: `192.168.250.82`
- PICO: `192.168.250.87`

Si alguna IP cambia, reemplazarla en los comandos.

## Diferencias clave vs hand-tracking

| Aspecto | Hand-tracking (`main.py`) | Controllers (`teleop_controllers.py`) |
|---|---|---|
| Cómo se mueven los brazos del robot | Manos físicas del operador (hand tracking de los dedos) | Pose de los 2 controllers físicos del PICO |
| Locomoción | Sticks del mando del G1 | Sticks del PICO |
| Agacharse / Pararse | (no existía) | Botón X (baja) / Botón A (sube) del PICO |
| Comando de gripper | Retargeting de dedos del operador | Triggers del PICO (lineal 0..1) |
| E-STOP | `button[3]` del mando G1 + `Ctrl+C` | **idéntico** |
| REPL `s/q/d/exit` | En la laptop | **idéntico** — en la laptop |
| ¿Cuántas personas? | 2 (teleoperador + laptop) | 2 (teleoperador + laptop) |

> ℹ️ Sin Dex3 físico, los comandos de gripper se calculan y se graban en el
> episodio pero ningún motor de mano responde. Es esperado, igual que en el
> modo hand-tracking.

## 1. Ver IPs

En la laptop:

```bash
hostname -I
ip a
```

Esperado:

- Ethernet al robot: `192.168.123.222`
- Wi-Fi: `192.168.250.82`

## 2. Entrar a la PC del G1 por SSH

Desde la laptop:

```bash
ssh unitree@192.168.123.164
```

## 3. Correr image server en la PC del G1

En la PC del G1:

```bash
cd ~/NONHUMAN/Psi0/real/teleop/image_server
conda activate vision
python realsense_server.py
```

Esperado:

```text
Server started, waiting for client requests...
RealSense: RGB + IR + Depth active.
```

Dejar esta terminal abierta.

## 4. Correr XRoboToolkit-PC-Service en la laptop

En otra terminal de la laptop:

```bash
cd /opt/apps/roboticsservice
bash runService.sh
pgrep -af RoboticsServiceProcess
```

Debe aparecer un proceso `RoboticsServiceProcess`.

## 5. Configurar el PICO

En el headset:

1. Abrir `XRoboToolkit-Unity-Client`.
2. En `Tracking Session`:
   - `Head` ON
   - `Controller` ON  ← **clave para este modo**
   - `Hand` puede estar OFF (no se usa)
   - `Send` ON
3. En `Remote Vision Session`:
   - elegir `ZEDMINI`
   - pulsar `Listen`
   - poner la IP Wi-Fi de la laptop:

```text
192.168.250.82
```

4. **Mantener los dos controllers en mano** desde el inicio. No los
   sueltes — los usaras todo el tiempo.

## 6. Validar PICO desde la laptop

Antes que nada, probar que el SDK lee los controllers correctamente.
Hay un script de probe descartable solo para eso:

```bash
cd /home/raul/NONHUMAN/Psi0/real/teleop
conda activate psi_deploy
python probe_pico_controllers.py --duration 10
```

Esperado:

```text
All expected xrt functions are present.
controllers/ subpackage imports OK.

Wave the controllers, press buttons, push the sticks. Probing for 10s...

head [+0.012, +1.523, -0.205] | L [+0.234, +1.198, -0.330] axis=(+0.00,+0.00) trg=0.00 grp=0.00 | R [-0.245, +1.205, -0.331] axis=(+0.00,+0.00) trg=0.00 grp=0.00 | btn A=0 B=0 X=0 Y=0 mL=0 mR=0 clkL=0 clkR=0
...
```

Mientras corre, tienes que ver:

- `head xyz` cambia cuando giras la cabeza
- `L xyz` y `R xyz` cambian cuando mueves cada controller
- `axis` se mueve cuando empujas los sticks
- `trg` y `grp` suben a ~1.0 cuando aprietas trigger / grip
- `A/B/X/Y/mL/mR` cambian a `1` cuando presionas cada botón

Si todo eso responde, sigue. Si no, revisar:

- `Head`, `Controller`, `Send` en el PICO (paso 5)
- `ZEDMINI -> Listen` en el PICO
- IP de la laptop en el PICO: `192.168.250.82`
- que `RoboticsServiceProcess` siga vivo (paso 4)

> 🧹 El script `probe_pico_controllers.py` es **descartable**. Es solo
> para Fase 0 / debugging; bórralo cuando estés cómodo con el modo
> controllers.

Opcionalmente, también puedes correr la validación de red del modo
hand-tracking (sigue siendo útil para verificar el puerto de stream):

```bash
python check_pico_connection.py --pico-ip 192.168.250.87 --wait --wait-timeout 120
```

## 7. Preparar metadata de tareas

Idéntico al modo hand-tracking:

```bash
cd /home/raul/NONHUMAN/Psi0/real/teleop
conda activate psi_deploy
python taskcreator.py
```

## 8. Lanzar teleop y data collection

Desde la laptop:

```bash
cd /home/raul/NONHUMAN/Psi0/real/teleop
conda activate psi_deploy
export CYCLONEDDS_URI="<CycloneDDS><Domain><General><NetworkInterfaceAddress>192.168.123.222</NetworkInterfaceAddress></General></Domain></CycloneDDS>"
python teleop_controllers.py --robot g1 --pico_ip 192.168.250.87
```

Notas:

- `192.168.123.222` es la IP Ethernet de la laptop hacia el G1.
- `192.168.250.87` es la IP del PICO.
- `--pico_streamer` **no** se pasa: el manager lo fuerza internamente
  (siempre se necesita el stream de cámara hacia el headset).
- El warning de CycloneDDS sobre `NetworkInterfaceAddress` deprecado no
  bloquea el flujo.

## 9. Qué debe pasar al arrancar

En la laptop deberias ver algo parecido a:

```text
[ControllerReceiver] Initializing PICO SDK...
[ControllerReceiver] PICO SDK initialized.
[PicoIRStreamer] started, target=192.168.250.87:12345
[PicoIRStreamer] connected to 192.168.250.87:12345
body_ctrl ok!
body_ik ok!
Initialize Dex3_1_Controller OK!
[INFO] Master: waiting to start
```

Entre `body_ctrl ok!` y `Master: waiting to start`, **el robot debe
bajar solo a su pose por defecto** (igual que con `main.py`). Esto es
la auto-calibración heredada del original. No hagas nada todavía —
espera a que el robot esté quieto y de pie.

Notas:

- `DDS hand state not received... Continuing without live Dex3 feedback.`
  es esperado si el robot no tiene manos Dex3.
- `Master: waiting to start` significa que ya está listo y ahora espera
  que tu inicies la sesión.

## 10. Iniciar la teleoperación

En la misma terminal donde corre `teleop_controllers.py`, cuando
aparezca:

```text
>
```

escribir:

```text
s
```

y luego `Enter`.

Esperado:

```text
[INFO] Session started.
[INFO] Current task: ...
Height Calibrated! Head Y: ..., Offset: ...
```

## 11. Comandos durante la sesión

En la terminal de `teleop_controllers.py`:

```text
s
q
d
exit
```

Significado:

- `s`: iniciar episodio
- `q`: detener y guardar
- `d`: detener y descartar
- `exit`: cerrar limpio

No usar `Ctrl+C` salvo emergencia.

## 12. Mapeo de inputs del PICO

Una vez que la sesión arranca con `s`:

| Input PICO | Acción en el robot |
|---|---|
| **Pose del controller izquierdo** | Brazo izquierdo del G1 sigue al controller |
| **Pose del controller derecho** | Brazo derecho del G1 sigue al controller |
| **Pose del headset** | Posición/orientación de la cabeza del robot (afecta torso vía IK) |
| **Stick izquierdo (Y)** | Caminar adelante (+) / atras (−) |
| **Stick izquierdo (X)** | Lateral derecha / izquierda |
| **Stick derecho (X)** | Girar (yaw) |
| **Stick derecho (Y)** | (sin uso) |
| **Botón X** (mano izquierda) | Mantener para agacharse |
| **Botón A** (mano derecha) | Mantener para pararse / volver a altura normal |
| **Trigger izquierdo** | Cerrar gripper izquierdo (0..1, sin movimiento físico sin Dex3) |
| **Trigger derecho** | Cerrar gripper derecho (0..1, sin movimiento físico sin Dex3) |
| **Botones B / Y / menu / grip / axis click** | Reservados (sin uso por ahora) |

E-STOP (NO está en el PICO en este modo):

- **`button[3]` del mando físico del G1** (vía DDS).
- **`Ctrl+C` en la terminal de la laptop**.

> ⚠️ Mantener el mando del G1 al alcance aunque no lo uses para nada
> mas — es el kill-switch primario. La locomoción ya no sale del mando,
> solo el E-STOP.

## 13. Validación mínima de teleop

Antes de grabar episodios largos, validar:

1. En el PICO ves el stream del robot.
2. El robot baja a pose cero **antes** de pulsar `s`.
3. Despues de `s`, los brazos del robot responden a los controllers.
4. El stick izquierdo hace caminar; el derecho hace girar.
5. Mantener X agacha el torso de a poco; A lo sube de vuelta.
6. Los triggers no producen movimiento físico (esperado, no hay Dex3),
   pero los valores se graban en el episodio.
7. `button[3]` del mando G1 sigue activando E-STOP.

## 14. Calibración inicial de los frames del controller

> 🛠️ **Solo la primera vez.** Las matrices `CONTROLLER2INSPIRE_L_ARM` y
> `CONTROLLER2INSPIRE_R_ARM` en
> [`real/teleop/controllers/constants.py`](../real/teleop/controllers/constants.py)
> son una mejor-suposición inicial copiada de los valores del modo
> hand-tracking. **Es esperado que necesiten un ajuste empírico** la
> primera vez que pruebes este modo.

Si al mover los controllers ves que los brazos del robot apuntan en
una dirección rara (ejemplo: muevo el controller hacia adelante y el
brazo del robot va hacia un costado), edita esas dos matrices en
`constants.py` y vuelve a lanzar. Una o dos iteraciones suelen alcanzar.

No tocar `constants_vuer.py` — eso sigue siendo del modo
hand-tracking.

## 15. Caso sin manos Dex3

Sin Dex3 fisico:

- El pipeline igual corre.
- Los triggers del PICO igual se leen y se mapean a qpos lineal entre
  pose abierta y cerrada.
- Los qpos resultantes igual se graban en el episodio (formato
  byte-identico al modo hand-tracking).
- El robot ignora esos comandos físicamente (no hay motor que ejecute).
- Cuando llegue la Dex3, los placeholders en `controllers/constants.py`
  (`DEX3_OPEN_QPOS`, `DEX3_CLOSED_QPOS`) deberán recalibrarse con valores
  empíricos. Hay un `TODO` claro en el archivo.

## 16. Terminales recomendadas

### Terminal A — G1 PC

```bash
ssh unitree@192.168.123.164
cd ~/NONHUMAN/Psi0/real/teleop/image_server
conda activate vision
python realsense_server.py
```

### Terminal B — laptop, XRoboToolkit service

```bash
cd /opt/apps/roboticsservice
bash runService.sh
pgrep -af RoboticsServiceProcess
```

### Terminal C — laptop, validación PICO controllers

```bash
cd /home/raul/NONHUMAN/Psi0/real/teleop
conda activate psi_deploy
python probe_pico_controllers.py --duration 10
```

### Terminal D — laptop, teleop real

```bash
cd /home/raul/NONHUMAN/Psi0/real/teleop
conda activate psi_deploy
export CYCLONEDDS_URI="<CycloneDDS><Domain><General><NetworkInterfaceAddress>192.168.123.222</NetworkInterfaceAddress></General></Domain></CycloneDDS>"
python teleop_controllers.py --robot g1 --pico_ip 192.168.250.87
```

Luego en esa terminal:

```text
s
```

## 17. Deploy RTC

El deploy RTC del cliente (correr una política entrenada en el robot)
no cambia entre modos — es el mismo del flujo original:

```bash
cd /home/raul/NONHUMAN/Psi0/real
conda activate psi_deploy
bash ./scripts/deploy_psi0-rtc.sh
```

Ese paso es para ejecución de política, no para teleop / data
collection.

## 18. Troubleshooting corto

### `Master: waiting to start`

Falta iniciar la sesión:

```text
s
```

### `[ControllerReceiver] xrt.init() raised: ...`

Solo es informativo si el SDK ya estaba inicializado por otro proceso
en la misma máquina. Continúa.

### `MISSING xrt functions in your installed XRoboToolkit-PC-Service-Pybind`

El binario instalado no expone alguna función que el modo controllers
necesita (ej. `get_left_controller_pose`). Actualizar
`XRoboToolkit-PC-Service-Pybind`. Sin esto el modo controllers no puede
arrancar.

### Brazos apuntan a dirección rara

Calibrar `CONTROLLER2INSPIRE_L_ARM` / `R_ARM` en
`real/teleop/controllers/constants.py` (ver paso 14).

### El robot se agacha demasiado o muy poco

Ajustar en `real/teleop/controllers/constants.py`:

- `CROUCH_STEP_M` — metros por frame mientras X/A está presionado.
- `CROUCH_RANGE_M` — `(min, max)` del offset Z; default `(-0.20, 0.05)`.

### `DDS hand state not received within 5.0s`

Esperado si no hay Dex3.

### El robot no camina con el stick PICO

- Verificar que `probe_pico_controllers.py` muestre los axis cambiando
  cuando empujas el stick.
- Confirmar que `Controller` y `Send` están ON en el PICO.

### El robot no se agacha con X

- Verificar que `probe_pico_controllers.py` muestre `X=1` cuando
  presionas el botón.
- Mantener el botón presionado **continuamente** — un toque puntual
  solo baja 0.005 m.

## 19. Volver al modo hand-tracking

Sin tocar nada:

```bash
python main.py --robot g1 --pico_streamer --pico_ip 192.168.250.87
```

Los dos modos coexisten; el formato de episodios es idéntico, así que
los datos pueden mezclarse en un mismo dataset al entrenar.
