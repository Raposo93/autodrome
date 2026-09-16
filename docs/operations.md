# Operación y recuperación

[Volver al README](../README.md) · [Configuración](configuration.md)

## Diagnóstico del sistema

**System status**, accesible también en `/status`, comprueba biblioteca, staging,
escritura durable de cola, ffmpeg, yt-dlp/EJS, Deno, YouTube, MusicBrainz, Redis y
el worker. La conectividad de la API de YouTube y la capacidad local de ejecutar
sus challenges JavaScript se muestran por separado. Deno ausente o demasiado
antiguo aparece como advertencia; Redis desactivado es un estado normal.

Cada comprobación es independiente. Las consultas externas tienen timeout y se
hacen solo al abrir o refrescar la vista. YouTube se comprueba mediante el
endpoint público de discovery, sin lanzar una búsqueda que consuma cuota.
MusicBrainz mantiene su cadencia de una petición por segundo.

El diagnóstico no cambia trabajos ni archivos de música. La prueba de escritura
crea y elimina un archivo temporal junto al estado de la cola, sin reemplazar
el JSON durable. Las respuestas no incluyen claves, credenciales, email de
contacto ni rutas absolutas. Cuando se exige `API_TOKEN`, `/api/status/` está
protegido como el resto de la API.

Los logs van a stdout/stderr por defecto: usa `docker compose logs -f autodrome`
o `journalctl -u autodrome -f`, según la instalación. `LOG_FILE` permite además
un archivo rotatorio; consulta [configuración](configuration.md#logs-y-caché).

## Publicación y datos persistentes

Cada álbum se construye en staging, en el mismo filesystem que la biblioteca.
Antes de publicarlo se comprueban la cantidad de archivos, su identidad numérica,
que sean MP3 legibles con duración positiva, los tags esperados y el tamaño de las
portadas embebidas. Estas comprobaciones no identifican la grabación musical.

El destino se comprueba antes del trabajo costoso y antes del rename final. Un
álbum existente se rechaza. La comprobación de la interfaz no reserva el nombre;
si el destino cambia mientras se descarga, el trabajo puede fallar al publicar.

Tras publicar, Autodrome registra la procedencia en el catálogo SQLite indicado
por `PUBLICATION_CATALOG_PATH`. La vista **Published albums** permite inspeccionar
fuentes, decisiones y checksums; consulta la [guía de uso](usage.md#álbumes-publicados).

Si el rename termina pero falla guardar el catálogo, el trabajo informa del fallo
y del destino publicado. Puede existir un álbum completo aunque la cola no
muestre `succeeded`. Revisa biblioteca, historial y logs antes de recuperar ese
trabajo: no se reconcilia automáticamente con el catálogo.

## Acciones de la cola

- **Cancel** sobre un trabajo `queued` impide que se ejecute y lo conserva como
  `cancelled`. Sobre uno `running`, guarda `cancelling` y solicita la cancelación;
  puede esperar a que termine la operación de audio activa. Cuando comienza
  `publishing`, la cancelación se rechaza.
- **Retry** crea un trabajo nuevo a partir de uno `failed` o `interrupted`, con
  sus decisiones originales y un enlace `retry_of`. El original conserva su
  estado y error. No se permite otro reintento del mismo original mientras haya
  uno activo. No es una reanudación desde la última pista descargada.
- **Remove** elimina una entrada terminada. **Clear finished jobs** elimina las
  entradas `succeeded`, `failed`, `interrupted` y `cancelled`.

Eliminar entradas no borra audio, álbumes publicados, catálogo ni staging
conservado. Sí libera portadas alternativas que ya no necesita ningún trabajo
recuperable. Los cambios se guardan antes de emitirse por WebSocket; si no se
pueden guardar, la acción no se confirma y la interfaz muestra un error.

## Si la cola no puede guardar

Si falla una transición del procesador, la cola se pausa y muestra el error de
almacenamiento. No acepta nuevas descargas hasta recuperar la escritura.
Comprueba espacio y permisos tanto de `QUEUE_STATE_PATH` como de su directorio.

El procesador reintenta guardar cada cinco segundos y continúa automáticamente
al recuperarse, sin repetir una descarga ya terminada. No hace falta reiniciar.
Si se reinicia antes de guardar la finalización, el estado durable puede seguir
siendo `running` y recuperarse como `interrupted`. Una parada con almacenamiento
averiado conserva en disco el último estado confirmado.

## Si falta espacio

La comprobación inicial exige `MIN_STAGING_FREE_BYTES` libres (1 GiB por defecto),
pero no reserva ese espacio. Si se agota durante descarga, conversión, etiquetado,
portada o publicación, el trabajo puede fallar con `ENOSPC`. El error y la última
fase se conservan siempre que la cola pueda guardar su estado.

Con `PRESERVE_FAILED_STAGING=true`, valor predeterminado, se conserva el staging
fallido para diagnóstico. Con `false` se limpia el staging de ese trabajo, no la
biblioteca. Si el espacio se agota después del rename, al guardar catálogo o cola,
el álbum ya puede estar publicado: compruébalo antes de reintentar.

Para recuperarte:

1. Restaura espacio o permisos en biblioteca/staging y en los directorios de
   cola, catálogo y portadas.
2. Comprueba si el álbum final existe y conserva el staging que necesites para
   diagnosticar el fallo.
3. Si la cola está pausada, espera su reintento de escritura. Para un trabajo
   `failed` o `interrupted`, usa **Retry** solo tras confirmar que no está publicado.

## Reinicios y cierres abruptos

Al arrancar, los trabajos `queued` vuelven a la cola en su orden. Los que estaban
`running` pasan a `interrupted` y no se repiten automáticamente. Una cancelación
ya guardada como `cancelling` se recupera como `cancelled`.

Si la última fase era `publishing`, el aviso pide revisar biblioteca e historial:
el rename puede haberse completado antes de que se guardase el estado final.
Autodrome no deduce el éxito a partir de la presencia de la carpeta ni repara el
catálogo automáticamente.

Un cierre abrupto (`SIGKILL`, caída del host o pérdida del proceso) no ejecuta la
limpieza cooperativa. Pueden quedar archivos parciales en staging. Revisa esos
archivos y el destino final antes de pulsar **Retry**.

La aceptación de un reinicio completo requiere un host real de prueba y sus
propias evidencias. Sigue el [procedimiento de reboot](reboot-acceptance.md);
no se deduce de una suite verde ni de tener una unidad systemd habilitada.
Las [campañas de caos](chaos-testing.md) documentan las pruebas reproducibles con
proveedores simulados.

## Copias y actualizaciones

La cola, el catálogo y las portadas alternativas contienen información que no
se puede reconstruir solo a partir de los MP3. Conserva una copia de:

- `LIBRARY_PATH` y `STAGING_PATH`.
- `QUEUE_STATE_PATH` y `PUBLICATION_CATALOG_PATH`.
- `COVER_STORAGE_PATH` y la configuración del servicio, incluido `.env`.

`COVER_ART_CACHE_PATH` contiene solo la caché regenerable de Cover Art Archive;
no es necesaria para restaurar el estado durable y puede quedar fuera de la
copia. Mantén esa caché separada de `COVER_STORAGE_PATH`.

Con las rutas predeterminadas de Docker, los datos están bajo el mismo mount
`/music`; `.env` permanece en el host. En instalación nativa pueden estar en
ubicaciones diferentes. Protege la copia de `.env`, que contiene credenciales.

Para obtener una copia coherente antes de actualizar, deja terminar el trabajo
activo y detén el servicio. Copia los directorios persistentes con el proceso
parado, incluido el directorio del catálogo con sus archivos auxiliares si los
hay. Actualiza siguiendo [Docker](docker.md#actualización) o
[systemd](installation-native.md#actualización), y después comprueba estado,
cola y últimas publicaciones.
