# Autodrome

Autodrome es una aplicación web autoalojada para buscar playlists de álbumes en
YouTube, descargar su audio, obtener metadatos de MusicBrainz y Cover Art
Archive, etiquetar los MP3 y publicarlos de forma segura en una biblioteca.

La interfaz soportada es **FastAPI + Vue/Vite**. La antigua CLI no forma parte
del producto y `start_autodrome.sh` es la única ruta de inicio recomendada.

## Funcionalidad

- Búsqueda conjunta de playlists de YouTube y releases de MusicBrainz.
- Cola persistente con estados visibles por WebSocket.
- Descarga secuencial por pista, con reintentos y errores individualizados.
- Metadatos y nombres correctos para releases de uno o varios discos.
- Validación, optimización y MIME real de las portadas embebidas.
- Preparación en staging y publicación atómica sin sobrescribir álbumes.
- Redis opcional como caché; nunca se necesita para completar una descarga.

## Requisitos

- Linux o un entorno Unix con Bash 5 o posterior.
- Python 3.14 y soporte para `venv`.
- Node.js 22 y npm.
- `ffmpeg` disponible en `PATH`.
- Una clave de YouTube Data API v3.
- Redis en `127.0.0.1:6379` es opcional y está desactivado por defecto. Para
  usarlo, configura `REDIS_ENABLED=true`. Sin Redis, Autodrome consulta los
  proveedores originales y conserva igualmente el estado de la cola en disco.

## Instalación desde un clon limpio

Desde la raíz del repositorio:

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

## Arranque y parada

La ruta recomendada es:

```bash
./start_autodrome.sh
```

El script valida herramientas, dependencias y configuración antes de arrancar.
Después inicia FastAPI en `http://127.0.0.1:5000` y Vue en
`http://127.0.0.1:5173`, mostrando los logs de ambos procesos en la terminal.
Abre la dirección de Vue en el navegador. Pulsa `Ctrl+C` para detener exactamente
los dos procesos de esa instancia.

No existe un comando CLI soportado para buscar o descargar álbumes.

## Configuración

La configuración principal vive en `.env`:

- `GOOGLE_API_KEY`: clave de YouTube Data API v3; obligatoria.
- `CONTACT_EMAIL`: contacto incluido en el User-Agent de MusicBrainz;
  obligatorio.
- `VERSION`: identificador del User-Agent; por defecto se propone
  `autodrome/dev` en el ejemplo.
- `LIBRARY_PATH`: raíz de la biblioteca; usa preferiblemente una ruta absoluta.
- `STAGING_PATH`: staging; por defecto,
  `LIBRARY_PATH/.autodrome-staging`.
- `QUEUE_STATE_PATH`: estado durable de la cola; por defecto,
  `LIBRARY_PATH/.autodrome-queue.json`.
- `MIN_STAGING_FREE_BYTES`: espacio mínimo antes de descargar; 1 GiB por
  defecto.
- `PRESERVE_FAILED_STAGING`: conserva (`true`) o elimina (`false`) los trabajos
  fallidos; por defecto, `true`.
- `DOWNLOAD_CONCURRENCY`: actualmente debe ser `1`; las descargas de un álbum
  siguen siendo secuenciales.
- `LOG_LEVEL`: nivel de log; por defecto, `INFO`.
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

Red y frontend:

- `API_HOST` y `API_PORT`: escucha de FastAPI; `127.0.0.1:5000` por defecto.
- `API_TOKEN`: token de al menos 32 caracteres, obligatorio cuando `API_HOST`
  no es loopback. `start_autodrome.sh` lo entrega al frontend sin duplicarlo.
- `CORS_ORIGINS`: orígenes `http`/`https` permitidos, separados por comas; vacío
  por defecto.
- `VITE_HOST` y `VITE_PORT`: escucha de Vue; `127.0.0.1:5173` por defecto.
- `VITE_API_TOKEN`: anulación opcional del token usado por el frontend.
- `VITE_IP_HOST`: destino opcional del proxy de Vite. El script lo calcula desde
  `API_HOST` y `API_PORT` si no se configura.

Para exponer la aplicación fuera del equipo, configura deliberadamente
`API_HOST`, `VITE_HOST`, `API_TOKEN` y la red/firewall. No expongas el servidor
de desarrollo directamente a Internet; sitúalo detrás de un proxy HTTPS.

## Integridad y recuperación

Cada álbum se construye completamente dentro del staging de la biblioteca. Se
validan cantidad, duración, tags y tamaño de portadas antes de publicar con un
rename atómico. Un álbum existente no se sobrescribe.

Al reiniciar, los trabajos `queued` se reanudan en orden. Un trabajo que estaba
`running` pasa a `interrupted` y conserva el último error; no se repite a ciegas.

Desde la cola, **Clear finished jobs** limpia el historial de trabajos `succeeded`,
`failed` e `interrupted`; **Remove** elimina uno de ellos. Los trabajos `queued` y
`running` permanecen intactos. Estas acciones solo borran entradas del historial,
no archivos de audio, álbumes publicados ni staging conservado.

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

La portada original queda en `covers/<release-id>.jpg`. Si se rechaza, sustituye
ese archivo por una imagen JPEG, PNG o WebP válida y vuelve a solicitar el álbum.
La versión optimizada solo vive en memoria y no modifica el original.

## Desarrollo

Ejecuta la validación completa antes de cada commit:

```bash
./check.sh
```

El comando ejecuta comprobaciones Git, la suite backend, las pruebas del frontend
y el build de Vite. Un resultado correcto termina con `All checks passed.`

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
