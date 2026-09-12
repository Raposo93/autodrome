# Autodrome

Autodrome es una aplicación web autoalojada para buscar playlists de álbumes en
YouTube, descargar su audio, obtener metadatos de MusicBrainz y Cover Art
Archive, etiquetar los MP3 y publicarlos de forma segura en una biblioteca.

La interfaz soportada es **FastAPI + Vue/Vite**. La antigua CLI no forma parte
del producto. Producción arranca mediante el comando instalado `autodrome`;
`start_autodrome.sh` queda reservado para desarrollo y diagnóstico.

## Funcionalidad

- Búsqueda conjunta de playlists de YouTube y releases de MusicBrainz.
- Cola persistente con estados, fases y avance por pista visibles por WebSocket.
- Descarga secuencial por pista, con reintentos y errores individualizados.
- Metadatos y nombres correctos para releases de uno o varios discos.
- Validación, optimización y MIME real de las portadas embebidas.
- Preparación en staging y publicación atómica sin sobrescribir álbumes.
- Redis opcional como caché; nunca se necesita para completar una descarga.
- Diagnóstico seguro de almacenamiento, worker y dependencias desde `/status`.

## Requisitos

- Python 3.14 y soporte para `venv`.
- `ffmpeg` disponible en `PATH`.
- Deno 2.3.0 o posterior, recomendado para soporte completo de YouTube.
- Una clave de YouTube Data API v3.
- Para construir desde el repositorio: Node.js 22, npm y Bash 5 o posterior.
- Redis en `127.0.0.1:6379` es opcional y está desactivado por defecto. Para
  usarlo, configura `REDIS_ENABLED=true`. Sin Redis, Autodrome consulta los
  proveedores originales y conserva igualmente el estado de la cola en disco.

## Desarrollo desde un clon limpio

