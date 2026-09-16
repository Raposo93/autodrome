# Configuración

[Volver al README](../README.md) · [Docker Compose](docker.md) ·
[Instalación nativa](installation-native.md)

La configuración principal vive en `.env`; las variables de entorno ya
definidas tienen prioridad. Usa [.env.example](../.env.example) como punto de
partida. Reinicia la aplicación después de cambiar la configuración.

En el servicio nativo, usa rutas absolutas. El Compose distribuido fija dentro
del contenedor las rutas de biblioteca, staging, cola, catálogo, caché de Cover
Art Archive y portadas alternativas bajo `/music`, además de la escucha en
`0.0.0.0:5000`; cambiar esos valores en `.env` no sustituye los de `compose.yaml`.

## Proveedores e identificación

- `GOOGLE_API_KEY`: clave de YouTube Data API v3; obligatoria.
- `CONTACT_EMAIL`: contacto incluido en el User-Agent de MusicBrainz;
  obligatorio.
- `VERSION`: override opcional del identificador del User-Agent y `/status`.
  Un wheel instalado usa automáticamente su metadata; el ejemplo propone
  `autodrome/dev` para ejecutar directamente desde el checkout.
- `AUTODROME_COMMIT`: commit hexadecimal opcional que identifica el build en la
  vista de diagnóstico. También se reconoce `GIT_COMMIT`.

## Almacenamiento y descargas

- `LIBRARY_PATH`: raíz de la biblioteca; usa preferiblemente una ruta absoluta.
- `STAGING_PATH`: staging; por defecto,
  `LIBRARY_PATH/.autodrome-staging`. Debe estar en el mismo filesystem que la
  biblioteca.
- `QUEUE_STATE_PATH`: estado durable de la cola; por defecto,
  `LIBRARY_PATH/.autodrome-queue.json`.
- `PUBLICATION_CATALOG_PATH`: catálogo SQLite durable de álbumes publicados;
  por defecto, `LIBRARY_PATH/.autodrome-publications.sqlite3`.
- `MIN_STAGING_FREE_BYTES`: espacio mínimo antes de descargar; 1 GiB por
  defecto.
- `PRESERVE_FAILED_STAGING`: conserva (`true`) o elimina (`false`) el staging
  de los trabajos fallidos; por defecto, `true`. No elimina entradas de la cola.
- `DOWNLOAD_CONCURRENCY`: descargas de pistas simultáneas dentro de un álbum,
  entre `1` y `4`; por defecto, `1`. Valores altos aumentan la carga de CPU,
  disco y ffmpeg, y pueden provocar throttling del proveedor.
- `YT_DLP_DENO_PATH`: ruta opcional al ejecutable Deno o a su directorio. Si se
  omite, yt-dlp y `/status` lo resuelven con el mismo `PATH` del proceso. La
  política se aplica igual al preflight y a la descarga.

## Logs y caché

- `LOG_LEVEL`: nivel de log; por defecto, `INFO`.
- `LOG_FILE`: ruta opcional para duplicar el log en un archivo rotatorio. Vacío
  por defecto. Si se configura, el usuario del servicio necesita permiso de
  escritura sobre el archivo y su directorio.
- `LOG_MAX_BYTES`: tamaño máximo de cada archivo de log; 10 MiB por defecto.
- `LOG_BACKUP_COUNT`: número de archivos rotados conservados; `3` por defecto.
- `REDIS_ENABLED`: activa la caché Redis local; por defecto, `false`. Cuando
  está desactivada no se crea ningún cliente ni se intenta conectar a Redis.
  Si se activa, se usa `localhost:6379`. La cola y el catálogo siguen en disco;
  Redis no es necesario para completar una descarga.

## Portadas

- `MAX_EMBEDDED_COVER_BYTES`: máximo embebido; 1 MiB por defecto.
- `OPTIMIZE_OVERSIZED_COVERS`: optimiza (`true`) o rechaza (`false`) imágenes
  que exceden los límites.
- `MAX_EMBEDDED_COVER_WIDTH` y `MAX_EMBEDDED_COVER_HEIGHT`: 1600 píxeles por
  defecto.
- `MAX_COVER_SOURCE_PIXELS`: límite duro de decodificación; 40 millones por
  defecto.
- `MAX_COVER_UPLOAD_BYTES`: tamaño máximo de una portada alternativa recibida;
  10 MiB por defecto.
- `COVER_ART_CACHE_PATH`: caché regenerable de Cover Art Archive; por defecto,
  la ruta absoluta `~/.cache/autodrome/cover-art` del usuario que ejecuta el
  proceso, independiente del directorio de trabajo y del paquete instalado.
  Si se configura, debe ser una ruta absoluta no vacía; para conservar el
  valor predeterminado, omite la variable. Docker y Compose la fijan en
  `/music/.autodrome-cover-cache`. El directorio se crea al guardar una portada
  descargada; una respuesta 404 no lo crea. El usuario del servicio necesita
  permisos para crearlo y escribir en él.
- `COVER_STORAGE_PATH`: almacenamiento durable para portadas preparadas;
  `covers/selected` por defecto, relativo al directorio de trabajo. Usa una
  ruta absoluta para el servicio nativo. Esas portadas pueden ser necesarias
  para Retry y reinicios; mantenlas en un directorio distinto de
  `COVER_ART_CACHE_PATH`.

## Red y frontend

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

## Peticiones a MusicBrainz

Los inicios de peticiones a MusicBrainz se separan al menos un segundo, incluidos
los reintentos. La política se comparte entre búsquedas y consultas de ediciones
dentro del proceso: ejecuta un único backend. Solo hay una petición simultánea;
una respuesta lenta no añade un segundo extra de espera.

- `MUSICBRAINZ_TIMEOUT_SECONDS`: timeout por intento; `20` segundos por defecto.
  Debe ser un número finito mayor que cero.
- `MUSICBRAINZ_MAX_ATTEMPTS`: intentos totales, incluido el primero; `3` por
  defecto y mínimo `1`.
- `MUSICBRAINZ_RETRY_BASE_SECONDS`: base de la espera exponencial entre intentos
  (`base`, `2 × base`, …); `1` segundo por defecto. Debe ser finita y no negativa.
  El valor `0` sigue respetando la separación mínima entre peticiones.

Se reintentan fallos de conexión, timeouts y respuestas HTTP 429 y 5xx. Agotar los
intentos se informa como error del proveedor, no como búsqueda vacía. Estos
ajustes no cambian la política de YouTube ni Cover Art Archive.

## Variables del host para Docker Compose

Estas variables las interpreta Compose, no la aplicación:

| Variable | Valor por defecto | Uso |
| --- | --- | --- |
| `AUTODROME_IMAGE` | `ghcr.io/raposo93/autodrome:latest` | Imagen que se ejecuta; fija una versión publicada para controlar actualizaciones. |
| `AUTODROME_BIND_ADDRESS` | `127.0.0.1` | Dirección del host donde se publica el puerto. |
| `AUTODROME_PORT` | `5000` | Puerto publicado en el host. |
| `AUTODROME_UID` / `AUTODROME_GID` | `10001` / `10001` | Identidad numérica del proceso; debe poder escribir en el mount. |
| `MUSIC_PATH` | `./music` en `.env.example` | Carpeta del host montada como `/music`; obligatoria para Compose. |

Consulta [Docker Compose](docker.md) para preparar permisos y persistencia.
