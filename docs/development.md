# Desarrollo

[Volver al README](../README.md)

## Requisitos

- Python 3.14 y soporte para `venv`.
- `ffmpeg` disponible en `PATH`.
- Deno 2.3.0 o posterior, recomendado para soporte completo de YouTube.
- Una clave de YouTube Data API v3.
- Para construir desde el repositorio: Node.js 22, npm y Bash 5 o posterior.
- Redis en `localhost:6379` es opcional y está desactivado por defecto. Para
  usarlo, configura `REDIS_ENABLED=true`. Sin Redis, Autodrome consulta los
  proveedores originales y conserva igualmente el estado de la cola en disco.

## Preparar el entorno

Desde la raíz de un clon del repositorio:

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
npm ci --prefix frontend
cp .env.example .env
```

Edita `.env` y completa como mínimo `GOOGLE_API_KEY` y `CONTACT_EMAIL`. Revisa
también `LIBRARY_PATH`; se recomienda una ruta absoluta hacia la biblioteca de
música. Usa una biblioteca de pruebas para desarrollo. Consulta la
[configuración completa](configuration.md). No uses `sudo` para instalar
dependencias dentro de `.venv` ni para ejecutar la aplicación.

## Construir el wheel

Para construir el artefacto instalable:

```bash
npm run build --prefix frontend
.venv/bin/python -m build
.venv/bin/python scripts/smoke_wheel.py dist/autodrome-0.2.0-py3-none-any.whl
```

Sustituye el nombre del wheel por el generado a partir de `pyproject.toml`.
Usa un archivo concreto si `dist/` contiene varias versiones.

El build falla si falta `frontend/dist/index.html`. El wheel resultante incluye
la SPA compilada y expone `autodrome`; Node y npm no son dependencias de
runtime. El workflow de releases repite el build y el smoke en un entorno
limpio antes de adjuntar el wheel a la release de GitHub.

## Arranque y parada

Para desarrollo, `./start_autodrome.sh` (o `--dev`) inicia FastAPI y Vite
(`http://127.0.0.1:5173`) y detiene ambos al salir. `npm run dev --prefix frontend`
sigue disponible cuando se gestiona el backend por separado.

```bash
./start_autodrome.sh
```

El script configura el proxy hacia FastAPI. En producción, usa el comando
`autodrome` del wheel instalado siguiendo la [guía nativa](installation-native.md)
o [Docker Compose](docker.md).

No existe un comando CLI soportado para buscar o descargar álbumes.

## Validación y dependencias

Antes de ejecutar los E2E por primera vez, instala el Chromium administrado por
Playwright (CI instala también sus dependencias de sistema):

```bash
npm exec --prefix frontend -- playwright install chromium
```

Ejecuta la validación completa antes de cada commit:

```bash
./check.sh
```

El comando ejecuta comprobaciones Git, instala las dependencias frontend fijadas,
construye Vite, ejecuta la suite backend, construye y prueba el wheel y ejecuta
las pruebas unitarias y E2E del frontend. Un resultado correcto termina con
`All checks passed.`

Las campañas de caos reproducibles son opt-in y solo usan proveedores simulados,
bibliotecas temporales y seeds explícitas. Consulta
[campañas de caos](chaos-testing.md) para ejecutar o reproducir una
campaña.

El [benchmark de concurrencia](download-concurrency-benchmark.md) y la
[aceptación de reboot](reboot-acceptance.md) tienen requisitos de entorno propios.
Pasar la suite local no equivale a completar esos procedimientos en un host real.

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

El workflow `Dependency audit` ejecuta `python-audit` y `frontend-audit` como
jobs independientes: un fallo en uno no impide ejecutar el otro y las
vulnerabilidades siguen produciendo checks fallidos. Se puede ejecutar
manualmente desde GitHub Actions, además de la ejecución semanal.

La revisión de la issue #72 (2026-10-19) detectó avisos frontend existentes que
requieren una actualización separada de `frontend/package-lock.json`:

| Paquete fijado | Aviso | Severidad | Versión corregida |
| --- | --- | --- | --- |
| `@vue/server-renderer@3.5.17` (también afecta al resultado de `vue`) | [GHSA-g2v6-rqmx-r4w6](https://github.com/advisories/GHSA-g2v6-rqmx-r4w6) | Alta | `3.5.42` |
| `source-map-js@1.2.1` | [GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q) | Alta | `1.2.2` |

`npm audit --package-lock-only --audit-level=high --prefix frontend` informó
tres paquetes afectados (dos avisos) en el lock anterior a la #73 y devolvía un
código distinto de cero.
La corrección de `multidict` no modifica estas dependencias ni oculta esos
fallos.

En la misma revisión, `pip-audit` también informó tres avisos existentes en
`aiohttp@3.14.3`: [CVE-2026-111064](https://osv.dev/vulnerability/CVE-2026-111064),
[GHSA-2g87-pp6c-29x5](https://github.com/advisories/GHSA-2g87-pp6c-29x5) y
[CVE-2026-111063](https://osv.dev/vulnerability/CVE-2026-111063), con corrección
indicada en `3.14.4`. Tras actualizar únicamente `multidict` a `6.9.1`, su aviso
desapareció; el job Python seguía fallando por esos avisos de `aiohttp`.

La [ejecución manual en GitHub Actions](https://github.com/Raposo93/autodrome/actions/runs/39327293393)
del commit `c7afa45` verificó ambos jobs independientes: cada auditoría se
ejecutó y falló por los avisos anteriores, sin reportar `multidict`.
La [CI del mismo commit](https://github.com/Raposo93/autodrome/actions/runs/39326746894)
pasó, al igual que `./check.sh` en local.

La #73 actualiza `aiohttp` a `3.14.4` y `yarl` a `1.25.1` (el mínimo requerido
por esa versión de `aiohttp`), conservando los demás pins Python. En frontend,
`npm audit fix --prefix frontend`, sin `--force`, actualiza Vue y sus paquetes
asociados a `3.5.44`, `source-map-js` a `1.2.2` y las dependencias requeridas por
Vue dentro de los rangos compatibles. `frontend/package.json` conserva sus
rangos. Tras estas actualizaciones, `pip-audit` y
`npm audit --package-lock-only --audit-level=high --prefix frontend` pasan sin
avisos. Los dos jobs de auditoría mantienen su independencia y sus códigos de
error.

La [auditoría manual del commit `0c64692`](https://github.com/Raposo93/autodrome/actions/runs/39328467255)
confirmó ambos jobs en verde, sin excepciones ni avisos ignorados.
La [CI del mismo commit](https://github.com/Raposo93/autodrome/actions/runs/39328380425)
pasó backend, frontend y construcción/smoke del contenedor; `./check.sh` también
pasó completo en local.
