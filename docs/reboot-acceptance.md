# Aceptación de recuperación tras reboot

Este procedimiento valida el issue #41 en un host Linux de prueba real. Un test
de CI, reiniciar solo el proceso o comprobar `WantedBy` no sustituyen esta prueba.
No lo ejecutes sobre la única copia de una biblioteca ni en un host compartido.

## Preparación segura

1. Usa un host desechable o self-hosted con acceso de consola y una copia limpia
   de Autodrome. Registra el commit probado con `git rev-parse HEAD`.
2. Instala y habilita `deploy/autodrome.service` siguiendo el README. Confirma que
   es una unidad del sistema, no de usuario:

   ```bash
   systemctl is-enabled autodrome
   systemctl is-active autodrome
   systemctl show autodrome -p User -p MainPID -p ControlGroup
   ```

3. Configura en `.env` rutas dedicadas que no contengan música real:

   ```dotenv
   LIBRARY_PATH=/var/lib/autodrome-reboot-test/library
   STAGING_PATH=/var/lib/autodrome-reboot-test/staging
   QUEUE_STATE_PATH=/var/lib/autodrome-reboot-test/queue.json
   PRESERVE_FAILED_STAGING=true
   DOWNLOAD_CONCURRENCY=1
   ```

   El usuario de la unidad debe ser propietario de `/var/lib/autodrome-reboot-test`.
   Reinicia el servicio después de cambiar `.env`.
4. Copia un álbum centinela que no forme parte de las descargas y guarda evidencia
   de que no cambia:

   ```bash
   find /var/lib/autodrome-reboot-test/library -type f -print0 \
     | sort -z \
     | xargs -0 sha256sum \
     > /var/lib/autodrome-reboot-test/library.before.sha256
   ```

5. Elige dos pares playlist/release ya verificados. El primero debe tardar lo
   suficiente para observarlo en `running`; el segundo puede ser pequeño. No uses
   contenido privado ni una playlist cuyo manifiesto no coincida con el release.

## Punto de reboot

1. Encola el primer álbum y espera a que la UI muestre `running` y una fase de
   descarga. Encola entonces el segundo y confirma que sigue `queued`.
2. Guarda la evidencia previa sin modificar el servicio:

   ```bash
   cp /var/lib/autodrome-reboot-test/queue.json \
     /var/lib/autodrome-reboot-test/queue.before-reboot.json
   find /var/lib/autodrome-reboot-test/staging -maxdepth 2 -type f -ls \
     > /var/lib/autodrome-reboot-test/staging.before-reboot.txt
   systemctl show autodrome -p ActiveState -p SubState -p MainPID -p ControlGroup \
     > /var/lib/autodrome-reboot-test/service.before-reboot.txt
   ```

   Comprueba en `queue.before-reboot.json` que hay exactamente un job `running` y
   al menos uno `queued`. Si el primero ya terminó, repite la preparación; no
   fabriques el estado editando `queue.json`.
3. Reinicia el host directamente, sin ejecutar antes `systemctl stop autodrome`:

   ```bash
   sudo systemctl reboot
   ```

## Verificación después del boot

Haz estas comprobaciones antes de iniciar una sesión gráfica del usuario de
Autodrome; una unidad de sistema habilitada no depende de esa sesión.

1. Confirma el arranque automático y conserva los logs de ambos boots:

   ```bash
   systemctl is-enabled autodrome
   systemctl is-active autodrome
   systemctl show autodrome -p ActiveState -p SubState -p MainPID -p ControlGroup
   journalctl -b -1 -u autodrome --no-pager \
     > /var/lib/autodrome-reboot-test/journal.previous-boot.txt
   journalctl -b 0 -u autodrome --no-pager \
     > /var/lib/autodrome-reboot-test/journal.recovery-boot.txt
   ```

   El journal del boot nuevo debe mostrar el arranque y la recuperación. El del
   boot anterior debe conservar el contexto de la descarga y del cierre del host.
2. Abre la cola. El job que estaba `running` debe figurar como `interrupted`, con
   un error que indique reinicio, y no debe volver a descargarse automáticamente.
   El job que estaba `queued` debe conservarse y pasar por `running` hasta un estado
   terminal normal. No debe aparecer una segunda ejecución del job incierto.
3. Inspecciona staging y biblioteca antes de pulsar **Retry**:

   ```bash
   find /var/lib/autodrome-reboot-test/staging -maxdepth 2 -type f -ls
   find /var/lib/autodrome-reboot-test/library -maxdepth 3 -type f -ls
   sha256sum -c /var/lib/autodrome-reboot-test/library.before.sha256
   ```

   Un staging parcial puede permanecer para diagnóstico porque
   `PRESERVE_FAILED_STAGING=true`. No debe existir un álbum parcial en la biblioteca
   final. Si el rename final ocurrió justo antes del reboot, el álbum puede estar
   completo aunque el job sea `interrupted`; en ese caso no hagas Retry. Autodrome
   debe rechazar el destino existente y nunca sobrescribirlo.
4. Comprueba que solo quedan procesos del boot actual dentro del cgroup de la
   unidad y que no depende de una shell o sesión interactiva:

   ```bash
   control_group=$(systemctl show autodrome -p ControlGroup --value)
   systemd-cgls "$control_group"
   pgrep -af 'autodrome.server|yt-dlp|ffmpeg' || true
   ```

   El proceso principal y cualquier `yt-dlp`/`ffmpeg` vivo deben pertenecer al
   cgroup mostrado. No debe haber procesos Autodrome fuera de él.

## Registro del resultado

Adjunta al issue #41:

- commit, distribución/kernel y versión de systemd;
- hora del reboot y salida de `systemctl is-enabled/is-active`;
- `queue.before-reboot.json` y el snapshot de cola posterior, sin secretos;
- listados de staging/biblioteca y resultado de los checksums;
- journals de boot anterior y de recuperación, eliminando tokens o URLs sensibles;
- resultado del cgroup/procesos;
- PASS/FAIL explícito para cada comprobación anterior.

Marca la aceptación como fallida si el job incierto vuelve a ejecutarse, se pierde
el queued, aparece contenido parcial en biblioteca, cambia el álbum centinela, el
servicio necesita login para arrancar o falta el contexto de recuperación en los
logs. Conserva el host y los artefactos sin reintentar hasta diagnosticarlo.
