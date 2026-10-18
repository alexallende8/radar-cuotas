# Radar de cuotas · actualización automática

Cada mañana GitHub ejecuta `scripts/actualizar.py`, que hace tres cosas:

1. Descarga resultados, tiros y cuotas de football-data.co.uk.
2. Descarga las cuotas de los próximos partidos de The Odds API.
3. Publica el radar en GitHub Pages con los datos nuevos.

No hace falta tener ningún ordenador encendido.

## Puesta en marcha (una sola vez)

1. **Clave de cuotas.** Regístrate gratis en the-odds-api.com. Te llega por correo una clave de 500 créditos al mes. Cada actualización gasta 14 (7 ligas), así que una al día cabe en el plan gratuito.
2. **Cuenta de GitHub.** Crea una en github.com si no la tienes.
3. **Repositorio.** Pulsa **New repository**, ponle de nombre `radar-cuotas`, marca **Public** y pulsa **Create repository**.
4. **Subir los archivos.** Pulsa **uploading an existing file**, arrastra **todo el contenido** de esta carpeta (incluida la carpeta `.github`) y pulsa **Commit changes**. En Mac la carpeta `.github` está oculta: en el Finder pulsa Cmd + Mayús + . para verla. Si no consigues subirla, mira la sección del final.
5. **Guardar la clave.** Ve a Settings › Secrets and variables › Actions › **New repository secret**. En Name escribe `ODDS_API_KEY`, en Secret pega tu clave y pulsa **Add secret**.
6. **Activar la web.** Ve a Settings › Pages › Build and deployment › Source y elige **GitHub Actions**.
7. **Primera ejecución.** Ve a Actions › **Actualizar radar** › **Run workflow**. Tarda 1 o 2 minutos.
8. **Tu dirección.** Cuando aparezca en verde, verás el enlace en el paso «publicar». Tiene la forma `https://TU-USUARIO.github.io/radar-cuotas/`. Ábrelo en el móvil y usa «Añadir a pantalla de inicio».

A partir de ahí se actualiza solo cada día a las 09:30. Para forzar una actualización, repite el paso 7.

## Si un equipo no se empareja

En la pestaña Datos del radar aparece la lista de partidos sin emparejar. Añade el nombre en `scripts/alias.json`, con el formato `"Nombre en la API": "Nombre en football-data"`.

## Si no se pudo subir la carpeta .github

En el repositorio, pulsa Add file › Create new file. Como nombre escribe `.github/workflows/actualizar.yml`, pega el contenido de ese archivo y pulsa Commit.

## Privacidad

El repositorio es público (es la condición de GitHub Pages gratis), pero solo contiene estadísticas y cuotas públicas. Tu seguimiento, tus cuotas escritas a mano y tus ajustes se guardan en tu navegador, no en GitHub. La clave de la API va como secreto y nadie puede verla.
