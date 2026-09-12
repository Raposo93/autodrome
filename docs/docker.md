# Despliegue con Docker Compose

La imagen estable de Autodrome se publica para `linux/amd64` en
`ghcr.io/raposo93/autodrome`. Contiene el wheel instalable, frontend compilado,
Python 3.14, ffmpeg, yt-dlp/EJS y Deno. El proceso ejecuta `autodrome` como UID y
GID 10001 por defecto; Node, npm, Git y el launcher de desarrollo no forman
parte del runtime.

## Preparación

Copia la configuración y edita los valores obligatorios:

```bash
cp .env.example .env
```

- `GOOGLE_API_KEY` y `CONTACT_EMAIL` son obligatorios.
- `API_TOKEN` debe contener al menos 32 caracteres porque el proceso escucha en
  `0.0.0.0` dentro del contenedor. Usa un valor aleatorio y no lo confirmes en
  Git.
- `MUSIC_PATH` identifica el directorio del host montado como `/music`.
- Fija `AUTODROME_IMAGE` a una versión estable concreta para actualizaciones
  controladas, por ejemplo `ghcr.io/raposo93/autodrome:0.x.y`. `latest` sólo se
  publica al crear una release estable, nunca desde `main`.

Crea el directorio exacto si aún no existe y concede acceso al UID/GID efectivo
del contenedor. El valor predeterminado es 10001:10001:

```bash
sudo install -d -o 10001 -g 10001 -m 0750 /srv/autodrome-music
```

Configura entonces `MUSIC_PATH=/srv/autodrome-music`. Si la biblioteca ya
existe o está compartida, no cambies recursivamente su propietario sin revisar
el alcance: usa un UID/GID que ya tenga acceso, ACLs o un grupo compartido y
refleja esos números en `AUTODROME_UID` y `AUTODROME_GID`.

## Arranque y red

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f autodrome
```

Compose publica `127.0.0.1:5000` por defecto. Para acceso desde otra máquina se
puede cambiar `AUTODROME_BIND_ADDRESS`, pero no se recomienda exponer Autodrome
directamente a Internet. Usa reverse proxy HTTPS y firewall; el `API_TOKEN`
sigue siendo obligatorio y el frontend lo intercambia por tickets WebSocket de
un solo uso.

El healthcheck consulta únicamente el frontend servido en loopback dentro del
contenedor. No contacta YouTube, MusicBrainz ni Redis, así que una caída de un
proveedor externo no reinicia el proceso. La página `/status` mantiene los
diagnósticos detallados, incluida la versión de Deno.

## Persistencia e integridad

El compose aplica esta topología dentro de un único bind mount:

```text
/music
├── Artist/
├── .autodrome-staging/
├── .autodrome-queue.json
└── .autodrome-covers/
```

Staging y biblioteca permanecen en el mismo filesystem para conservar la
publicación atómica. La cola y las portadas alternativas necesarias para Retry
sobreviven a recreaciones del contenedor. No configures `STAGING_PATH` en otro
volumen: un rename entre filesystems puede fallar con `EXDEV`.

Redis no forma parte del compose y permanece opcional. La fuente de verdad es
el filesystem montado, no una caché.

## Actualización

Después de cambiar `AUTODROME_IMAGE` a la versión deseada:

```bash
docker compose pull
docker compose up -d
docker compose ps
```

No uses `docker compose down -v` sobre una configuración modificada con
volúmenes de datos que quieras conservar. El compose distribuido usa un bind
mount y una recreación normal no elimina la biblioteca, staging, cola ni
portadas.

## Build local

El mismo `Dockerfile` multi-stage construye primero Vue, genera el wheel y lo
instala en la imagen final con las versiones de `requirements.lock` como
constraints:

```bash
AUTODROME_COMMIT="$(git rev-parse HEAD)" docker compose build
docker compose up -d
```

La imagen final ejecuta `CMD ["autodrome"]` como un único worker. Deno está
fijado en el Dockerfile y no se descarga ni actualiza durante el arranque.
