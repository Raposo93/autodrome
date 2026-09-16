# Instalación nativa con systemd

[Volver al README](../README.md)

Requisitos: Linux con systemd, Python 3.14 con soporte para `venv`, ffmpeg
y Deno 2.3.0 o posterior. Necesitas una clave de YouTube Data API v3 y un email
de contacto para MusicBrainz. Redis es opcional.

La unidad de ejemplo [deploy/autodrome.service](../deploy/autodrome.service) asume
un wheel instalado en `/opt/autodrome/.venv`, el fichero
`/opt/autodrome/.env` y un usuario/grupo no-root `autodrome`. El checkout, Node,
npm, `app.py` y `frontend/` no son necesarios en ese host una vez instalado el
wheel.

Puedes usar otro usuario existente u otra ruta, pero entonces ajusta `User`,
`Group`, `WorkingDirectory`, `EnvironmentFile` y `ExecStart` en la copia de la
unidad.

## Instalación persistente en `/opt/autodrome`

Crea primero el usuario del servicio. El ejemplo usa un usuario de sistema sin
shell interactiva:

```bash
sudo useradd --system --user-group --home-dir /opt/autodrome \
  --shell /usr/sbin/nologin autodrome
```

Si ya existe, no vuelvas a crearlo. Compruébalo con `id autodrome`.

Descarga el wheel de una release o constrúyelo en otra máquina. Desde una cuenta
administrativa normal, indica su ruta en `AUTODROME_WHEEL` e instala el
artefacto sin copiar el repositorio. Obtén también `deploy/autodrome.service` del
código fuente de esa misma [release](https://github.com/raposo93/autodrome/releases)
y conserva su ruta en `AUTODROME_UNIT`:

```bash
AUTODROME_WHEEL=/ruta/autodrome-0.x.y-py3-none-any.whl
AUTODROME_UNIT=/ruta/deploy/autodrome.service
sudo install -d -o "$USER" -g "$(id -gn)" -m 0755 /opt/autodrome
python3.14 -m venv /opt/autodrome/.venv
/opt/autodrome/.venv/bin/python -m pip install "$AUTODROME_WHEEL"
sudo install -o "$USER" -g autodrome -m 0640 /dev/null /opt/autodrome/.env
sudo install -d -o autodrome -g autodrome -m 0750 /opt/autodrome/covers
```

Edita `/opt/autodrome/.env` con esta configuración mínima, sustituyendo los
valores por los tuyos:

```dotenv
GOOGLE_API_KEY=tu-clave-de-youtube
CONTACT_EMAIL=tu-email-de-contacto
LIBRARY_PATH=/ruta/absoluta/a/la/biblioteca
COVER_STORAGE_PATH=/opt/autodrome/covers/selected
```

Consulta la [referencia de configuración](configuration.md) para red, token,
rutas y límites. `VERSION` es opcional
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
`STAGING_PATH`, `QUEUE_STATE_PATH`, `PUBLICATION_CATALOG_PATH` y
`COVER_STORAGE_PATH`, incluidos los directorios donde se crean sus archivos.
Staging y biblioteca deben estar en el mismo filesystem. La forma concreta de
conceder permisos depende de si la biblioteca es exclusiva del servicio o
compartida con otros usuarios.

Antes de instalar la unidad, prueba el mismo arranque que usará systemd:

```bash
cd /opt/autodrome
sudo -u autodrome env \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin \
  /opt/autodrome/.venv/bin/autodrome
```

El proceso sirve frontend, API y WebSocket en
[http://127.0.0.1:5000](http://127.0.0.1:5000) por defecto. Si arranca
correctamente, detén la prueba con `Ctrl+C`. Un fallo aquí suele ser
de configuración, dependencias o permisos y es más fácil de diagnosticar antes
de introducir systemd.

Instala y verifica la unidad:

```bash
sudo install -m 644 "$AUTODROME_UNIT" /etc/systemd/system/autodrome.service
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

## Biblioteca compartida

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

## Biblioteca en otro filesystem

Si la biblioteca vive en un disco o montaje independiente, puedes hacer que
systemd espere explícitamente a ese filesystem. Añade al mismo override:

```ini
[Unit]
RequiresMountsFor=/ruta/a/la/biblioteca
```

Después ejecuta `sudo systemctl daemon-reload` y reinicia el servicio. Esto evita
que Autodrome intente arrancar durante el boot antes de que su biblioteca esté
montada.

## Actualización

Descarga el wheel de la nueva release, detén el servicio, conserva una
[copia de los datos persistentes](operations.md#copias-y-actualizaciones),
actualiza el paquete y vuelve a arrancar. La biblioteca, staging, cola, catálogo
y portadas alternativas configuradas permanecen fuera del wheel:

```bash
AUTODROME_WHEEL=/ruta/autodrome-0.x.y-py3-none-any.whl
sudo systemctl stop autodrome
/opt/autodrome/.venv/bin/python -m pip install --upgrade "$AUTODROME_WHEEL"
sudo systemctl start autodrome
```

Si cambia `deploy/autodrome.service`, vuelve a instalar la unidad y recarga
systemd antes de arrancar. Actualiza `AUTODROME_UNIT` con la ruta del archivo
de la nueva versión:

```bash
sudo install -m 644 "$AUTODROME_UNIT" /etc/systemd/system/autodrome.service
sudo systemctl daemon-reload
```

## Portadas de Cover Art Archive

En la versión de desarrollo actual, la caché de Cover Art Archive se resuelve
junto al paquete Python (`site-packages/covers` en una instalación wheel), no
en `COVER_STORAGE_PATH`. Una descarga que necesite escribir allí puede fallar
por permisos con el usuario no root del servicio o del contenedor. Es un punto
pendiente de corregir antes de la 0.2; crear `/opt/autodrome/covers` no cambia
esa ruta. `COVER_STORAGE_PATH` controla únicamente las portadas alternativas
preparadas.
