# Teleop y Data Collection en Unitree G1

Guia corta, operativa y pensada para copy/paste.

Este flujo fue validado con:

- G1 PC: `192.168.123.164`
- Laptop por Ethernet al G1: `192.168.123.222`
- Laptop por Wi-Fi: `192.168.250.82`
- PICO: `192.168.250.87`

Si alguna IP cambia, reemplazarla en los comandos.

## 1. Ver IPs

En la laptop:

```bash
hostname -I
ip a
```

Esperado en este setup:

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
   - `Controller` ON
   - `Hand` ON
   - `Send` ON
3. En `Remote Vision Session`:
   - elegir `ZEDMINI`
   - pulsar `Listen`
   - poner la IP Wi-Fi de la laptop:

```text
192.168.250.82
```

4. Soltar o bajar los controllers para que el PICO entre a hand tracking.

## 6. Validar PICO desde la laptop

En otra terminal de la laptop:

```bash
cd /home/raul/NONHUMAN/Psi0/real/teleop
conda activate psi_deploy
python check_pico_connection.py --pico-ip 192.168.250.87 --wait --wait-timeout 120
```

Esperado:

```text
PICO looks reachable from the laptop.
```

Si no sale eso, revisar:

- `Head`, `Controller`, `Hand`, `Send`
- `ZEDMINI -> Listen`
- IP del PC en el PICO: `192.168.250.82`
- que `RoboticsServiceProcess` siga vivo

## 7. Preparar metadata de tareas

Desde la laptop:

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
python main.py --robot g1 --pico_streamer --pico_ip 192.168.250.87
```

Notas:

- `192.168.123.222` es la IP Ethernet de la laptop hacia el G1.
- `192.168.250.87` es la IP del PICO.
- El warning de CycloneDDS sobre `NetworkInterfaceAddress` deprecado no bloquea el flujo.

## 9. Qué debe pasar al arrancar

En la laptop deberías ver algo parecido a esto:

```text
[PICO] PICO SDK Initialized successfully
[PicoIRStreamer] started, target=192.168.250.87:12345
[PicoIRStreamer] connected to 192.168.250.87:12345
body_ctrl ok!
body_ik ok!
Initialize Dex3_1_Controller OK!
[INFO] Master: waiting to start
```

Notas:

- `DDS hand state not received... Continuing without live Dex3 feedback.` es esperado si el robot no tiene manos Dex3.
- `Master: waiting to start` significa que ya está listo y ahora espera que tú inicies la sesión.

## 10. Iniciar la teleoperación

En la misma terminal donde corre `main.py`, cuando aparezca:

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
```

También puede aparecer:

```text
Height Calibrated! Head Y: ..., Offset: ...
```

## 11. Comandos durante la sesión

En la terminal de `main.py`:

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

No usar `Ctrl+C` salvo emergencia, porque ensucia el cierre de procesos.

## 12. Validación mínima de teleop

Antes de grabar episodios largos, validar:

1. En el PICO ves el stream del robot.
2. Hay manos virtuales en el headset.
3. El robot entra en pose ready.
4. Los brazos responden al movimiento.
5. La locomoción sale del joystick del control remoto del G1, no del PICO.

## 13. Caso sin manos Dex3

Si el robot no tiene manos:

- el pipeline igual corre
- el hand tracking del PICO igual se captura
- se calculan comandos de mano
- el robot ignora esos comandos físicamente

Esto sirve para mover brazos/cuerpo y para grabar data reusable.

## 14. Terminales recomendadas

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

### Terminal C — laptop, validación PICO

```bash
cd /home/raul/NONHUMAN/Psi0/real/teleop
conda activate psi_deploy
python check_pico_connection.py --pico-ip 192.168.250.87 --wait --wait-timeout 120
```

### Terminal D — laptop, teleop real

```bash
cd /home/raul/NONHUMAN/Psi0/real/teleop
conda activate psi_deploy
export CYCLONEDDS_URI="<CycloneDDS><Domain><General><NetworkInterfaceAddress>192.168.123.222</NetworkInterfaceAddress></General></Domain></CycloneDDS>"
python main.py --robot g1 --pico_streamer --pico_ip 192.168.250.87
```

Luego en esa terminal:

```text
s
```

## 15. Deploy RTC

Para el deploy real del cliente RTC en el host:

```bash
cd /home/raul/NONHUMAN/Psi0/real
conda activate psi_deploy
bash ./scripts/deploy_psi0-rtc.sh
```

Usar esta parte cuando ya no estés en teleop/data collection sino en ejecución de política.

## 16. Troubleshooting corto

### `Master: waiting to start`

Falta iniciar la sesión:

```text
s
```

### `PicoIRStreamer connected ...` pero no hay teleop

Hay stream de video, pero todavía falta:

- que `s` entre
- o que el hand tracking del PICO esté llegando bien

Validar con:

```bash
python check_pico_connection.py --pico-ip 192.168.250.87 --wait --wait-timeout 120
```

### `DDS hand state not received within 5.0s`

Esperado si no hay Dex3.

### El robot no camina con el PICO

Esperado. En este repo, la locomoción usa el joystick del control remoto del G1.

### El robot no mueve manos

Esperado si no tienes manos físicas Dex3 instaladas.
