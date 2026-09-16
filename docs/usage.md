# Guía de uso

[Volver al README](../README.md)

## Buscar y seleccionar

Desde el dashboard, pulsa **New download** y busca por **Artist** y **Album**.
Los resultados de YouTube y MusicBrainz se muestran por separado; si un proveedor
falla, puedes seguir viendo los resultados válidos del otro.

**Results per source** limita por igual las playlists y las ediciones de
MusicBrainz. **Max tracks per result** excluye los candidatos cuyo número conocido
de pistas supera el máximo; conserva los que aún no tienen un recuento conocido.

Las listas de pistas de MusicBrainz se cargan progresivamente. Comprueba la
edición, el número de discos y el orden antes de seleccionar. Al elegir una
playlist, Autodrome consulta su manifiesto: la lista de entradas que descargará.
Ese resultado se reutiliza hasta dos minutos y el backend vuelve a validarlo
antes de descargar. Una incompatibilidad de recuentos bloquea la descarga.

Pulsa **Continue to review** para revisar la selección.

## Revisar pistas y destino

**Track compatibility** compara las pistas de YouTube y MusicBrainz por posición.
Utiliza títulos, el nombre del artista para reconocer prefijos y duraciones
cuando están disponibles para señalar coincidencias y posibles diferencias.
Puedes desplegar el detalle para revisar cada pareja.

Esta comparación es informativa: no reordena pistas, cambia metadatos ni certifica
que el audio sea la grabación correcta. Las advertencias de similitud no sustituyen
la revisión de la edición. Los recuentos incompatibles sí impiden descargar.

Cuando están disponibles los nombres definitivos de artista y álbum, la interfaz
comprueba el destino normalizado. Si existe, muestra la ruta relativa y el número
de MP3 que puede leer y bloquea la descarga. También la bloquea si no puede
comprobar el destino con fiabilidad. Los términos de búsqueda no se usan como
nombres definitivos de forma implícita.

Esta comprobación no reserva el nombre: el backend vuelve a verificarlo durante
el trabajo. Consulta [integridad y recuperación](operations.md).

## Metadatos manuales

Si no hay una edición adecuada, selecciona solo la playlist y, en **Review**,
pulsa **Download without MusicBrainz**. Acepta la explicación e introduce los
nombres definitivos de **Artist** y **Album**. Son independientes de los términos
de búsqueda y se conservan en el trabajo y sus reintentos.

En este modo los títulos y el orden proceden de YouTube. No se obtiene fecha,
portada, créditos individuales ni estructura multidisco de MusicBrainz, y no hay
editor de pistas individuales. La cola lo identifica como **Manual metadata**.
Se aplican las mismas comprobaciones de archivos y destino antes de publicar.

## Portadas

Si la edición tiene una portada en Cover Art Archive, se utiliza automáticamente.
Si no la tiene, debes elegir una alternativa antes de encolar:

- La miniatura de la playlist seleccionada.
- Una imagen JPEG, PNG o WebP que subas.
- Continuar sin portada.

El modo manual continúa sin portada. Una miniatura de YouTube no se considera
una portada oficial del álbum.

La vista previa permite comparar el original con el resultado cuadrado. Para
imágenes no cuadradas, **Fit** conserva la imagen con relleno centrado y **Crop**
aplica un recorte centrado; confirma la opción elegida antes de continuar.
Las portadas alternativas se validan y preparan antes de descargar audio.
La portada de Cover Art Archive se valida durante el trabajo, antes de publicarlo.
Los [límites de tamaño y resolución](configuration.md#portadas) son configurables.

La decisión y la referencia a los bytes preparados de una portada alternativa
se guardan con el trabajo, de modo que **Retry** conserva la misma imagen.
Las selecciones preparadas se mantienen mientras las necesite un trabajo
recuperable. Las selecciones abandonadas sin encolar expiran tras 24 horas y se
limpian en barridos acotados al arrancar o preparar otra portada.

## Cola de descargas

El dashboard muestra estados, fases, avance por pista y errores. Desde la cola
puedes cancelar trabajos, reintentar fallos y limpiar el historial. Consulta
[acciones de la cola](operations.md#acciones-de-la-cola) para conocer cuándo se
admite cada acción y qué se conserva.

## Álbumes publicados

**Published albums** muestra las publicaciones registradas por Autodrome. No es
un escáner de toda la música que ya existe en la carpeta de biblioteca.

**View provenance** permite inspeccionar la playlist y su manifiesto, la edición
de MusicBrainz, la correspondencia final de pistas, los metadatos aplicados, la
fuente de la portada, la versión de Autodrome y los SHA-256 de los MP3 publicados.

**Recreate in Review** abre las decisiones históricas en la pantalla de revisión
sin encolar una descarga. Compara por separado las respuestas actuales de
YouTube y MusicBrainz y muestra cambios o errores de consulta. Los datos históricos
se conservan; no se sustituyen silenciosamente por los actuales. El destino
existente sigue bloqueando una nueva descarga sobre el mismo álbum.

Si la publicación usó una portada alternativa, la decisión histórica se muestra
como referencia. Para descargar de nuevo, selecciona y confirma otra vez la imagen
o elige explícitamente continuar sin portada: los bytes preparados del trabajo
original no se restauran desde el historial.