Para desarrollo o ejecución manual, desde la raíz del repositorio:

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
npm ci --prefix frontend
cp .env.example .env
```

Edita `.env` y completa como mínimo `GOOGLE_API_KEY` y `CONTACT_EMAIL`. Revisa
también `LIBRARY_PATH`; se recomienda una ruta absoluta hacia la biblioteca de
música. No uses `sudo` para instalar dependencias dentro de `.venv` ni para
ejecutar la aplicación.

Para construir el artefacto instalable:

```bash
npm ci --prefix frontend
npm run build --prefix frontend
.venv/bin/python -m build
.venv/bin/python scripts/smoke_wheel.py dist/*.whl
```

El build falla si falta `frontend/dist/index.html`. El wheel resultante incluye
la SPA compilada y expone `autodrome`; Node y npm no son dependencias de
runtime. El workflow de releases repite el build y el smoke en un entorno
limpio antes de adjuntar el wheel a la release de GitHub.

## Servicio systemd (recomendado)

La unidad de ejemplo [deploy/autodrome.service](deploy/autodrome.service) asume
un wheel instalado en `/opt/autodrome/.venv`, el fichero
`/opt/autodrome/.env` y un usuario/grupo no-root `autodrome`. El checkout, Node,
npm, `app.py` y `frontend/` no son necesarios en ese host una vez instalado el
wheel.

Puedes usar otro usuario existente u otra ruta, pero entonces ajusta `User`,
`Group`, `WorkingDirectory`, `EnvironmentFile` y `ExecStart` en la copia de la
unidad.

### Instalación persistente en `/opt/autodrome`

Crea primero el usuario del servicio. El ejemplo usa un usuario de sistema sin
shell interactiva:

```bash
sudo useradd --system --user-group --home-dir /opt/autodrome \
  --shell /usr/sbin/nologin autodrome
```

Si ya existe, no vuelvas a crearlo. Compruébalo con `id autodrome`.

Descarga el wheel de una release o constrúyelo en otra máquina. Desde una cuenta
administrativa normal, indica su ruta en `AUTODROME_WHEEL` e instala el
artefacto sin copiar el repositorio:

```bash
AUTODROME_WHEEL=/ruta/autodrome-0.x.y-py3-none-any.whl
sudo install -d -o "$USER" -g "$(id -gn)" -m 0755 /opt/autodrome
python3.14 -m venv /opt/autodrome/.venv
/opt/autodrome/.venv/bin/python -m pip install "$AUTODROME_WHEEL"
sudo install -o "$USER" -g autodrome -m 0640 /dev/null /opt/autodrome/.env
sudo install -d -o autodrome -g autodrome -m 0750 /opt/autodrome/covers
```

Edita `/opt/autodrome/.env` y configura al menos `GOOGLE_API_KEY`,
`CONTACT_EMAIL` y una ruta absoluta para `LIBRARY_PATH`. `VERSION` es opcional
en una instalación desde wheel: si se omite, se usa la versión instalada del
paquete.

El wheel instala también la versión compatible de `yt-dlp-ejs`, pero no
descarga ni administra Deno. Instala una versión fijada de Deno 2.3.0 o
posterior siguiendo la [documentación oficial](https://docs.deno.com/runtime/getting_started/installation/)
y deja el ejecutable en `/usr/local/bin/deno` para que la unidad incluida lo
encuentre. No dependas de una instalación bajo el home de tu usuario
interactivo: el servicio se ejecuta como `autodrome` con un `PATH` explícito.
Comprueba exactamente ese entorno antes de arrancar:

```bash
sudo -u autodrome env \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin \
  deno --version
```

Si el runtime vive en otra ubicación, configura en `.env` la ruta absoluta al
binario (o a su directorio), por ejemplo
`YT_DLP_DENO_PATH=/opt/deno/bin/deno`. Autodrome no necesita ejecutarse como
root para usarlo.

El usuario `autodrome` también necesita lectura y escritura en `LIBRARY_PATH`,
`STAGING_PATH` y `QUEUE_STATE_PATH`. La forma concreta de concederlos depende de
si la biblioteca es exclusiva del servicio o compartida con otros usuarios.

Antes de instalar la unidad, prueba el mismo arranque que usará systemd:

```bash
sudo -u autodrome /opt/autodrome/.venv/bin/autodrome
```

Si arranca correctamente, detén la prueba con `Ctrl+C`. Un fallo aquí suele ser
de configuración, dependencias o permisos y es más fácil de diagnosticar antes
de introducir systemd.

Instala y verifica la unidad:

```bash
sudo install -m 644 deploy/autodrome.service /etc/systemd/system/autodrome.service
sudo systemd-analyze verify /etc/systemd/system/autodrome.service
sudo systemctl daemon-reload
sudo systemctl enable --now autodrome
systemctl status autodrome
journalctl -u autodrome -f
```

Operación habitual:

```bash
sudo systemctl stop autodrome
sudo systemctl start autodrome
sudo systemctl restart autodrome
systemctl status autodrome
journalctl -u autodrome -b
journalctl -xeu autodrome.service
```

El proceso permanece en foreground, arranca sin login y se reinicia tras fallos
con una espera de cinco segundos. Al parar, se espera a que termine o se
interrumpa la operación de audio activa; no se inicia otra pista. Si no termina
en 120 segundos, systemd elimina todo el grupo de procesos. La cola conserva el
último estado durable y los trabajos inciertos pasan a `interrupted` al
reiniciar; revisa staging y biblioteca antes de reintentarlos. Por defecto, los
logs se escriben únicamente en stdout/stderr y systemd los recoge en journal.

### Biblioteca compartida

La unidad distribuida usa `UMask=0077`, adecuada cuando los archivos creados por
Autodrome deben quedar privados para el usuario del servicio. Si `LIBRARY_PATH`
forma parte de una biblioteca administrada también por otra cuenta o por otros
servicios, usa un grupo compartido y una umask deliberada en vez de cambiar la
propiedad de toda la biblioteca a `autodrome`.

Por ejemplo, con un grupo `media`:

```bash
sudo groupadd media
sudo usermod -aG media "$USER"
sudo usermod -aG media autodrome
sudo chgrp -R media /ruta/a/la/biblioteca
sudo find /ruta/a/la/biblioteca -type d -exec chmod 2775 {} +
sudo find /ruta/a/la/biblioteca -type f -exec chmod 0664 {} +
```

Revisa el alcance antes de aplicar cambios recursivos sobre una biblioteca
existente. Los directorios con bit `setgid` hacen que los nuevos archivos y
subdirectorios hereden el grupo compartido.

Crea un override de systemd para que Autodrome use ese grupo y genere contenido
compartible:

```bash
sudo mkdir -p /etc/systemd/system/autodrome.service.d
sudo tee /etc/systemd/system/autodrome.service.d/override.conf >/dev/null <<'EOF'
[Service]
UMask=0002
SupplementaryGroups=media
EOF

sudo systemctl daemon-reload
sudo systemctl restart autodrome
```

`UMask=0002` produce normalmente directorios `775` y archivos `664`; usa
`UMask=0007` si solo el propietario y el grupo deben tener acceso. Si cambias la
umask después de haber descargado contenido, los permisos existentes no cambian
automáticamente.

Comprueba la configuración efectiva, incluidos los overrides:

```bash
systemctl show autodrome -p UMask -p SupplementaryGroups
systemctl cat autodrome
```

Para diagnosticar un problema de permisos sobre la cola o la biblioteca:

```bash
sudo -u autodrome test -r /opt/autodrome/.env && echo '.env readable'
sudo -u autodrome test -w /ruta/a/la/biblioteca && echo 'library writable'
namei -l /ruta/a/la/biblioteca/.autodrome-queue.json
```

### Biblioteca en otro filesystem

Si la biblioteca vive en un disco o montaje independiente, puedes hacer que
systemd espere explícitamente a ese filesystem. Añade al mismo override:

```ini
[Unit]
RequiresMountsFor=/ruta/a/la/biblioteca
```

Después ejecuta `sudo systemctl daemon-reload` y reinicia el servicio. Esto evita
que Autodrome intente arrancar durante el boot antes de que su biblioteca esté
montada.

### Actualización

Descarga el wheel de la nueva release, detén el servicio, actualiza el paquete y
vuelve a arrancar. La biblioteca, staging, cola y portadas permanecen fuera del
wheel:

```bash
AUTODROME_WHEEL=/ruta/autodrome-0.x.y-py3-none-any.whl
sudo systemctl stop autodrome
/opt/autodrome/.venv/bin/python -m pip install --upgrade "$AUTODROME_WHEEL"
sudo systemctl start autodrome
```

Si cambia `deploy/autodrome.service`, vuelve a instalar la unidad y recarga
systemd antes de arrancar:

```bash
sudo install -m 644 deploy/autodrome.service /etc/systemd/system/autodrome.service
sudo systemctl daemon-reload
```

## Arranque y parada

En producción, el único entry point soportado es el instalado por el wheel:

```bash
/opt/autodrome/.venv/bin/autodrome
```

El comando valida la configuración y sirve frontend, API y WebSocket desde un
único proceso FastAPI en `http://127.0.0.1:5000`. No requiere checkout, Node ni
Vite en runtime. Pulsa `Ctrl+C` para detenerlo.

Para desarrollo, `./start_autodrome.sh` (o `--dev`) inicia FastAPI y Vite
(`http://127.0.0.1:5173`) y detiene ambos al salir. `npm run dev --prefix frontend`
sigue disponible cuando se gestiona el backend por separado.

No existe un comando CLI soportado para buscar o descargar álbumes.

## Diagnóstico del sistema

La navegación principal y la ruta directa `/status` muestran una comprobación
de solo lectura de biblioteca, staging, escritura durable de cola, `ffmpeg`,
yt-dlp/EJS, Deno, YouTube, MusicBrainz, Redis y el worker. La conectividad de la
API de YouTube y la capacidad local de ejecutar sus challenges JavaScript son
resultados separados. Deno ausente o demasiado antiguo aparece como warning,
sin fingir que el proceso está caído. Cada resultado es independiente: una
caída de proveedor no convierte la página completa en error y Redis desactivado
es un estado normal. La comprobación de la cola crea y elimina un archivo
temporal junto al estado, pero nunca modifica ni reemplaza el JSON durable.

Las pruebas externas tienen timeout y se ejecutan solo al abrir o refrescar la
vista. La comprobación de YouTube usa el endpoint público de discovery, no una
búsqueda que consuma cuota; MusicBrainz conserva el límite global de inicio de
una petición por segundo. La respuesta no incluye claves, credenciales, email de
contacto ni rutas absolutas. Cuando `API_TOKEN` es obligatorio, `/api/status/`
queda protegido por el mismo token que el resto de la API.

## Configuración

La configuración principal vive en `.env`:

- `GOOGLE_API_KEY`: clave de YouTube Data API v3; obligatoria.
- `CONTACT_EMAIL`: contacto incluido en el User-Agent de MusicBrainz;
  obligatorio.
- `VERSION`: override opcional del identificador del User-Agent y `/status`.
  Un wheel instalado usa automáticamente su metadata; el ejemplo propone
  `autodrome/dev` para ejecutar directamente desde el checkout.
- `AUTODROME_COMMIT`: commit hexadecimal opcional que identifica el build en la
  vista de diagnóstico. También se reconoce `GIT_COMMIT`.
- `LIBRARY_PATH`: raíz de la biblioteca; usa preferiblemente una ruta absoluta.
- `STAGING_PATH`: staging; por defecto,
  `LIBRARY_PATH/.autodrome-staging`.
- `QUEUE_STATE_PATH`: estado durable de la cola; por defecto,
  `LIBRARY_PATH/.autodrome-queue.json`.
- `MIN_STAGING_FREE_BYTES`: espacio mínimo antes de descargar; 1 GiB por
  defecto.
- `PRESERVE_FAILED_STAGING`: conserva (`true`) o elimina (`false`) los trabajos
  fallidos; por defecto, `true`.
- `DOWNLOAD_CONCURRENCY`: descargas de pistas simultáneas dentro de un álbum,
  entre `1` y `4`; por defecto, `1`. Valores altos aumentan la carga de CPU,
  disco y ffmpeg, y pueden provocar throttling del proveedor.
- `YT_DLP_DENO_PATH`: ruta opcional al ejecutable Deno o a su directorio. Si se
  omite, yt-dlp y `/status` lo resuelven con el mismo `PATH` del proceso. La
  política se aplica igual al preflight y a la descarga.
- `LOG_LEVEL`: nivel de log; por defecto, `INFO`.
- `LOG_FILE`: ruta opcional para duplicar el log en un archivo rotatorio. Vacío
  por defecto. Si se configura, el usuario del servicio necesita permiso de
  escritura sobre el archivo y su directorio.
- `LOG_MAX_BYTES`: tamaño máximo de cada archivo de log; 10 MiB por defecto.
- `LOG_BACKUP_COUNT`: número de archivos rotados conservados; `3` por defecto.
- `REDIS_ENABLED`: activa la caché Redis local; por defecto, `false`. Cuando
  está desactivada no se crea ningún cliente ni se intenta conectar a Redis.

Portadas:

- `MAX_EMBEDDED_COVER_BYTES`: máximo embebido; 1 MiB por defecto.
- `OPTIMIZE_OVERSIZED_COVERS`: optimiza (`true`) o rechaza (`false`) imágenes
  que exceden los límites.
- `MAX_EMBEDDED_COVER_WIDTH` y `MAX_EMBEDDED_COVER_HEIGHT`: 1600 píxeles por
  defecto.
- `MAX_COVER_SOURCE_PIXELS`: límite duro de decodificación; 40 millones por
  defecto.
- `MAX_COVER_UPLOAD_BYTES`: tamaño máximo de una portada alternativa recibida;
  10 MiB por defecto.
- `COVER_STORAGE_PATH`: almacenamiento durable para portadas preparadas;
  `covers/selected` por defecto, relativo al directorio de trabajo. Usa una
  ruta absoluta si el servicio no trabaja en `/opt/autodrome`.

Red y frontend:

- `API_HOST` y `API_PORT`: escucha de FastAPI; `127.0.0.1:5000` por defecto.
- `API_TOKEN`: token de al menos 32 caracteres, obligatorio cuando `API_HOST`
  no es loopback. Introdúcelo en la pantalla de conexión del navegador; se
  conserva solo durante la sesión de esa pestaña. Nunca se incrusta en el build
  ni se incluye en la URL del WebSocket: el frontend lo intercambia mediante
  HTTP autenticado por un ticket aleatorio, efímero y de un solo uso.
- `CORS_ORIGINS`: orígenes `http`/`https` permitidos, separados por comas; vacío
  por defecto.
- `VITE_HOST` y `VITE_PORT`: escucha de Vue; `127.0.0.1:5173` por defecto.
- `VITE_IP_HOST`: destino opcional del proxy de Vite. El script lo calcula desde
  `API_HOST` y `API_PORT` si no se configura.

Para exponer la aplicación fuera del equipo, configura deliberadamente
`API_HOST`, `API_TOKEN` y la red/firewall. Usa un proxy HTTPS para acceso remoto.
`VITE_HOST` solo afecta al desarrollo. No expongas Vite a Internet.

## Selección y metadata manual

La búsqueda muestra candidatos ligeros. Los tracklists de MusicBrainz se cargan
progresivamente y se pueden desplegar para comparar ediciones. Solo se comprueba
el manifiesto de YouTube al seleccionar una playlist; un fallo o una cantidad
incompatible bloquea la selección. El manifiesto se reutiliza hasta dos minutos
y se vuelve a validar en el backend antes de descargar.

**Results per source** limita por igual las playlists de YouTube y los releases
de MusicBrainz. Al activar **Max tracks per result**, ambas listas excluyen los
candidatos cuyo número conocido de pistas supera el máximo; los candidatos sin
recuento conocido se conservan para no confundir metadata incompleta con una
incompatibilidad confirmada.

Se recomienda seleccionar una playlist y su release de MusicBrainz. Si no existe
un release adecuado, selecciona la playlist y pulsa **Download without MusicBrainz**.
Acepta la explicación e introduce los nombres definitivos de **Artist** y **Album**;
son independientes de la búsqueda y se guardan con el trabajo y sus reintentos.
En modo manual, los títulos y el orden proceden de la playlist. No se obtiene fecha,
portada, créditos individuales ni estructura multidisco de MusicBrainz. La cola
identifica este modo como **Manual metadata**. Las garantías de validación, staging
y publicación atómica son las mismas.

Cuando los nombres finales de artista y álbum ya son autoritativos —desde el
release cargado o desde los campos manuales confirmados— la interfaz comprueba el
destino normalizado antes de habilitar la descarga. Si ya existe, muestra su ruta
relativa y el número de MP3 regulares que puede leer; si el filesystem no permite
una respuesta fiable, conserva el estado como desconocido y bloquea el botón. Los
términos originales de búsqueda nunca se usan como destino implícito.

Si Cover Art Archive tiene una portada, se usa como fuente autoritativa sin
mostrar alternativas. Si no la tiene, antes de encolar hay que elegir entre la
miniatura exacta de la playlist, subir un JPEG/PNG/WebP o continuar sin portada.
La miniatura de YouTube se identifica claramente como no autoritativa y se
normaliza a 1:1 con relleno centrado, sin recortar ni deformar. Las imágenes se
validan y optimizan antes de descargar audio. La fuente elegida y la referencia
a los bytes ya preparados forman parte del trabajo, por lo que un reintento usa
la misma decisión e imagen.

Las portadas alternativas preparadas se conservan mientras cualquier trabajo
`queued`, `running`, `failed` o `interrupted` las necesite. Al dejar de estar
referenciadas por un trabajo recuperable se eliminan después de persistir el
nuevo estado. Las selecciones abandonadas sin llegar a encolarse expiran tras
24 horas y se limpian mediante barridos acotados al arrancar o preparar otra
portada.

## Integridad y recuperación

Cada álbum se construye completamente dentro del staging de la biblioteca. Se
validan cantidad, duración, tags y tamaño de portadas antes de publicar con un
rename atómico. Un álbum existente no se sobrescribe.

La comprobación preventiva de la interfaz no reserva el nombre. El backend vuelve
a comprobar el destino tanto antes del trabajo costoso como inmediatamente antes
del rename final; si otro proceso crea el álbum entretanto, la publicación falla
sin reemplazarlo.

Al reiniciar, los trabajos `queued` se reanudan en orden. Un trabajo que estaba
`running` pasa a `interrupted` y conserva el último error; no se repite a ciegas.

Desde la cola, **Cancel** impide que un trabajo `queued` llegue a ejecutarse y lo
conserva como `cancelled`. No interrumpe trabajos que ya estén `running`.
**Clear finished jobs** limpia el historial de trabajos `succeeded`, `failed`,
`interrupted` y `cancelled`; **Remove** elimina uno de ellos. Estas dos últimas
acciones borran las entradas y liberan portadas alternativas que ya no necesita
ningún trabajo recuperable; nunca borran audio, álbumes publicados ni staging
conservado.

**Retry** crea un nuevo trabajo con el payload original de un fallo o interrupción.
El original conserva su estado y error, y el nuevo guarda su identificador en
`retry_of`. No se permite otro reintento del mismo original mientras tenga uno
activo. Cada cambio se guarda antes de emitir el snapshot por WebSocket; si no se
puede guardar, la operación se revierte y la UI muestra un error.

Si falla guardar una transición del procesador, la cola se pausa y muestra el
error de almacenamiento. No acepta nuevas descargas hasta recuperar la escritura.
Corrige el espacio libre o los permisos de `QUEUE_STATE_PATH`: el procesador
reintenta guardar cada cinco segundos y continúa automáticamente, sin repetir
una descarga que ya terminó. No hace falta reiniciar. Si reinicias mientras
la finalización sigue sin guardar, el trabajo pasa de `running` a `interrupted`;
comprueba la biblioteca y el staging antes de solicitar un reintento. Una parada
con almacenamiento averiado conserva en disco el último estado confirmado.

Si el filesystem se queda sin espacio durante descarga, conversión, tagging,
portada o publicación, el álbum no se publica y el trabajo termina en `failed`
con la última fase y el error `ENOSPC`, siempre que la cola aún pueda guardar su
estado. Por defecto se conserva el staging fallido para diagnóstico; con
`PRESERVE_FAILED_STAGING=false` se limpia únicamente ese staging, nunca una
biblioteca válida. La comprobación inicial de espacio es una guardia temprana,
no una reserva: libera espacio tanto en el filesystem de biblioteca/staging como
en los que alojan `QUEUE_STATE_PATH` y `covers/`.

Para recuperarte, restaura espacio y comprueba primero biblioteca y staging. Si
la cola estaba pausada por no poder persistir, reintentará la escritura y seguirá
automáticamente. Para un job `failed` o `interrupted`, usa **Retry** solo después
de confirmar que el álbum final no existe; Autodrome rechazará un destino ya
publicado en vez de sobrescribirlo. Conserva o mueve aparte cualquier staging que
necesites para diagnóstico antes de reintentar.

Un cierre abrupto (`SIGKILL`, caída del host o pérdida del proceso) no ejecuta el
cleanup cooperativo. Al arrancar de nuevo, un job que quedó durablemente en
`running` pasa a `interrupted` y nunca se repite de forma automática; los jobs
que seguían en `queued` sí conservan su orden y continúan. El staging parcial se
mantiene con la política predeterminada para poder diagnosticarlo. Si el proceso
cayó después del rename final pero antes de guardar `succeeded`, el álbum puede
estar completo aunque el job figure como `interrupted`: revisa primero biblioteca
y staging y no uses **Retry** sobre un álbum ya publicado. La protección de
destino impedirá sobrescribirlo.

La aceptación de un reinicio completo requiere un host de prueba real; no debe
ejecutarse en CI compartido ni inferirse solo de la configuración systemd. Sigue
el procedimiento y conserva las evidencias descritas en
[`docs/reboot-acceptance.md`](docs/reboot-acceptance.md).

El benchmark experimental de concurrencia también es exclusivo de un host
desechable y una biblioteca bajo `/tmp`; consulta
[`docs/download-concurrency-benchmark.md`](docs/download-concurrency-benchmark.md).

La portada original queda en `covers/<release-id>.jpg`. Si se rechaza, sustituye
ese archivo por una imagen JPEG, PNG o WebP válida y vuelve a solicitar el álbum.
La versión optimizada solo vive en memoria y no modifica el original.

## Desarrollo

Antes de ejecutar los E2E por primera vez, instala el Chromium administrado por
Playwright (CI instala también sus dependencias de sistema):

```bash
npm exec --prefix frontend -- playwright install chromium
```

Ejecuta la validación completa antes de cada commit:

```bash
./check.sh
```

El comando ejecuta comprobaciones Git, la suite backend, las pruebas unitarias y
E2E del frontend y el build de Vite. Un resultado correcto termina con
`All checks passed.`

Las dependencias Python están fijadas en `requirements.lock`. Si cambian
`requirements.txt` o `requirements-dev.txt`, regenera el lock con:

```bash
.venv/bin/python -m piptools compile requirements.txt requirements-dev.txt \
  --strip-extras --allow-unsafe --output-file requirements.lock
```

Para actualizar dependencias frontend de forma intencionada, ejecuta
`npm install --prefix frontend` y revisa `frontend/package-lock.json`. CI repite
las pruebas y builds; la auditoría de dependencias informa vulnerabilidades sin
aplicar actualizaciones automáticas.

## Limitaciones de la primera release

- Un backend y un álbum activo; concurrencia de pistas limitada a `1–4`
  (`DOWNLOAD_CONCURRENCY=1` por defecto).
- Los trabajos en espera se pueden cancelar; las descargas activas no se interrumpen.
- Las playlists pueden cambiar tras el preflight. Un fallo posterior impide publicar
  el álbum y conserva el contexto; no se completa con pistas ausentes.
- MusicBrainz y Cover Art Archive deben responder para completar el flujo con release.
  Un timeout o error no se interpreta como ausencia válida de metadata o portada.
- El modo manual no edita pistas individuales ni deduce estructura multidisco.
- Los trabajos interrumpidos requieren revisar biblioteca/staging antes de Retry.
- Las pruebas avanzadas de disco lleno, SIGKILL, reboot y concurrencia quedan
  aplazadas; no forman parte de las garantías verificadas de esta versión.

## Uso responsable

Autodrome se proporciona únicamente con fines educativos y personales. Cada
usuario debe contar con permiso para descargar, distribuir o almacenar el
contenido y cumplir la legislación de propiedad intelectual aplicable.

### MusicBrainz request policy

MusicBrainz requests start at least one second apart, including retries, independently
of its one-request concurrency limit. Slow responses do not add an unnecessary extra
second. This limit is shared by search and release lookups in the application process;
run a single backend process to preserve that cadence.

- `MUSICBRAINZ_TIMEOUT_SECONDS` (default `20`): positive, finite timeout per attempt.
- `MUSICBRAINZ_MAX_ATTEMPTS` (default `3`): total attempts, including the first; at least `1`.
- `MUSICBRAINZ_RETRY_BASE_SECONDS` (default `1`): finite, nonnegative exponential backoff
  base in seconds (`base`, `2 × base`, …). Setting it to zero still respects the rate limit.

Only connection failures, timeouts, HTTP 429 and HTTP 5xx are retried. Exhaustion is
reported as an upstream error, not an empty search. These settings do not change
YouTube or Cover Art Archive request policy.
