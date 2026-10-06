<div align="center">

# SIMEX-RACSO

### Simulador de eventos de colisión con clúster MPI de bajo costo

Validación cinemática con datos reales del CMS Open Data y simulación Monte Carlo con masa invariante controlada.

[![License: MIT](https://img.shields.io/badge/License-MIT-7a1f1f.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![MPI](https://img.shields.io/badge/MPI-OpenMPI-EE4C2C)](https://www.open-mpi.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2B-0078D6)](https://www.microsoft.com/windows)

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

Ambas rutas alimentan pestañas de **reconstrucción visual 3D** donde se ve la geometría de cada colisión, y todo el procesamiento se puede repartir entre los hilos de una PC o entre los nodos de un **clúster de Raspberry Pi** vía SSH + OpenMPI.

> El nombre viene de "SIMulación de EXperimentos" y "RACSO" (Oscar al revés).

---

## Características principales

| Módulo | Descripción |
|---|---|
| **Hilos Local** | Benchmark Monte Carlo puro para medir el overhead de MPI sin I/O. |
| **Colisiones Local** | Recalcula la masa invariante del dataset del CMS con 4 pruebas base: J/ψ, Υ, Z y Higgs. |
| **Hilos RPi** | Igual que *Hilos Local* pero repartido entre nodos Raspberry Pi. |
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

Antes de ejecutar la aplicación, necesitas instalar **WSL2 con Ubuntu** y los paquetes de MPI. Sigue estos pasos:

### 1. Instalar WSL2 con Ubuntu

Abre **PowerShell como administrador** y ejecuta:

    wsl --install -d Ubuntu

El sistema descarga la imagen de Ubuntu y te pide reiniciar. Después del reinicio, Ubuntu se abre sola y te pide crear un usuario y contraseña.

### 2. Instalar los paquetes de MPI dentro de Ubuntu

Abre la terminal de Ubuntu (menú Inicio → Ubuntu) y ejecuta:

    sudo apt update
    sudo apt install -y libopenmpi-dev openmpi-bin build-essential

Esto instala `mpicxx`, `mpirun` y `g++`, que son los que compilan y ejecutan los kernels C++.

### 3. (Solo para el clúster RPi) Configurar SSH sin contraseña

Si vas a usar las pestañas RPi, necesitas que Ubuntu pueda entrar por SSH a cada Raspberry Pi sin pedir contraseña:

    ssh-keygen -t ed25519 -N ""
    ssh-copy-id pi@192.168.1.XX    # repite por cada Pi

### Verificación rápida

Desde Ubuntu, comprueba las instalaciones:

    mpicxx --version    # debe mostrar "g++ ..."
    mpirun --version    # debe mostrar "mpirun (Open MPI) ..."

Si ambos comandos responden, todo está listo.

---

## Instalación

### Opción A — Instalador (recomendado para Windows)

1. Ve a la sección Releases en GitHub.
2. Descarga `SIMEX-RACSO-Setup-X.Y.Z.exe`.
3. Ejecútalo. No requiere permisos de administrador.
4. Al terminar, abre SIMEX-RACSO desde el menú Inicio o desde el acceso directo del escritorio.
5. La app instala todo en tu AppData Local y crea la entrada de desinstalación en Configuración → Aplicaciones.

### Opción B — Desde el código fuente

    git clone [https://github.com/OscarPab/SIMEX-RACSO.git](https://github.com/OscarPab/SIMEX-RACSO.git)
    cd SIMEX-RACSO
    pip install -r requirements.txt
    python ClusterApp.py

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
3. Ajusta el usuario SSH (pi) y la ruta remota (`~/cluster`).
4. Pulsa **Ejecutar** o **Iniciar benchmark**.
5. Los binarios compilados con `mpicxx` están en la carpeta de la app. Cópialos a `~/cluster/` en la Pi maestra la primera vez:

    scp mc_core colision_core anim_core sim_core pi@192.168.1.XX:~/cluster/

---

## Cómo funciona por dentro

### Arquitectura general

    ┌──────────────────────────────────────────────────┐
    │  Capa 3: Interfaz gráfica (Python + Tkinter)    │
    │  · Paneles, gráficas (Matplotlib), PDFs (FPDF)  │
    └─────────────────────┬────────────────────────────┘
                          │ subprocess.Popen
                          ▼
    ┌──────────────────────────────────────────────────┐
    │  Capa 2: Kernels MPI (C++ + OpenMPI)            │
    │  · mc_core       → Monte Carlo puro             │
    │  · colision_core → Validación cinemática CMS    │
    │  · anim_core     → Precomputación 3D            │
    │  · sim_core      → Generación Monte Carlo       │
    └─────────────────────┬────────────────────────────┘
                          │
                          ▼
    ┌──────────────────────────────────────────────────┐
    │  Capa 1: Puente Windows ↔ Linux (WSL2)          │
    │  · Compila con mpicxx -O3                        │
    │  · Ejecuta con mpirun                            │
    │  · Conecta con RPi vía SSH                       │
    └──────────────────────────────────────────────────┘

### Patrón de distribución de trabajo

Todos los kernels usan el mismo patrón:

1. Rank 0 lee el CSV (o genera su parte si es `sim_core`) y aplica el filtro de masa.
2. Distribuye a los demás procesos con `MPI_Scatterv` (para no perder eventos cuando el total no es múltiplo del número de procesos).
3. Cada proceso calcula en su parte.
4. Los resultados se juntan con `MPI_Reduce` (histogramas) o `MPI_Gatherv` (eventos individuales).

### Optimizaciones clave

*   **Lectura de bajo nivel:** uso `fgets` + `strtod` en C en vez de streams de C++. Eso elimina cientos de miles de asignaciones dinámicas.
*   **Caché binario:** la primera vez se parsea el CSV y se guarda como `.dat`. Después se lee con `fread` en milisegundos.
*   **Reutilización de artistas 3D:** la animación actualiza `_offsets3d` en vez de crear/destruir scatter en cada frame.
*   **Sin procesos zombis:** `subprocess.Popen` + `terminate()` tras timeout.

---

## Compilar desde el código fuente

### Generar el .exe con PyInstaller

    pyinstaller --noconfirm --onefile --windowed --name "SIMEX-RACSO" --icon "otros\Logo_SIMEX-RACSO.ico" --add-data "otros;otros" ClusterApp.py

El resultado queda en `dist\SIMEX-RACSO.exe`.

---

## Estructura del proyecto

    SIMEX-RACSO/
    ├── ClusterApp.py              # Código principal (interfaz + lógica)
    ├── installer.iss              # Script de Inno Setup para el instalador
    ├── requirements.txt           # Dependencias de Python
    ├── LICENSE.txt                # Licencia MIT
    ├── README.md                  # Este archivo
    ├── otros/                     # Recursos empaquetados
    │   ├── Logo_SIMEX-RACSO.ico
    │   ├── logo_buap.jpeg
    │   ├── uveg_logo.jpg
    │   └── SMF-Horizontal.png


---

## Rendimiento y benchmarks

### Escalabilidad típica

Con un CPU de 8 hilos y 100,000 eventos de simulación:

| Hilos | Tiempo (s) | Speedup |
|---|---|---|
| 1 | 0.050 | 1.00x |
| 2 | 0.031 | 1.59x |
| 4 | 0.014 | 3.56x |
| 6 | 0.013 | 3.73x |
| 8 | 0.018 | 2.79x |

El speedup cae a partir de 6 hilos por la contención de memoria y el overhead de `MPI_Barrier`.

### Clúster de Raspberry Pi

En un clúster de 4 Raspberry Pi 4 (4 GB), el `colision_core` con 100,000 eventos del CMS tarda ~1.3 s por nodo vs ~4.8 s en una sola PC, logrando un speedup de ~3.6x sobre 4 nodos.

La Ley de Amdahl (1967) es la que explica por qué el speedup no es lineal en la vida real.

---

## Física involucrada

### Masa invariante de dos muones

Para cada evento, tengo la cinemática de dos muones: pT, eta, phi. La masa invariante del sistema es:

    m² = 2 · pT₁ · pT₂ · [ cosh(η₁ − η₂) − cos(φ₁ − φ₂) ]

donde:

*   pT va en GeV/c (momento transverso)
*   eta es adimensional (pseudorapidez)
*   phi va en radianes (ángulo azimutal)
*   m sale en GeV/c²

La fórmula viene de partir del cuadrimomento relativista de cada muón, sumar y calcular el módulo. Al pasar a coordenadas (pT, η, φ) y aplicar identidades hiperbólicas, se simplifica a esa expresión.

### Generación Monte Carlo

El kernel `sim_core` despeja cos(Δφ) de la fórmula anterior:

    cos(Δφ) = cosh(Δη) − m² / (2 · pT₁ · pT₂)

Si el resultado cae fuera de [-1, 1], no hay solución física y se descarta el intento. Si cae dentro, se calcula el ángulo aleatorio y así cada evento sale con la masa objetivo exacta.

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

1. CMS Collaboration (2019). Events with two muons from 2011 (Primary dataset DoubleMu 2011A). CERN Open Data Portal. DOI: 10.7483/OPENDATA.CMS.RZ34.QR6N
2. McCauley, T. (2019). Dimuon spectrum (educational). CERN Open Data Portal.
3. CMS Collaboration (2012). Observation of a new boson at 125 GeV. Physics Letters B, 716(1), 30-61.
4. Einstein, A. (1905). Zur Elektrodynamik bewegter Körper. Annalen der Physik, 17, 891-921.
5. Minkowski, H. (1908). Raum und Zeit. 80. Versammlung deutscher Naturforscher und Ärzte.
6. Landau, L. D., & Lifshitz, E. M. (1975). The Classical Theory of Fields (4th ed.). Pergamon Press.
7. Particle Data Group (2012). Review of Particle Physics. Physical Review D, 86, 010001.
8. Amdahl, G. M. (1967). Validity of the single processor approach. AFIPS SJCC, 30, 483-485.
9. Gropp, W., Lusk, E., & Skjellum, A. (2014). Using MPI (3rd ed.). MIT Press.
10. Metropolis, N., & Ulam, S. (1949). The Monte Carlo Method. JASA, 44(247), 335-341.

La bibliografía completa (24 referencias) está en la pestaña Referencias de la aplicación.

---

## Licencia

MIT. Ver `LICENSE.txt`.

Eres libre de usar, modificar y redistribuir este software siempre que conserves el aviso de copyright.

---

## Agradecimientos

* Al **CERN** por publicar el dataset del CMS Open Data bajo licencia CC0.
* Al **Particle Data Group** por los valores de masas y constantes.
* A la **Facultad de Ciencias Físico Matemáticas de la BUAP** y a la **UVEG** por el apoyo académico.
* A la **Sociedad Mexicana de Física** por el espacio en la sesión de Partículas y Campos del LXIX Congreso Nacional de Física.
* A **Cristóbal Miguel García Jaimes ("El Chico Partículas")** por su invaluable apoyo, correcciones técnicas y orientación fundamental durante el desarrollo de este proyecto.

<div align="center">
Si este proyecto te sirvió, dale una ⭐ al repositorio.
Hecho con amor y física en Puebla, México.
</div>