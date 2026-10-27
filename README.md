# Notas Cifradas

App de notas para KDE Plasma (Qt6 / PySide6) cuyo contenido se guarda cifrado con **AES-256-GCM**.
Pensada para CachyOS / Arch, pero funciona en cualquier Linux con Qt6.

## Instalar

Hay tres formas. Las dos últimas se instalan solo para tu usuario, sin root, con el mismo `./install.sh`
(que detecta cuál toca). Aparece como **Notas Cifradas** en el lanzador; `./install.sh --uninstall`
la quita sin borrar tus notas.

### 1) Flatpak con el runtime de KDE (recomendado)

Aspecto Breeze nativo y un sandbox **sin acceso a la red ni a tus archivos**: la app solo puede leer los
colores de Plasma (`kdeglobals`) y escribir en su propia carpeta, así que aunque tuviera un fallo no podría
enviar tus notas a ningún sitio. Usa `org.kde.Platform//6.11` y `io.qt.PySide.BaseApp//6.11` (PySide6
compilado contra el Qt del propio runtime). El `.flatpak` lo compila GitHub Actions y se publica en
[Releases](https://github.com/lumiere11/notas-cifradas/releases).

```bash
flatpak install --user ./notas-cifradas.flatpak      # descarga el runtime de KDE desde Flathub si falta
flatpak run io.github.lumiere11.NotasCifradas
```

Para compilarlo tú mismo (recomendable, es una app de seguridad):

```bash
flatpak install --user flathub org.kde.Platform//6.11 org.kde.Sdk//6.11 io.qt.PySide.BaseApp//6.11
flatpak-builder --user --install --force-clean build-flatpak flatpak/io.github.lumiere11.NotasCifradas.yml
```

La compilación ejecuta las pruebas con el Qt real del runtime y falla si algo no cuadra. Las dependencias de
Python (`cryptography`, `cffi`, `pycparser`) van como ruedas de PyPI con hash fijado; se regeneran con
`flatpak/update-python-deps.py`.

Tus notas quedan en `~/.var/app/io.github.lumiere11.NotasCifradas/data/notas-cifradas/vault.ncv`.
Para llevar una bóveda existente, copia ahí `vault.ncv` con la app cerrada. Dentro del sandbox el bloqueo
automático al bloquear la pantalla depende de que Plasma avise por `org.freedesktop.ScreenSaver`; el aviso
de suspensión del sistema (logind) no está disponible, pero Plasma bloquea la pantalla al suspender.

### 2) Autocontenida: no necesita ninguna dependencia

Incluye dentro su propio Python, Qt6/PySide6 y OpenSSL (con Argon2id). No usa pacman, pip ni el Python del sistema.

```bash
./build-bundle.sh                                   # una vez; necesita python3 e internet para construir
./release/notas-cifradas-linux-x86_64/install.sh
```

El resultado es `release/notas-cifradas-linux-x86_64.tar.gz` (61 MB, ~160 MB instalado), que se puede
copiar a otro PC y allí basta con descomprimir y ejecutar `./install.sh`, sin internet.
Comprueba lo que usa de verdad con `notas-cifradas --selftest`.

- **Construye tú mismo el bundle** en lugar de fiarte de un binario ajeno: es una app de seguridad.
  Las versiones están fijadas en `requirements-build.txt` y el tarball lleva su `.sha256`.
- Sigue necesitando lo que tiene cualquier escritorio Linux: glibc ≥ 2.38 (CachyOS la supera de sobra),
  EGL/GL, fontconfig, dbus y las bibliotecas cliente de Wayland o X11 (en X11 también `xcb-util-cursor`,
  `xcb-util-keysyms`, `xcb-util-wm` y `libxkbcommon-x11`, que Plasma ya trae).
- **Aspecto:** el Qt empaquetado no incluye el estilo Breeze. La app toma entonces de `~/.config/kdeglobals`
  los colores, el tema de iconos y la fuente de Plasma y los aplica sobre el estilo Fusion; se ve
  cercano a Breeze, pero no idéntico (sin sus animaciones ni formas exactas de los controles).

### 3) Con las dependencias del sistema (aspecto Breeze nativo, ~300 KB)

```bash
sudo pacman -S --needed pyside6 python-cryptography   # python-cryptography >= 44 (Argon2id)
./install.sh
```

Sin instalar: `python3 -m notas_cifradas`. Otra bóveda: `notas-cifradas --vault /ruta/archivo.ncv`.

## Cómo protege tus notas

| Pieza | Elección |
|---|---|
| Cifrado | **AES-256-GCM** (autenticado: detecta cualquier modificación). Nonce aleatorio de 96 bits nuevo en cada guardado |
| Clave | **Argon2id**, 512 MiB, 3 pasadas, 4 lanes (~1 s por desbloqueo) → clave de 256 bits |
| Contraseña | Normalizada a Unicode NFKC (la misma contraseña tecleada de distinta forma sirve igual); mínimo 12 caracteres |
| Archivo | Un solo archivo `~/.local/share/notas-cifradas/vault.ncv` (0600). Títulos, número de notas y fechas van dentro del cifrado; el tamaño se redondea a 4 KiB |
| Cabecera | Los parámetros del KDF van en claro pero **autenticados** como AAD: si alguien los altera, el descifrado falla |
| Escritura | Atómica (temporal + `fsync` + `rename`), nunca deja el archivo a medias |

El formato está verificado descifrando un archivo real con otras librerías (argon2-cffi + PyCryptodome),
así que no depende de este programa para recuperar tus datos.

### Extras de seguridad
- **Bloqueo automático** por inactividad (1/5/15/30 min, por defecto 5), al **bloquear la pantalla de Plasma**,
  al **suspender** y, opcionalmente, al minimizar. Al bloquear se descartan la clave y las notas de la interfaz.
- Una sola instancia por bóveda (evita que dos ventanas se pisen).
- Proceso endurecido: sin core dumps y no inspeccionable con `ptrace`/`/proc/PID/mem` por otros procesos
  de tu usuario (desactivable con `NOTAS_NO_HARDEN=1`). En Flatpak solo se desactivan los core dumps: el
  sandbox ya aísla el proceso y `PR_SET_DUMPABLE=0` impediría que los portales identifiquen la aplicación.
- Una copia `vault.ncv.bak` del estado al abrir la sesión (para borrados accidentales). Al **cambiar la
  contraseña maestra se elimina**, porque seguiría abriéndose con la contraseña antigua.

## Uso

`Ctrl+N` nueva · `Ctrl+S` guardar (también se autoguarda al dejar de escribir) · `Ctrl+F` buscar ·
`Ctrl+L` bloquear · `Ctrl+Mayús+Supr` eliminar · `Ctrl+Q` salir.
Menú **Seguridad**: cambiar contraseña, autobloqueo, bloquear al minimizar.

**Si olvidas la contraseña maestra no hay recuperación posible.** Copia `vault.ncv` a algún sitio seguro
de vez en cuando: es un archivo cifrado y se puede guardar en la nube sin problema.

## Límites que conviene conocer

- La seguridad la marca tu contraseña. Una frase de 5+ palabras al azar es mejor que `P@ssw0rd!2026`.
  El medidor de fuerza es solo orientativo.
- Mientras la bóveda está desbloqueada, las notas están en claro en la RAM del proceso. Python no permite
  borrar con garantías las cadenas de texto, así que el bloqueo descarta las referencias pero no puede
  asegurar que la memoria se sobrescriba al instante. Esta app protege **datos en reposo** (disco, copias de
  seguridad, nube); no protege contra malware que ya esté ejecutándose como tu usuario.
- Para cubrir también el swap y las hibernaciones, usa cifrado de disco completo (LUKS) y swap cifrado.
- Borrar `vault.ncv.bak` no es un borrado seguro en SSD/btrfs (copy-on-write); es cifrado, pero con la contraseña antigua.

## Desarrollo

```bash
python3 -m unittest discover -s tests -t .      # 34 pruebas (la GUI se prueba sin pantalla)
```

Parámetros del KDF: `DEFAULT_KDF` en `notas_cifradas/crypto.py`. Se guardan en cada archivo, así que
cambiarlos no rompe bóvedas existentes (se aplican al crear una nueva o al cambiar la contraseña).

## Licencia

[MIT](LICENSE)
