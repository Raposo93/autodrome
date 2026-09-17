# Autodrome

**De una playlist de YouTube a un álbum etiquetado en tu biblioteca.**

Autodrome es una aplicación web autoalojada para buscar álbumes en YouTube,
elegir su edición en MusicBrainz y descargar el audio como MP3 con metadatos y
portada. Revisas la selección en el navegador; Autodrome prepara y valida los
archivos antes de incorporarlos a la biblioteca.

> **Autodrome 0.2.0**: consulta las [notas de versión](docs/v0.2.0-release-notes.md)
> y los artefactos en [GitHub Releases](https://github.com/raposo93/autodrome/releases).

## Qué puedes hacer

- **Buscar y comparar ediciones.** Playlists de YouTube y releases de MusicBrainz,
  con listas de pistas y una comparación de títulos y duraciones para ayudarte
  a revisar la correspondencia.
- **Revisar antes de descargar.** Comprueba el destino y la portada; usa metadatos
  de MusicBrainz, incluidos créditos y varios discos, o introduce artista y
  álbum manualmente.
- **Elegir una portada alternativa.** Si la edición no tiene portada en Cover
  Art Archive, puedes usar la miniatura de la playlist, subir una imagen o
  continuar sin ella. Las alternativas permiten ajuste cuadrado o recorte.
- **Gestionar la cola.** Sigue el progreso por pista, cancela trabajos y
  reintenta fallos conservando su historial.
- **Consultar lo publicado.** Inspecciona fuentes, metadatos, correspondencia de
  pistas y checksums. Recupera una selección histórica en la pantalla de revisión.
- **Comprobar el sistema.** Consulta almacenamiento, dependencias y proveedores
  desde **System status**.

## Cómo se usa

1. Pulsa **New download** y busca por artista y álbum.
2. Selecciona una playlist y la edición de MusicBrainz correspondiente.
3. En **Review**, revisa pistas, destino y portada. Si no encuentras una edición
   adecuada, puedes confirmar metadatos manuales.
4. Encola la descarga y sigue su avance desde el dashboard.

El resultado se organiza bajo `Artista/Álbum/`, con los MP3 etiquetados y la
portada embebida cuando se ha elegido una. La interfaz está en inglés.
Consulta la [guía de uso](docs/usage.md) para los detalles de selección,
portadas y publicaciones.

## Instalación

**Docker Compose es la opción más directa.** La imagen incluye el frontend,
Python, ffmpeg, yt-dlp/EJS y Deno. Necesitas Docker con Compose, una clave de
YouTube Data API v3, un email de contacto para MusicBrainz y una carpeta de
música con permisos de escritura.

Sigue la [guía de Docker Compose](docs/docker.md) para obtener los archivos,
configurar `.env` y preparar la biblioteca. Después:

```bash
docker compose pull
docker compose up -d
```

Abre [http://127.0.0.1:5000](http://127.0.0.1:5000) e introduce el `API_TOKEN`
que configuraste. El puerto se publica solo en loopback por defecto; la guía
explica el acceso desde otros equipos y las actualizaciones.

También puedes instalar el wheel con Python 3.14 y ejecutarlo como
[servicio systemd](docs/installation-native.md). Redis es opcional y está
desactivado por defecto.

## Cómo cuida la biblioteca

Cada álbum se prepara en un directorio temporal de trabajo (*staging*), en el
mismo filesystem que la biblioteca. Antes de publicarlo se comprueban los MP3,
su cantidad, sus etiquetas y el tamaño de las portadas embebidas. El destino se
comprueba antes de descargar y antes de publicar; los álbumes existentes se
rechazan.

La cola se guarda en disco. Tras un reinicio, los trabajos en espera continúan
y los que estaban ejecutándose quedan como interrumpidos para su revisión.
Si un fallo ocurre al publicar, el álbum puede estar completo aunque el trabajo
no figure como terminado: revisa la biblioteca antes de reintentar. Consulta
[operación y recuperación](docs/operations.md).

## Alcance y límites

- Un único proceso backend y un álbum activo cada vez. Las pistas se descargan
  secuencialmente por defecto; la concurrencia es configurable entre 1 y 4.
- La comparación de pistas es orientativa: no identifica el audio ni reordena
  la playlist. Debes elegir la edición y el orden correctos.
- La cancelación de un trabajo activo puede esperar a que termine una operación
  en curso y deja de admitirse al comenzar la publicación final.
- El modo manual usa los títulos y el orden de YouTube; no ofrece edición por
  pista ni metadatos multidisco de MusicBrainz.
- La disponibilidad de YouTube, MusicBrainz y Cover Art Archive puede impedir
  completar una descarga. Un error de proveedor no se trata como un resultado vacío.

## Documentación y desarrollo

| Necesitas… | Guía |
| --- | --- |
| Instalar o actualizar con Docker | [Docker Compose](docs/docker.md) |
| Instalar el wheel como servicio Linux | [Instalación nativa](docs/installation-native.md) |
| Ajustar rutas, red, portadas o proveedores | [Configuración](docs/configuration.md) |
| Seleccionar un álbum y revisar sus fuentes | [Guía de uso](docs/usage.md) |
| Diagnosticar fallos o recuperar trabajos | [Operación y recuperación](docs/operations.md) |
| Ejecutar desde el código, probar o construir | [Desarrollo](docs/development.md) |

El proyecto usa FastAPI y Vue/Vite. La validación completa se ejecuta con
`./check.sh`; la guía de desarrollo incluye la preparación del entorno.

## Uso responsable

Utiliza Autodrome con contenido que tengas permiso para descargar y almacenar.
