# Diagnóstico de lag — Test C (htop)

Última prueba pendiente: medir qué proceso satura la CPU durante una
sesión activa de `teleop_controllers.py`. Pruebas A y B ya hechas
(controllers > hand-tracking, CUDA disponible).

## Cómo correrlo

1. En **terminal 1**, lanzar el teleop normal:

   ```bash
   cd ~/NONHUMAN/Psi0/real/teleop
   conda activate psi_deploy
   export CYCLONEDDS_URI="<CycloneDDS><Domain><General><NetworkInterfaceAddress>192.168.123.222</NetworkInterfaceAddress></General></Domain></CycloneDDS>"
   python teleop_controllers.py --robot g1 --pico_ip 192.168.250.87
   ```

   Pulsar `s` y mover los controllers ~15 segundos.

2. En **terminal 2**, mientras el teleop corre:

   ```bash
   htop
   ```

   Pulsar `Shift+P` para ordenar por `%CPU`.

3. Anotar el top 10 de procesos por uso de CPU.

## Qué buscar

- ¿Algún `python` al 100% de un core?
- ¿`RoboticsServiceProcess` alto?
- ¿`gst-launch` o similar (PicoIRStreamer x264)?

## Resultado C

```
[pegá top 10 por %CPU]
```
