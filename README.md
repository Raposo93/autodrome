# Autodrome

Autodrome es una herramienta CLI para descargar discos completos desde YouTube y etiquetar automáticamente sus pistas utilizando metadatos reales de MusicBrainz. La aplicación está escrita en Python y sigue buenas prácticas de diseño modular, preparación para logging, testing y futura expansión a interfaz web.

## Funcionalidades actuales (MVP)

- Búsqueda de playlists en YouTube relacionadas con un artista y álbum.
- Selección manual de playlist y release.
- Descarga de playlist en formato MP3 usando `yt-dlp`.
- Consulta de metadatos reales en MusicBrainz (release y lista de tracks).
- Etiquetado automático de los archivos MP3:
  - Título
  - Número de pista
  - Álbum
  - Artista
  - Portada embebida en cada archivo (si está disponible)
- Organización de los archivos descargados en una carpeta temporal (aún sin mover a biblioteca definitiva).

## Requisitos

- Python 3.8+
- yt-dlp
- ffmpeg
- Entorno virtual recomendado (`venv`)
- `.env` con:
  - `GOOGLE_API_KEY`
  - `CONTACT_EMAIL`
  - `VERSION`
  - `LOG_LEVEL` (opcional, por defecto `INFO`)

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
Uso
bash
Copy
Edit
```

## Uso

```bash
python autodrome.py
```

El sistema te pedirá el nombre del artista y del álbum. Luego mostrará posibles playlists y releases para que elijas.

## Staging y publicación de la biblioteca

Los álbumes se preparan por completo en un directorio de staging y se publican
con un único rename en el mismo sistema de archivos. Por defecto, un álbum ya
existente nunca se sobrescribe y los restos de un trabajo fallido se conservan
para poder diagnosticarlos o reintentarlos.

La política se configura mediante estas variables de entorno:

- `LIBRARY_PATH`: raíz de la biblioteca.
- `STAGING_PATH`: staging; por defecto, `LIBRARY_PATH/.autodrome-staging`.
- `MIN_STAGING_FREE_BYTES`: espacio libre mínimo antes de descargar; por defecto,
  1 GiB.
- `PRESERVE_FAILED_STAGING`: `true` conserva fallos y `false` los elimina; por
  defecto, `true`.
- `MAX_EMBEDDED_COVER_BYTES`: tamaño máximo permitido al validar una portada
  incrustada; por defecto, 1 MiB.

## Descargo de responsabilidad legal

Este proyecto se proporciona únicamente con fines educativos y personales.

No se autoriza ni se fomenta el uso de Autodrome para descargar, distribuir o almacenar contenido protegido por derechos de autor sin el consentimiento de los titulares correspondientes. El autor de este software no se responsabiliza del uso indebido que otros puedan hacer del mismo. Cada usuario es responsable de cumplir con las leyes de propiedad intelectual de su país.
