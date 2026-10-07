<div align="center">

# SIMEX-RACSO

### Simulador de eventos de colisión con clúster MPI de bajo costo

Validación cinemática con datos reales del CMS Open Data y simulación Monte Carlo con masa invariante controlada en un clúster MPI de Raspberry Pi 3B+.

[![License: MIT](https://img.shields.io/badge/License-MIT-7a1f1f.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![MPICH](https://img.shields.io/badge/MPI-MPICH%204.3.2-EE4C2C)](https://www.mpich.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2B-0078D6)](https://www.microsoft.com/windows)
[![Website](https://img.shields.io/badge/Sitio_Web-SIMEX--RACSO-7a1f1f)](https://simex-racso.liminalcoded.com/)

**Autor:** Oscar Pablo Morales Zuñiga
**Institución:** BUAP — FCFM / UVEG — Ingeniería en Sistemas Computacionales
**Congreso SMF 2026** — División de Partículas y Campos
**Contacto:** oscaripingui@gmail.com · [+52 744-153-5937](tel:+527441535937)

[Descargar instalador](https://github.com/OscarPab/SIMEX-RACSO/releases/latest) · [Reportar un problema](https://github.com/OscarPab/SIMEX-RACSO/issues) · [Ver código](https://github.com/OscarPab/SIMEX-RACSO)

</div>

---

## Tabla de contenidos

- [¿Qué es SIMEX-RACSO?](#qué-es-simex-racso)
- [Características principales](#características-principales)
- [Requisitos previos](#requisitos-previos)
- [Instalación](#instalación)
- [Uso paso a paso](#uso-paso-a-paso)
- [Cómo funciona por dentro](#cómo-funciona-por-dentro)
- [Compilar desde el código fuente](#compilar-desde-el-código-fuente)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Rendimiento y benchmarks](#rendimiento-y-benchmarks)
- [Física involucrada](#física-involucrada)
- [Referencias académicas](#referencias-académicas)
- [Licencia](#licencia)
- [Agradecimientos](#agradecimientos)

---

## ¿Qué es SIMEX-RACSO?

**SIMEX-RACSO** es una aplicación de escritorio que sirve para dos cosas a la vez:

1. **Validar cinemática relativista contra datos reales del CERN.** La app lee el dataset público *DoubleMu 2011A* del [CMS Open Data](http://opendata.cern.ch/record/700), filtra eventos por rango de masa, **recalcula la masa invariante** de cada par de muones usando la fórmula relativista y compara el resultado contra la columna `M` que el propio CMS ya publicó.

2. **Generar eventos desde cero con Monte Carlo.** Un kernel MPI construye eventos nuevos con una masa objetivo fija, usando la fórmula de masa invariante como **restricción física** (no como post-procesado). El usuario controla la masa, la resolución experimental `σ` y los rangos cinemáticos.

Ambas rutas alimentan pestañas de **reconstrucción visual 3D** donde se ve la geometría de cada colisión, y todo el procesamiento se puede repartir entre los hilos de una PC o entre los nodos de un **clúster de Raspberry Pi** vía SSH + MPICH.

> El nombre viene de "SIMulación de EXperimentos" y "RACSO" (Oscar al revés).

---

## Características principales

| Módulo | Descripción |
|---|---|
| **Hilos Local** | Benchmark Monte Carlo puro para medir el overhead de MPI sin I/O. |
| **Colisiones Local** | Recalcula la masa invariante del dataset del CMS con 4 pruebas base: J/ψ, Υ, Z y Higgs. |
| **Hilos RPi** | Igual que *Hilos Local* pero repartido entre nodos Raspberry Pi 3B+. |
| **Colisiones RPi** | Igual que *Colisiones Local* pero en el clúster. |
| **Simulación Local** | Genera eventos Monte Carlo con masa invariante controlada. |
| **Simulación RPi** | Igual, pero distribuido entre las Raspberry Pi. |
| **Reconstrucción** | Animación 3D de eventos reales del CMS. |
| **Reconstrucción Simulada** | Animación 3D de eventos generados por Monte Carlo. |
| **Reporte PDF** | Compila tablas y gráficas en un PDF académico. |

Además:

- **Detección automática de recursos.** Cuenta los hilos lógicos de la CPU con `os.cpu_count()` y escanea la red local buscando Raspberry Pi por MAC.
- **4 pruebas base editables.** Cada resonancia tiene un rango de masa y un σ experimental que el usuario puede cambiar.
- **Caché binario del CSV.** La primera vez se parsea el CSV con `fgets`+`strtod` (bajo nivel en C), se guarda un `.dat` binario y las siguientes ejecuciones cargan el CSV en milisegundos.
- **Sin pérdida de eventos.** Uso `MPI_Scatterv`/`MPI_Gatherv` para repartir el trabajo entre procesos sin descartar eventos del dataset.
- **Sin fugas de memoria.** La animación 3D reutiliza los artistas de Matplotlib en vez de recrearlos por frame.
- **Procesos hijos controlados.** Uso `subprocess.Popen` + `terminate()`/`kill()` para que no queden procesos zombis en las Raspberry Pi.

---

## Requisitos previos

Antes de ejecutar la aplicación, necesitas instalar **WSL2 con Ubuntu** y los paquetes de MPI.

### 1. Instalar WSL2 con Ubuntu

Abre **PowerShell como administrador** y ejecuta:

```powershell
wsl --install -d Ubuntu
```

El sistema descarga la imagen de Ubuntu y te pide reiniciar. Después del reinicio, Ubuntu se abre sola y te pide crear un usuario y contraseña.

### 2. Instalar los paquetes de MPI dentro de Ubuntu

Abre la terminal de Ubuntu (menú Inicio → Ubuntu) y ejecuta:

```bash
sudo apt update
sudo apt install -y mpich build-essential
```

Esto instala `mpicxx`, `mpirun` (MPICH Hydra) y `g++`, que son los que compilan y ejecutan los kernels C++.

Si por alguna razón tu sistema ya tiene OpenMPI y quieres desinstalarlo:

```bash
sudo apt remove -y libopenmpi-dev openmpi-bin
sudo apt autoremove -y
```

### 3. (Solo para el clúster RPi) Configurar SSH sin contraseña

Si vas a usar las pestañas RPi, necesitas que Ubuntu pueda entrar por SSH a cada Raspberry Pi sin pedir contraseña:

```bash
ssh-keygen -t ed25519 -N ""
ssh-copy-id pi@192.168.1.XX
```

Repite el `ssh-copy-id` por cada Pi del clúster.

### Verificación rápida

Desde Ubuntu, comprueba las instalaciones:

```bash
mpicxx --version
mpirun --version
```

La salida esperada de `mpirun --version` es algo así:

```text
HYDRA build details:
    Version:                                 4.3.2
    Release Date:                            ...
    Process Manager:                         pmi
    Launchers available:                     ssh rsh fork slurm ll lsf sge manual persist
```

Si ves `Process Manager: pmi` y `Launchers available: ssh`, todo está listo.

---

## Instalación

### Opción A — Instalador (recomendado para Windows)

1. Ve a la sección Releases en GitHub.
2. Descarga `SIMEX-RACSO-Setup-X.Y.Z.exe`.
3. Ejecútalo. No requiere permisos de administrador.
4. Al terminar, abre SIMEX-RACSO desde el menú Inicio o desde el acceso directo del escritorio.
5. La app instala todo en tu AppData Local y crea la entrada de desinstalación en Configuración → Aplicaciones.

### Opción B — Desde el código fuente

```bash
git clone https://github.com/OscarPab/SIMEX-RACSO.git
cd SIMEX-RACSO
pip install -r requirements.txt
python ClusterApp.py
```

El script detecta automáticamente la carpeta `otros/` en la raíz del proyecto y busca el CSV.

---

## Uso paso a paso

### Validar cinemática contra el CMS

1. Abre la pestaña **Pruebas Local** → **Colisiones**.
2. Escoge una prueba base: J/psi, Upsilon o Z.
3. Pulsa **Ejecutar**. El kernel filtra el CSV por rango, recalcula la masa y compara contra la columna M.
4. En la gráfica verás dos curvas superpuestas: la roja (tu recálculo) y la negra punteada (columna M del CMS). Si coinciden, tu cinemática está bien.

### Generar eventos Monte Carlo

1. Abre la pestaña **Pruebas Local** → **Simulación**.
2. Ajusta la masa objetivo, el σ (resolución experimental, en GeV) y los rangos de pT y eta.
3. Pulsa **Ejecutar**.
4. La gráfica mostrará el pico simulado. Con σ = 0 es una línea vertical (delta de Dirac). Con σ > 0 es un pico con ancho, comparable al del detector real.

### Visualizar la geometría de una colisión

1. Abre la pestaña **Reconstrucción**.
2. Elige "Desde CSV (CMS)" o "Desde Simulación".
3. Pulsa **Precomputar eventos (usa MPI)** o **Cargar simulacion_eventos.csv (no usa MPI)**.
4. Mueve el slider para recorrer eventos, pulsa **Reproducir colisión** para la animación 3D de 5 segundos.

### Correr en el clúster de Raspberry Pi

1. En cualquier pestaña RPi, pulsa **Escanear red**. La app busca MACs de Raspberry Pi en la tabla ARP.
2. Verifica que aparezcan los nodos en el combo.
3. Ajusta el usuario SSH (`pi`) y la ruta remota (`~/cluster`).
4. Pulsa **Ejecutar** o **Iniciar benchmark**.
5. Los binarios compilados con `mpicxx` están en la carpeta `dist/`. Cópialos a `~/cluster/` en la Pi maestra la primera vez:

```bash
scp mc_core colision_core anim_core sim_core pi@192.168.1.XX:~/cluster/
```

---

## Cómo funciona por dentro

### Arquitectura general

```text
┌──────────────────────────────────────────────────┐
│  Capa 3: Interfaz gráfica (Python + Tkinter)     │
│  · Paneles, gráficas (Matplotlib), PDFs (FPDF)   │
└─────────────────────┬────────────────────────────┘
                      │ subprocess.Popen
                      ▼
┌──────────────────────────────────────────────────┐
│  Capa 2: Kernels MPI (C++ + MPICH 4.3.2)         │
│  · mc_core       → Monte Carlo puro              │
│  · colision_core → Validación cinemática CMS     │
│  · anim_core     → Precomputación 3D             │
│  · sim_core      → Generación Monte Carlo        │
└─────────────────────┬────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────┐
│  Capa 1: Puente Windows ↔ Linux (WSL2)           │
│  · Compila con mpicxx -O3                        │
│  · Ejecuta con mpirun (Hydra)                    │
│  · Conecta con RPi vía SSH                       │
└──────────────────────────────────────────────────┘
```

### Patrón de distribución de trabajo

Todos los kernels usan el mismo patrón:

1. Rank 0 lee el CSV (o genera su parte si es `sim_core`) y aplica el filtro de masa.
2. Distribuye a los demás procesos con `MPI_Scatterv` (para no perder eventos cuando el total no es múltiplo del número de procesos).
3. Cada proceso calcula en su parte.
4. Los resultados se juntan con `MPI_Reduce` (histogramas) o `MPI_Gatherv` (eventos individuales).

### Optimizaciones clave

- **Lectura de bajo nivel:** uso `fgets` + `strtod` en C en vez de streams de C++. Eso elimina cientos de miles de asignaciones dinámicas.
- **Caché binario:** la primera vez se parsea el CSV y se guarda como `.dat`. Después se lee con `fread` en milisegundos.
- **Reutilización de artistas 3D:** la animación actualiza `_offsets3d` en vez de crear/destruir scatter en cada frame.
- **Sin procesos zombis:** `subprocess.Popen` + `terminate()` tras timeout.

---

## Compilar desde el código fuente

### Generar el `.exe` con PyInstaller

```powershell
pyinstaller --noconfirm --onefile --windowed ^
    --name "SIMEX-RACSO" ^
    --icon "otros\Logo_SIMEX-RACSO.ico" ^
    --add-data "otros;otros" ^
    ClusterApp.py
```

El resultado queda en `dist\SIMEX-RACSO.exe`.

---

## Estructura del proyecto

```text
SIMEX-RACSO/
├── ClusterApp.py              # Código principal (interfaz + lógica)
├── installer.iss              # Script de Inno Setup para el instalador
├── requirements.txt           # Dependencias de Python
├── LICENSE.txt                # Licencia MIT
├── README.md                  # Este archivo
├── dist/                      # Binarios compilados (mc_core, sim_core, etc.)
│   ├── mc_core
│   ├── colision_core
│   ├── anim_core
│   ├── sim_core
│   ├── datos_cern.csv
│   ├── simulacion_eventos.csv
│   └── SIMEX-RACSO.exe
└── otros/                     # Recursos empaquetados
    ├── Logo_SIMEX-RACSO.ico
    ├── logo_buap.jpeg
    ├── uveg_logo.jpg
    └── SMF-Horizontal.png
```

---

## Rendimiento y benchmarks

> **Nota metodológica.** El clúster de 4 nodos Raspberry Pi 3B+ fue
> **simulado computacionalmente** en una estación de trabajo con
> procesador Intel Core i7-1185G7 (4 núcleos físicos @ 3.0 GHz, 16 GB RAM,
> WSL2 Ubuntu 26.04). Cada nodo del clúster se emuló como un proceso MPI
> independiente lanzado con **MPICH 4.3.2** (Hydra process manager).
> Los tiempos etiquetados como **"PC"** son mediciones directas
> promediadas sobre 10 repeticiones. Los tiempos etiquetados como
> **"RPi 3B+"** se obtuvieron aplicando un factor de escalado de **5.4×**,
> calculado a partir de la razón de frecuencias (3.0 GHz / 1.4 GHz = 2.14×)
> y de la diferencia de IPC entre Willow Cove y Cortex-A53 (~2.5×).

### Kernel `mc_core` — Monte Carlo puro (compute-bound)

| Nodos | T PC (s) | T RPi 3B+ (s) | Speedup | Eficiencia |
|:---:|---:|---:|:---:|:---:|
| 1 | 1.952 | 10.539 | 1.00× | 100.0% |
| 2 | 1.034 | 5.585  | 1.89× | 94.3% |
| 3 | 0.817 | 4.412  | 2.39× | 79.6% |
| 4 | 0.651 | 3.518  | **3.00×** | 74.9% |

Fracción paralela: **f = 0.89** (solo ~11% serial).

### Kernel `sim_core` — Simulación cinemática (compute-bound)

| Nodos | T PC (s) | T RPi 3B+ (s) | Speedup | Eficiencia |
|:---:|---:|---:|:---:|:---:|
| 1 | 0.0431 | 0.2328 | 1.00× | 100.0% |
| 2 | 0.0261 | 0.1409 | 1.65× | 82.6% |
| 3 | 0.0218 | 0.1178 | 1.98× | 65.9% |
| 4 | 0.0170 | 0.0916 | **2.54×** | 63.6% |

Fracción paralela: **f = 0.81**.

### Kernel `colision_core` — Validación CMS (I/O-bound)

| Nodos | T PC (s) | T RPi 3B+ (s) | Speedup | Eficiencia |
|:---:|---:|---:|:---:|:---:|
| 1 | 0.0308 | 0.1664 | 1.00× | 100.0% |
| 2 | 0.0185 | 0.1001 | 1.66× | 83.1% |
| 3 | 0.0228 | 0.1233 | 1.35× | 45.0% |
| 4 | 0.0231 | 0.1248 | **1.33×** | 33.3% |

Fracción paralela: **f = 0.33**. El cuello de botella es la lectura secuencial del CSV (14 MB) realizada por el rank 0.

### Kernel `anim_core` — Precomputación 3D (I/O-bound)

| Nodos | T PC (s) | T RPi 3B+ (s) | Speedup | Eficiencia |
|:---:|---:|---:|:---:|:---:|
| 1 | 0.0082 | 0.0442 | 1.00× | 100.0% |
| 2 | 0.0057 | 0.0305 | 1.45× | 72.4% |
| 3 | 0.0077 | 0.0418 | 1.06× | 35.3% |
| 4 | 0.0077 | 0.0414 | **1.07×** | 26.6% |

Fracción paralela: **f = 0.09**. Prácticamente secuencial por el I/O del CSV.

### Interpretación con la Ley de Amdahl

Ajustando `S(p) = 1/[(1−f) + f/p]`, los resultados confirman empíricamente que los kernels **compute-bound** escalan casi linealmente, mientras que los **I/O-bound** quedan atrapados por la fracción secuencial del algoritmo:

```text
Kernel          Fracción serial (s)   Fracción paralela (f)
mc_core               0.11                 0.89
sim_core              0.19                 0.81
colision_core         0.67                 0.33
anim_core             0.91                 0.09
```

---

## Física involucrada

### Masa invariante de dos muones

Para cada evento, tengo la cinemática de dos muones: pT, eta, phi. La masa invariante del sistema es:

```text
m² = 2 · pT₁ · pT₂ · [ cosh(η₁ − η₂) − cos(φ₁ − φ₂) ]
```

donde:

- pT va en GeV/c (momento transverso)
- eta es adimensional (pseudorapidez)
- phi va en radianes (ángulo azimutal)
- m sale en GeV/c²

La fórmula viene de partir del cuadrimomento relativista de cada muón, sumar y calcular el módulo. Al pasar a coordenadas (pT, η, φ) y aplicar identidades hiperbólicas, se simplifica a esa expresión.

### Generación Monte Carlo

El kernel `sim_core` despeja `cos(Δφ)` de la fórmula anterior:

```text
cos(Δφ) = cosh(Δη) − m² / (2 · pT₁ · pT₂)
```

Si el resultado cae fuera de `[-1, 1]`, no hay solución física y se descarta el intento. Si cae dentro, se calcula el ángulo aleatorio y así cada evento sale con la masa objetivo exacta.

### Resonancias usadas en las pruebas

| Resonancia | Masa (GeV) | σ experimental (GeV) | Rango de filtro |
|---|---|---|---|
| J/ψ | 3.096 | 0.05 | [2.5, 3.7] |
| Υ | 9.460 | 0.15 | [8.5, 10.5] |
| Z | 91.1876 | 2.5 | [80, 100] |
| Higgs | 125.0 | 4.0 | [115, 135] |

El dataset es de 2011, por lo que no tiene estadística de Higgs. Ese preset sirve para simulación pero no para validación contra CMS.

---

## Referencias académicas

1. CMS Collaboration (2019). *Events with two muons from 2011 (Primary dataset DoubleMu 2011A)*. CERN Open Data Portal. DOI: 10.7483/OPENDATA.CMS.RZ34.QR6N
2. McCauley, T. (2019). *Dimuon spectrum (educational)*. CERN Open Data Portal.
3. CMS Collaboration (2012). *Observation of a new boson at 125 GeV*. Physics Letters B, 716(1), 30-61.
4. Einstein, A. (1905). *Zur Elektrodynamik bewegter Körper*. Annalen der Physik, 17, 891-921.
5. Minkowski, H. (1908). *Raum und Zeit*. 80. Versammlung deutscher Naturforscher und Ärzte.
6. Landau, L. D., & Lifshitz, E. M. (1975). *The Classical Theory of Fields* (4th ed.). Pergamon Press.
7. Particle Data Group (2012). *Review of Particle Physics*. Physical Review D, 86, 010001.
8. Amdahl, G. M. (1967). *Validity of the single processor approach*. AFIPS SJCC, 30, 483-485.
9. Gropp, W., Lusk, E., & Skjellum, A. (2014). *Using MPI* (3rd ed.). MIT Press.
10. Metropolis, N., & Ulam, S. (1949). *The Monte Carlo Method*. JASA, 44(247), 335-341.

La bibliografía completa (24 referencias) está en la pestaña Referencias de la aplicación.

---

## Licencia

MIT. Ver `LICENSE.txt`.

Eres libre de usar, modificar y redistribuir este software siempre que conserves el aviso de copyright.

---

## Agradecimientos

- Al **CERN** por publicar el dataset del CMS Open Data bajo licencia CC0.
- Al **Particle Data Group** por los valores de masas y constantes.
- A la **Facultad de Ciencias Físico Matemáticas de la BUAP** y a la **UVEG** por el apoyo académico.
- A la **Sociedad Mexicana de Física** por el espacio en la sesión de Partículas y Campos del LXIX Congreso Nacional de Física.
- A **Cristóbal Miguel García Jaimes ("El Chico Partículas")** por su invaluable apoyo, correcciones técnicas y orientación fundamental durante el desarrollo de este proyecto.

<div align="center">

Si este proyecto te sirvió, dale una ⭐ al repositorio.

Hecho con amor y física en Puebla, México.

</div>
