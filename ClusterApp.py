# ============================================================
#  SIMEX-RACSO
#  Panel de control para el clúster MPI de Raspberry Pi
#
#  Oscar Pablo Morales Zuñiga
#  BUAP - Facultad de Ciencias Físico Matemáticas
#  UVEG - Ingeniería en Sistemas Computacionales
#  oscaripingui@gmail.com | +52 744-153-5937
#  Congreso SMF 2026 - División de Partículas y Campos
# ============================================================

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from tkinter import TclError     # Excepción explícita para after_cancel
import os
import sys
import shutil
import subprocess
import threading
import re
import random
import tempfile
import time
import numpy as np
from datetime import datetime
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import (FigureCanvasTkAgg,
                                                NavigationToolbar2Tk)
from fpdf import FPDF
from PIL import Image, ImageTk


COLORES = {
    "bg":           "#f4f5f7",
    "bg2":          "#ffffff",
    "bg3":          "#eaecef",
    "fg":           "#1a1a1a",
    "fg_dim":       "#5a5a5a",
    "accent":       "#7a1f1f",
    "accent_hi":    "#a83232",
    "border":       "#d5d8dd",
    "console_bg":   "#111418",
    "console_fg":   "#7fff7f",
    "graph_bg":     "#ffffff",
    "graph_grid":   "#d0d0d0",
    "graph_fg":     "#333333",
    "success":      "#1a7f37",
}


# Las cuatro pruebas base. Nombre, rango de masa, masa teórica PDG,
# y ancho experimental típico (sigma en GeV).
PRESETS_MASA = [
    ("Todos",   0.0,   120.0, None,    0.0),
    ("J/psi",   2.5,   3.7,   3.096,   0.05),
    ("Upsilon", 8.5,   10.5,  9.460,   0.15),
    ("Z",       80.0,  100.0, 91.1876, 2.5),
    ("Higgs",   115.0, 135.0, 125.0,   4.0),
]


def ruta_recurso(relativa):
    """Ruta de un archivo empaquetado. Si estoy corriendo desde PyInstaller
    uso sys._MEIPASS, si no, la carpeta de trabajo."""
    base = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base, relativa)


def carpeta_datos():
    """Carpeta donde escribo los CSV y PDFs de salida. Si soy un .exe,
    uso la carpeta del ejecutable para que el usuario encuentre todo
    junto."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")


def rango_de_preset(nombre):
    """Devuelve (m_min, m_max, masa_objetivo, sigma) del preset."""
    for n, mn, mx, masa, sigma in PRESETS_MASA:
        if n == nombre:
            return mn, mx, masa, sigma
    return 0.0, 120.0, None, 0.0


def abrir_archivo(ruta):
    """Abre un archivo con la aplicación por defecto del sistema.
    Windows usa os.startfile; macOS usa 'open'; Linux usa 'xdg-open'.
    Si ninguno funciona, avisa por stderr pero no revienta la app."""
    try:
        if sys.platform.startswith('win'):
            os.startfile(ruta)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', ruta])
        else:
            subprocess.Popen(['xdg-open', ruta])
    except (OSError, AttributeError) as e:
        print(f"[aviso] No pude abrir {ruta}: {e}", file=sys.stderr)


# ============================================================
#  Kernels C++
# ============================================================

CPP_SIMULADOR = r"""
#include <iostream>
#include <random>
#include <mpi.h>
#include <cmath>
int main(int argc, char** argv) {
    MPI_Init(&argc, &argv);
    int rank, size;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);
    MPI_Barrier(MPI_COMM_WORLD);
    double start = MPI_Wtime();
    long long eventos = 50000000 / size;
    volatile double resultado = 0.0;
    std::mt19937 gen(2026 + rank);
    std::uniform_real_distribution<double> dist(0.0, M_PI);
    for(long long i=0; i<eventos; ++i) resultado += std::sin(dist(gen));
    double end = MPI_Wtime();
    if(rank == 0)
        std::cout << "| " << size << " \t| " << (end-start) << " s \t| MONTE_CARLO" << std::endl;
    MPI_Finalize();
    return 0;
}
"""

CPP_COLISION = r"""
#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <cmath>
#include <vector>
#include <cstdlib>
#include <cstdio>
#include <mpi.h>

int main(int argc, char** argv) {
    MPI_Init(&argc, &argv);
    int rank, size;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);

    const int NBINS = 240;
    const int REPS = 200;

    double M_MIN = 0.0;
    double M_MAX = 120.0;
    if (argc > 1) M_MIN = std::atof(argv[1]);
    if (argc > 2) M_MAX = std::atof(argv[2]);
    if (M_MIN >= M_MAX) { M_MIN = 0.0; M_MAX = 120.0; }

    std::vector<double> datos_globales;
    int eventos_totales = 0;

    if (rank == 0) {
        const char* archivo_binario = "cern_cache.dat";
        FILE* bin = fopen(archivo_binario, "rb");

        if (bin) {
            fseek(bin, 0, SEEK_END);
            long bytes = ftell(bin);
            rewind(bin);

            long total_doubles = bytes / sizeof(double);
            std::vector<double> buffer_completo(total_doubles);
            fread(buffer_completo.data(), sizeof(double), total_doubles, bin);
            fclose(bin);

            for (size_t i = 0; i + 6 < buffer_completo.size(); i += 7) {
                double M_filtro = buffer_completo[i + 6];
                if (M_filtro >= M_MIN && M_filtro < M_MAX) {
                    datos_globales.insert(datos_globales.end(),
                                          buffer_completo.begin() + i,
                                          buffer_completo.begin() + i + 7);
                    eventos_totales++;
                }
            }
        } else {
            FILE* csv = fopen("datos_cern.csv", "r");
            if (!csv) {
                fprintf(stderr, "[Error] No se encontro datos_cern.csv\n");
                MPI_Abort(MPI_COMM_WORLD, 1);
            }

            std::vector<double> buffer_completo;
            char linea[2048];

            if (!fgets(linea, sizeof(linea), csv)) {
                fclose(csv);
                MPI_Abort(MPI_COMM_WORLD, 1);
            }

            while (fgets(linea, sizeof(linea), csv)) {
                double v[21] = {0.0};
                char* ptr = linea;
                char* endptr = nullptr;
                int col = 0;

                while (col < 21 && *ptr != '\0' && *ptr != '\n') {
                    if (col == 2 || col == 11) {
                        while (*ptr != ',' && *ptr != '\n' && *ptr != '\0') ptr++;
                        if (*ptr == ',') ptr++;
                        col++;
                        continue;
                    }
                    v[col] = std::strtod(ptr, &endptr);
                    ptr = endptr;
                    while (*ptr != ',' && *ptr != '\n' && *ptr != '\0') ptr++;
                    if (*ptr == ',') ptr++;
                    col++;
                }

                buffer_completo.push_back(v[7]);
                buffer_completo.push_back(v[8]);
                buffer_completo.push_back(v[9]);
                buffer_completo.push_back(v[16]);
                buffer_completo.push_back(v[17]);
                buffer_completo.push_back(v[18]);
                buffer_completo.push_back(v[20]);

                double M_filtro = v[20];
                if (M_filtro >= M_MIN && M_filtro < M_MAX) {
                    datos_globales.insert(datos_globales.end(),
                                          buffer_completo.end() - 7,
                                          buffer_completo.end());
                    eventos_totales++;
                }
            }
            fclose(csv);

            bin = fopen(archivo_binario, "wb");
            if (bin) {
                fwrite(buffer_completo.data(), sizeof(double),
                       buffer_completo.size(), bin);
                fclose(bin);
                printf("[+] Cache binario cern_cache.dat creado.\n");
            }
        }

        eventos_totales -= (eventos_totales % size);
        datos_globales.resize(eventos_totales * 7);
    }

    MPI_Bcast(&eventos_totales, 1, MPI_INT, 0, MPI_COMM_WORLD);
    int eventos_por_hilo = eventos_totales / size;
    int buffer_size = eventos_por_hilo * 7;
    std::vector<double> buffer_local(buffer_size);

    MPI_Barrier(MPI_COMM_WORLD);
    double t_inicio = MPI_Wtime();

    if (buffer_size > 0) {
        MPI_Scatter(datos_globales.data(), buffer_size, MPI_DOUBLE,
                    buffer_local.data(), buffer_size, MPI_DOUBLE,
                    0, MPI_COMM_WORLD);
    }

    std::vector<long long> hist_recalc(NBINS, 0);
    std::vector<long long> hist_cms(NBINS, 0);
    double diff_suma = 0.0, diff_suma2 = 0.0;
    long long n_validos = 0;
    volatile double anti_optimizacion = 0.0;

    for (int rep = 0; rep < REPS; ++rep) {
        bool ultima = (rep == REPS - 1);
        for (int i = 0; i < buffer_size; i += 7) {
            double pt1  = buffer_local[i];
            double eta1 = buffer_local[i+1];
            double phi1 = buffer_local[i+2];
            double pt2  = buffer_local[i+3];
            double eta2 = buffer_local[i+4];
            double phi2 = buffer_local[i+5];
            double M_cms = buffer_local[i+6];

            double d_eta = eta1 - eta2;
            double d_phi = phi1 - phi2;
            double m2 = 2.0 * pt1 * pt2 * (std::cosh(d_eta) - std::cos(d_phi));
            if (m2 <= 0.0) continue;
            double m_recalc = std::sqrt(m2);

            anti_optimizacion += m_recalc + M_cms;

            if (ultima) {
                if (m_recalc >= M_MIN && m_recalc < M_MAX) {
                    int bin = (int)((m_recalc - M_MIN) / (M_MAX - M_MIN) * NBINS);
                    if (bin >= 0 && bin < NBINS) hist_recalc[bin]++;
                }
                if (M_cms >= M_MIN && M_cms < M_MAX) {
                    int bin = (int)((M_cms - M_MIN) / (M_MAX - M_MIN) * NBINS);
                    if (bin >= 0 && bin < NBINS) hist_cms[bin]++;
                }
                double diff = m_recalc - M_cms;
                diff_suma  += diff;
                diff_suma2 += diff * diff;
                n_validos++;
            }
        }
    }

    double t_fin = MPI_Wtime();
    double t_local = t_fin - t_inicio;

    std::vector<long long> hist_recalc_global(NBINS, 0);
    std::vector<long long> hist_cms_global(NBINS, 0);
    MPI_Reduce(hist_recalc.data(), hist_recalc_global.data(), NBINS,
               MPI_LONG_LONG, MPI_SUM, 0, MPI_COMM_WORLD);
    MPI_Reduce(hist_cms.data(), hist_cms_global.data(), NBINS,
               MPI_LONG_LONG, MPI_SUM, 0, MPI_COMM_WORLD);

    double diff_local[3]  = {diff_suma, diff_suma2, (double)n_validos};
    double diff_global[3] = {0.0, 0.0, 0.0};
    MPI_Reduce(diff_local, diff_global, 3, MPI_DOUBLE, MPI_SUM, 0, MPI_COMM_WORLD);

    double t_max = 0.0;
    MPI_Reduce(&t_local, &t_max, 1, MPI_DOUBLE, MPI_MAX, 0, MPI_COMM_WORLD);

    if (rank == 0) {
        double media_diff = 0.0, sigma_diff = 0.0;
        if (diff_global[2] > 0) {
            media_diff = diff_global[0] / diff_global[2];
            double var = diff_global[1] / diff_global[2] - media_diff * media_diff;
            sigma_diff = std::sqrt(var > 0 ? var : 0);
        }

        std::cout << "[+] Rango de masa: [" << M_MIN << ", "
                  << M_MAX << ") GeV" << std::endl;
        std::cout << "[+] Eventos procesados: " << (long long)diff_global[2]
                  << " (x" << REPS << " reps)" << std::endl;
        std::cout << "[+] Diferencia media (recalc - CMS): "
                  << media_diff << " GeV" << std::endl;
        std::cout << "[+] Desviacion estandar de la diferencia: "
                  << sigma_diff << " GeV" << std::endl;
        std::cout << "| " << size << " \t| " << t_max
                  << " s \t| CERN_RECALC" << std::endl;

        std::ofstream out("histograma_colision.csv");
        out << "masa_GeV,recalculado,cms\n";
        for (int b = 0; b < NBINS; ++b) {
            double m_bin = M_MIN + (b + 0.5) * (M_MAX - M_MIN) / NBINS;
            out << m_bin << "," << hist_recalc_global[b] << ","
                << hist_cms_global[b] << "\n";
        }
        out.close();

        std::ofstream st("estadisticas_colision.csv");
        st << "eventos,diff_media,diff_sigma,tiempo_s,m_min,m_max\n";
        st << (long long)diff_global[2] << "," << media_diff << ","
           << sigma_diff << "," << t_max << ","
           << M_MIN << "," << M_MAX << "\n";
        st.close();
    }
    MPI_Finalize();
    return 0;
}
"""

CPP_ANIMACION = r"""
#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <cmath>
#include <vector>
#include <mpi.h>

int main(int argc, char** argv) {
    MPI_Init(&argc, &argv);
    int rank, size;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);

    std::vector<double> datos_globales;
    int eventos_totales = 0;

    if (rank == 0) {
        std::ifstream archivo("datos_cern.csv");
        if (!archivo.is_open()) {
            std::cerr << "[Error] No se encontro datos_cern.csv" << std::endl;
            MPI_Abort(MPI_COMM_WORLD, 1);
        }
        std::string linea;
        std::getline(archivo, linea);
        while (std::getline(archivo, linea)) {
            std::stringstream ss(linea);
            std::string campo;
            double v[21] = {0.0};
            int col = 0;
            while (std::getline(ss, campo, ',') && col < 21) {
                if (col == 2 || col == 11) { col++; continue; }
                try { v[col] = std::stod(campo); } catch (...) {}
                col++;
            }
            datos_globales.push_back(v[7]);
            datos_globales.push_back(v[8]);
            datos_globales.push_back(v[9]);
            datos_globales.push_back(v[16]);
            datos_globales.push_back(v[17]);
            datos_globales.push_back(v[18]);
            datos_globales.push_back(v[20]);
            eventos_totales++;
        }
        archivo.close();
        eventos_totales -= (eventos_totales % size);
        datos_globales.resize(eventos_totales * 7);
    }

    MPI_Bcast(&eventos_totales, 1, MPI_INT, 0, MPI_COMM_WORLD);
    int eventos_por_hilo = eventos_totales / size;
    int buffer_size = eventos_por_hilo * 7;
    std::vector<double> buffer_local(buffer_size);

    MPI_Barrier(MPI_COMM_WORLD);
    double t_inicio = MPI_Wtime();

    MPI_Scatter(datos_globales.data(), buffer_size, MPI_DOUBLE,
                buffer_local.data(), buffer_size, MPI_DOUBLE,
                0, MPI_COMM_WORLD);

    std::vector<double> resultado_local(eventos_por_hilo * 8);

    for (int i = 0, j = 0; i < buffer_size; i += 7, ++j) {
        double pt1  = buffer_local[i];
        double eta1 = buffer_local[i+1];
        double phi1 = buffer_local[i+2];
        double pt2  = buffer_local[i+3];
        double eta2 = buffer_local[i+4];
        double phi2 = buffer_local[i+5];
        double M_cms = buffer_local[i+6];

        double d_eta = eta1 - eta2;
        double d_phi = phi1 - phi2;
        double m2 = 2.0 * pt1 * pt2 * (std::cosh(d_eta) - std::cos(d_phi));
        double m_recalc = (m2 > 0.0) ? std::sqrt(m2) : 0.0;

        resultado_local[j * 8 + 0] = pt1;
        resultado_local[j * 8 + 1] = eta1;
        resultado_local[j * 8 + 2] = phi1;
        resultado_local[j * 8 + 3] = pt2;
        resultado_local[j * 8 + 4] = eta2;
        resultado_local[j * 8 + 5] = phi2;
        resultado_local[j * 8 + 6] = M_cms;
        resultado_local[j * 8 + 7] = m_recalc;
    }

    double t_fin = MPI_Wtime();
    double t_local = t_fin - t_inicio;

    std::vector<double> resultado_global;
    if (rank == 0) resultado_global.resize(eventos_totales * 8);
    MPI_Gather(resultado_local.data(), eventos_por_hilo * 8, MPI_DOUBLE,
               resultado_global.data(), eventos_por_hilo * 8, MPI_DOUBLE,
               0, MPI_COMM_WORLD);

    double t_max = 0.0;
    MPI_Reduce(&t_local, &t_max, 1, MPI_DOUBLE, MPI_MAX, 0, MPI_COMM_WORLD);

    if (rank == 0) {
        std::ofstream out("animacion_eventos.csv");
        out << "pt1,eta1,phi1,pt2,eta2,phi2,M_cms,m_recalc\n";
        for (int j = 0; j < eventos_totales; ++j) {
            for (int k = 0; k < 8; ++k) {
                out << resultado_global[j * 8 + k];
                if (k < 7) out << ",";
            }
            out << "\n";
        }
        out.close();

        std::cout << "[+] Eventos precomputados: " << eventos_totales << std::endl;
        std::cout << "| " << size << " \t| " << t_max
                  << " s \t| ANIMACION" << std::endl;
    }
    MPI_Finalize();
    return 0;
}
"""

CPP_SIMULACION = r"""
#include <iostream>
#include <fstream>
#include <random>
#include <cmath>
#include <vector>
#include <cstdlib>
#include <mpi.h>

int main(int argc, char** argv) {
    MPI_Init(&argc, &argv);
    int rank, size;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);

    int total_eventos    = 100000;
    double masa_objetivo = 91.1876;
    double pt_min        = 10.0;
    double pt_max        = 100.0;
    double eta_min       = -2.4;
    double eta_max       =  2.4;
    double sigma_masa    = 0.0;

    if (argc > 1) total_eventos    = std::atoi(argv[1]);
    if (argc > 2) masa_objetivo    = std::atof(argv[2]);
    if (argc > 3) pt_min           = std::atof(argv[3]);
    if (argc > 4) pt_max           = std::atof(argv[4]);
    if (argc > 5) eta_min          = std::atof(argv[5]);
    if (argc > 6) eta_max          = std::atof(argv[6]);
    if (argc > 7) sigma_masa       = std::atof(argv[7]);

    int base = total_eventos / size;
    int resto = total_eventos % size;
    int eventos_por_proceso = base + (rank == 0 ? resto : 0);

    std::mt19937 gen(2026 + rank * 7919);
    std::uniform_real_distribution<double> dist_pt(pt_min, pt_max);
    std::uniform_real_distribution<double> dist_eta(eta_min, eta_max);
    std::uniform_real_distribution<double> dist_phi(-M_PI, M_PI);
    std::uniform_int_distribution<int>     dist_signo(0, 1);
    std::normal_distribution<double>       dist_masa(masa_objetivo,
                                                      sigma_masa > 0.0 ? sigma_masa : 1.0);

    std::vector<double> eventos_locales;
    eventos_locales.reserve(eventos_por_proceso * 8);

    int generados = 0;
    long long intentos = 0;
    const long long max_intentos = (long long)200 * eventos_por_proceso + 100000;

    MPI_Barrier(MPI_COMM_WORLD);
    double t_inicio = MPI_Wtime();

    while (generados < eventos_por_proceso && intentos < max_intentos) {
        ++intentos;
        double pt1  = dist_pt(gen);
        double eta1 = dist_eta(gen);
        double phi1 = dist_phi(gen);
        double pt2  = dist_pt(gen);
        double eta2 = dist_eta(gen);

        double masa_evento = masa_objetivo;
        if (sigma_masa > 0.0) {
            masa_evento = dist_masa(gen);
            if (masa_evento <= 0.0) continue;
        }

        double deta      = eta1 - eta2;
        double cosh_deta = std::cosh(deta);
        double m2_ev     = masa_evento * masa_evento;
        double cos_dphi  = cosh_deta - m2_ev / (2.0 * pt1 * pt2);
        if (std::abs(cos_dphi) > 1.0) continue;

        double dphi = std::acos(cos_dphi);
        if (dist_signo(gen) == 0) dphi = -dphi;
        double phi2 = phi1 + dphi;
        while (phi2 >  M_PI) phi2 -= 2.0 * M_PI;
        while (phi2 < -M_PI) phi2 += 2.0 * M_PI;

        double m2_calc = 2.0 * pt1 * pt2 *
                         (std::cosh(deta) - std::cos(phi1 - phi2));
        double m_calc = (m2_calc > 0.0) ? std::sqrt(m2_calc) : 0.0;

        eventos_locales.push_back(pt1);
        eventos_locales.push_back(eta1);
        eventos_locales.push_back(phi1);
        eventos_locales.push_back(pt2);
        eventos_locales.push_back(eta2);
        eventos_locales.push_back(phi2);
        eventos_locales.push_back(masa_evento);
        eventos_locales.push_back(m_calc);
        ++generados;
    }

    double t_fin = MPI_Wtime();
    double t_local = t_fin - t_inicio;

    double t_max = 0.0;
    MPI_Reduce(&t_local, &t_max, 1, MPI_DOUBLE, MPI_MAX, 0, MPI_COMM_WORLD);

    long long intentos_global = 0;
    MPI_Reduce(&intentos, &intentos_global, 1, MPI_LONG_LONG, MPI_SUM,
               0, MPI_COMM_WORLD);

    int local_count = (int)eventos_locales.size();
    std::vector<int> counts(size, 0), displs(size, 0);
    MPI_Gather(&local_count, 1, MPI_INT, counts.data(), 1, MPI_INT,
               0, MPI_COMM_WORLD);

    if (rank == 0) {
        displs[0] = 0;
        for (int i = 1; i < size; ++i)
            displs[i] = displs[i-1] + counts[i-1];
    }

    std::vector<double> todos_eventos;
    if (rank == 0) {
        int total_doubles = 0;
        for (int i = 0; i < size; ++i) total_doubles += counts[i];
        todos_eventos.resize(total_doubles);
    }

    MPI_Gatherv(eventos_locales.data(), local_count, MPI_DOUBLE,
                todos_eventos.data(), counts.data(), displs.data(), MPI_DOUBLE,
                0, MPI_COMM_WORLD);

    if (rank == 0) {
        int n_eventos = (int)todos_eventos.size() / 8;

        std::ofstream out("simulacion_eventos.csv");
        out << "pt1,eta1,phi1,pt2,eta2,phi2,M_target,m_calc\n";
        for (int i = 0; i < n_eventos; ++i) {
            for (int j = 0; j < 8; ++j) {
                out << todos_eventos[i*8 + j];
                if (j < 7) out << ",";
            }
            out << "\n";
        }
        out.close();

        std::cout << "[+] Eventos simulados: " << n_eventos << std::endl;
        std::cout << "[+] Masa objetivo: " << masa_objetivo
                  << " GeV  (sigma = " << sigma_masa << " GeV)" << std::endl;
        std::cout << "[+] Intentos totales: " << intentos_global << std::endl;
        std::cout << "| " << size << " \t| " << t_max
                  << " s \t| SIMULACION" << std::endl;
    }

    MPI_Finalize();
    return 0;
}
"""


class PanelGraficas:
    """Panel con canvas de Matplotlib y toolbar visible (zoom/pan)."""

    def __init__(self, parent, opciones, callback,
                 titulo_vista="Vista de gráficas", figsize=(8, 8)):
        self.parent = parent
        self.opciones = opciones
        self.callback = callback
        self.var = tk.StringVar(value=opciones[0][1])
        self.modo = opciones[0][1]

        marco = ttk.LabelFrame(parent, text=titulo_vista, padding=6,
                               style="Card.TLabelframe")
        marco.pack(fill="x", pady=(0, 8))

        for etiqueta, clave in opciones:
            ttk.Radiobutton(marco, text=etiqueta,
                            variable=self.var, value=clave,
                            command=lambda k=clave: self._cambiar(k),
                            style="Modern.TRadiobutton").pack(side="left", padx=8)

        contenedor = ttk.Frame(parent)
        contenedor.pack(fill="both", expand=True)

        hint = ttk.Label(
            contenedor,
            text=("Arrastra con el botón izquierdo para hacer zoom a una "
                  "zona. Usa las herramientas de abajo para pan (mano), "
                  "zoom, home y guardar imagen."),
            font=("Segoe UI", 8, "italic"),
            foreground=COLORES["fg_dim"])
        hint.pack(side="top", fill="x", pady=(0, 4))

        self.fig = Figure(figsize=figsize, dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=contenedor)

        self.toolbar = NavigationToolbar2Tk(self.canvas, contenedor,
                                            pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side="bottom", fill="x")

        self.canvas.get_tk_widget().pack(side="top", fill="both",
                                          expand=True)

    def _cambiar(self, modo):
        self.modo = modo
        self.callback(modo)

    def redibujar(self):
        self.callback(self.modo)

    @staticmethod
    def aplicar_estilo(ax):
        """
        Aplica el tema visual al eje. En proyecciones 3D algunas spines
        no existen, así que atrapo AttributeError que es el único error
        que puede lanzar Matplotlib aquí.
        """
        try:
            ax.set_facecolor(COLORES["graph_bg"])
            ax.tick_params(colors=COLORES["graph_fg"])
            ax.xaxis.label.set_color(COLORES["graph_fg"])
            ax.yaxis.label.set_color(COLORES["graph_fg"])
            ax.title.set_color(COLORES["graph_fg"])
            for borde in ax.spines.values():
                borde.set_color(COLORES["graph_fg"])
            ax.grid(True, linestyle="--", alpha=0.4,
                    color=COLORES["graph_grid"])
        except AttributeError:
            return


class ClusterControlApp:

    def __init__(self, root):
        self.root = root
        self.root.title("SIMEX-RACSO - Simulación de Eventos de Colisión")

        try:
            icono = ruta_recurso(os.path.join("otros", "Logo_SIMEX-RACSO.ico"))
            if os.path.exists(icono):
                img = Image.open(icono).convert("RGBA")
                img = img.resize((64, 64), Image.LANCZOS)
                self._icono = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, self._icono)
        except (FileNotFoundError, OSError) as e:
            print(f"[aviso] No pude cargar el icono: {e}", file=sys.stderr)

        self.root.geometry("1440x980")
        self.root.minsize(1150, 720)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.ruta_windows = carpeta_datos()
        self.ruta_wsl = self.ruta_windows.replace("\\", "/").replace("C:", "/mnt/c")
        self.ruta_otros = ruta_recurso("otros")

        self.hilos_locales = os.cpu_count() or 1
        self.secuencia_hilos = sorted(set(
            [1] + [i for i in range(2, self.hilos_locales + 1, 2)] +
            [self.hilos_locales]
        ))
        self.secuencia_nodos_rpi = [1]
        self.combos_rpi = {}

        self.hilos_mc, self.tiempos_mc = [], []
        self.hilos_col, self.tiempos_col = [], []
        self.hilos_rpi_mc, self.tiempos_rpi_mc = [], []
        self.hilos_rpi_col, self.tiempos_rpi_col = [], []
        self.hilos_sim, self.tiempos_sim = [], []
        self.hilos_rpi_sim, self.tiempos_rpi_sim = [], []

        self._datos_col_masas = None
        self._datos_col_cms = None
        self._datos_col_conteos = None
        self._datos_col_tiempos = None

        self._datos_rpi_col_masas = None
        self._datos_rpi_col_cms = None
        self._datos_rpi_col_conteos = None
        self._datos_rpi_col_tiempos = None

        self._diff_media = 0.0
        self._diff_sigma = 0.0
        self._n_eventos = 0

        self._col_rango_min = 0.0
        self._col_rango_max = 120.0
        self._col_rango_min_rpi = 0.0
        self._col_rango_max_rpi = 120.0

        self._eventos_cms = None
        self._n_eventos_cms = 0
        self._evento_actual = 0

        self._eventos_sim = None
        self._n_eventos_sim = 0
        self._evento_sim_actual = 0

        # Datos de simulación separados por origen. "pc" es la pestaña
        # Simulación Local, "rpi" es la de Raspberry Pi. Los "_datos_sim_*"
        # sin sufijo son el último cargado, los uso en la pestaña de
        # Reconstrucción.
        self._datos_sim_masas_pc = None
        self._datos_sim_conteos_pc = None
        self._datos_sim_masas_rpi = None
        self._datos_sim_conteos_rpi = None

        self._datos_sim_masas = None
        self._datos_sim_conteos = None
        self._sim_xlim_max = 150.0
        self._sim_masa_actual = None
        self._sim_baseline_s = None
        self._sim_rpi_baseline_s = None

        self.rpi_hosts = []
        self.rpi_user = tk.StringVar(value="pi")
        self.rpi_path = tk.StringVar(value="~/cluster")

        self.modo_anim = tk.StringVar(value="pc")

        self.preset_col_pc = tk.StringVar(value="Todos")
        self.preset_col_rpi = tk.StringVar(value="Todos")
        self.preset_sim_pc = tk.StringVar(value="Z")
        self.preset_sim_rpi = tk.StringVar(value="Z")

        self.sim_masa = tk.StringVar(value="91.1876")
        self.sim_sigma = tk.StringVar(value="2.5")
        self.sim_eventos = tk.StringVar(value="100000")
        self.sim_pt_min = tk.StringVar(value="10.0")
        self.sim_pt_max = tk.StringVar(value="100.0")
        self.sim_eta_min = tk.StringVar(value="-2.4")
        self.sim_eta_max = tk.StringVar(value="2.4")

        self.binarios_listos = False
        self.prueba_en_curso = False
        self.proceso_actual = None

        self._copiar_csv()
        self._precargar_cms()
        self._cargar_eventos()
        self._cargar_sim_existente()

        self._estilos()
        self._ui()
        self.compilar_binarios()

    # ---------- manejo de procesos y cierre ----------
    def _matar_proceso_actual(self):
        """Termina el proceso hijo si sigue vivo. Primero terminate(),
        si no muere en 3 s, kill()."""
        if self.proceso_actual is None:
            return
        proc = self.proceso_actual
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    print(f"[aviso] El proceso {proc.pid} no terminó en 3 s, "
                          "forzando kill()", file=sys.stderr)
                    proc.kill()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        print(f"[error] El proceso {proc.pid} sigue vivo "
                              "tras kill()", file=sys.stderr)
        except (OSError, ProcessLookupError) as e:
            print(f"[aviso] Falló terminate/kill del proceso: {e}",
                  file=sys.stderr)

    def _on_close(self):
        """Al cerrar la ventana mato cualquier proceso hijo antes de salir."""
        self._matar_proceso_actual()
        self.root.destroy()

    def _ejecutar_proceso(self, cmd, timeout=300, shell=True):
        """Ejecuta un comando con Popen. Si se pasa de timeout, mata al
        proceso hijo. Devuelve (rc, stdout, stderr)."""
        try:
            if shell:
                self.proceso_actual = subprocess.Popen(
                    cmd, shell=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            else:
                self.proceso_actual = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except (OSError, subprocess.SubprocessError) as e:
            self.proceso_actual = None
            return -1, "", f"No pude lanzar el proceso: {e}"

        try:
            stdout, stderr = self.proceso_actual.communicate(timeout=timeout)
            return self.proceso_actual.returncode, stdout, stderr
        except subprocess.TimeoutExpired:
            self._matar_proceso_actual()
            return -1, "", f"[Timeout] proceso terminado forzosamente tras {timeout} s"
        finally:
            self.proceso_actual = None

    # ---------- estilos ----------
    def _estilos(self):
        c = COLORES
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except TclError as e:
            print(f"[aviso] No pude usar el tema 'clam': {e}",
                  file=sys.stderr)

        self.root.configure(bg=c["bg"])
        self.style.configure(".", background=c["bg"], foreground=c["fg"],
                             fieldbackground=c["bg2"], bordercolor=c["border"])
        self.style.configure("TFrame", background=c["bg"])
        self.style.configure("TLabel", background=c["bg"], foreground=c["fg"],
                             font=("Segoe UI", 10))
        self.style.configure("TButton", background=c["bg2"], foreground=c["fg"],
                             borderwidth=1, relief="flat",
                             font=("Segoe UI", 10), padding=6)
        self.style.map("TButton",
                       background=[("active", c["accent_hi"])],
                       foreground=[("active", "#ffffff")])
        self.style.configure("Accent.TButton", background=c["accent"],
                             foreground="#ffffff",
                             font=("Segoe UI", 10, "bold"), padding=8)
        self.style.map("Accent.TButton",
                       background=[("active", c["accent_hi"])])
        self.style.configure("Play.TButton", background=c["success"],
                             foreground="#ffffff",
                             font=("Segoe UI", 11, "bold"), padding=10)
        self.style.map("Play.TButton",
                       background=[("active", "#116b2e")])
        self.style.configure("Card.TLabelframe", background=c["bg2"],
                             foreground=c["fg"], bordercolor=c["border"],
                             relief="solid", borderwidth=1)
        self.style.configure("Card.TLabelframe.Label", background=c["bg2"],
                             foreground=c["accent"],
                             font=("Segoe UI", 10, "bold"))
        self.style.configure("TNotebook", background=c["bg"],
                             bordercolor=c["border"])
        self.style.configure("TNotebook.Tab", background=c["bg3"],
                             foreground=c["fg"], padding=[14, 8],
                             font=("Segoe UI", 10, "bold"))
        self.style.map("TNotebook.Tab",
                       background=[("selected", c["bg2"])],
                       foreground=[("selected", c["accent"])])
        self.style.configure("TCheckbutton", background=c["bg"],
                             foreground=c["fg"])
        self.style.configure("TRadiobutton", background=c["bg"],
                             foreground=c["fg"])
        self.style.configure("Modern.TRadiobutton", background=c["bg2"],
                             foreground=c["fg"])
        self.style.configure("Treeview", background=c["bg2"],
                             foreground=c["fg"], fieldbackground=c["bg2"],
                             borderwidth=0)
        self.style.configure("Treeview.Heading", background=c["bg3"],
                             foreground=c["accent"],
                             font=("Segoe UI", 10, "bold"))
        self.style.map("Treeview",
                       background=[("selected", c["accent"])],
                       foreground=[("selected", "#ffffff")])
        self.style.configure("TCombobox", fieldbackground=c["bg2"],
                             background=c["bg2"], foreground=c["fg"])
        self.style.configure("TEntry", fieldbackground=c["bg2"],
                             foreground=c["fg"])
        self.style.configure("Horizontal.TScale", background=c["bg"],
                             troughcolor=c["bg3"])
        self.style.configure("Vertical.TScrollbar", background=c["bg2"],
                             troughcolor=c["bg3"], borderwidth=0)

    # ---------- UI principal ----------
    def _ui(self):
        barra = ttk.Frame(self.root)
        barra.pack(fill="x", padx=14, pady=(10, 0))

        ttk.Label(barra, text="SIMEX-RACSO",
                  font=("Segoe UI", 16, "bold"),
                  foreground=COLORES["accent"]).pack(side="left")
        ttk.Label(barra, text="   ·  Validación CMS + Simulación",
                  font=("Segoe UI", 10, "italic"),
                  foreground=COLORES["fg_dim"]).pack(side="left")

        self.lbl_recursos = ttk.Label(
            barra,
            text=f"CPU: {self.hilos_locales} hilos  ·  RPi: 0 nodos",
            font=("Segoe UI", 9, "italic"),
            foreground=COLORES["fg_dim"])
        self.lbl_recursos.pack(side="right", padx=10)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_inicio = ttk.Frame(self.notebook)
        self.tab_local = ttk.Frame(self.notebook)
        self.tab_rpi = ttk.Frame(self.notebook)
        self.tab_recon = ttk.Frame(self.notebook)
        self.tab_reporte = ttk.Frame(self.notebook)
        self.tab_refs = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_inicio,  text="Inicio")
        self.notebook.add(self.tab_local,   text="Pruebas Local")
        self.notebook.add(self.tab_rpi,     text="Pruebas Raspberry Pi")
        self.notebook.add(self.tab_recon,   text="Reconstrucción")
        self.notebook.add(self.tab_reporte, text="Reporte PDF")
        self.notebook.add(self.tab_refs,    text="Referencias")

        self.nb_local = ttk.Notebook(self.tab_local)
        self.nb_local.pack(fill="both", expand=True, padx=6, pady=6)
        self.tab_mc_pc = ttk.Frame(self.nb_local)
        self.tab_col_pc = ttk.Frame(self.nb_local)
        self.tab_sim_pc = ttk.Frame(self.nb_local)
        self.nb_local.add(self.tab_mc_pc,  text="Hilos")
        self.nb_local.add(self.tab_col_pc, text="Colisiones")
        self.nb_local.add(self.tab_sim_pc, text="Simulación")

        self.nb_rpi = ttk.Notebook(self.tab_rpi)
        self.nb_rpi.pack(fill="both", expand=True, padx=6, pady=6)
        self.tab_mc_rpi = ttk.Frame(self.nb_rpi)
        self.tab_col_rpi = ttk.Frame(self.nb_rpi)
        self.tab_sim_rpi = ttk.Frame(self.nb_rpi)
        self.nb_rpi.add(self.tab_mc_rpi,  text="Hilos")
        self.nb_rpi.add(self.tab_col_rpi, text="Colisiones")
        self.nb_rpi.add(self.tab_sim_rpi, text="Simulación")

        self.nb_recon = ttk.Notebook(self.tab_recon)
        self.nb_recon.pack(fill="both", expand=True, padx=6, pady=6)
        self.tab_recon_cms = ttk.Frame(self.nb_recon)
        self.tab_recon_sim = ttk.Frame(self.nb_recon)
        self.nb_recon.add(self.tab_recon_cms, text="Desde CSV (CMS)")
        self.nb_recon.add(self.tab_recon_sim, text="Desde Simulación")

        self.tab_inicio_armar()
        self.tab_mc_pc_armar()
        self.tab_col_pc_armar()
        self.tab_mc_rpi_armar()
        self.tab_col_rpi_armar()
        self.tab_sim_pc_armar()
        self.tab_sim_rpi_armar()
        self.tab_recon_armar()
        self.tab_recon_sim_armar()
        self.tab_reporte_armar()
        self.tab_refs_armar()

    # ---------- utilidades ----------
    def _copiar_csv(self):
        origen = os.path.join(self.ruta_otros, "datos_cern.csv")
        destino = os.path.join(self.ruta_windows, "datos_cern.csv")
        if os.path.exists(origen) and not os.path.exists(destino):
            try:
                shutil.copy(origen, destino)
            except (OSError, shutil.SameFileError) as e:
                print(f"[aviso] No pude copiar datos_cern.csv: {e}",
                      file=sys.stderr)

    def _precargar_cms(self):
        rutas = [os.path.join(self.ruta_windows, "datos_cern.csv"),
                 os.path.join(self.ruta_otros, "datos_cern.csv")]
        ruta = next((r for r in rutas if os.path.exists(r)), None)
        if not ruta:
            return
        try:
            M_cms = np.loadtxt(ruta, delimiter=',', skiprows=1,
                               usecols=20, max_rows=5_000_000)
            hist, bordes = np.histogram(M_cms, bins=240, range=(0, 120))
            centros = ((bordes[:-1] + bordes[1:]) / 2).tolist()
            self._datos_col_masas = centros
            self._datos_col_cms = hist.tolist()
            self._datos_rpi_col_masas = self._datos_col_masas
            self._datos_rpi_col_cms = self._datos_col_cms
        except (OSError, ValueError) as e:
            print(f"[aviso] No pude pre-cargar el histograma del CMS: {e}",
                  file=sys.stderr)

    def _cargar_eventos(self):
        rutas = [os.path.join(self.ruta_windows, "datos_cern.csv"),
                 os.path.join(self.ruta_otros, "datos_cern.csv")]
        ruta = next((r for r in rutas if os.path.exists(r)), None)
        if not ruta:
            return
        try:
            arr = np.loadtxt(ruta, delimiter=',', skiprows=1,
                             usecols=(7, 8, 9, 16, 17, 18, 20),
                             max_rows=100_000)
            self._eventos_cms = arr
            self._n_eventos_cms = len(arr)
        except (OSError, ValueError) as e:
            print(f"[aviso] No pude cargar eventos del CMS: {e}",
                  file=sys.stderr)
            self._eventos_cms = None
            self._n_eventos_cms = 0

    def _histograma_sim(self, m_calc):
        if len(m_calc) == 0:
            return None, None, 150.0
        m_max_data = float(np.max(m_calc))
        xlim = max(150.0, m_max_data * 1.2)
        hist, bordes = np.histogram(m_calc, bins=240, range=(0, xlim))
        centros = ((bordes[:-1] + bordes[1:]) / 2).tolist()
        return centros, hist.tolist(), xlim

    def _cargar_sim_existente(self):
        """Si ya hay un simulacion_eventos.csv en disco lo cargo como el
        resultado de la pestaña Simulación Local."""
        ruta = os.path.join(self.ruta_windows, "simulacion_eventos.csv")
        if not os.path.exists(ruta):
            return
        try:
            arr = np.loadtxt(ruta, delimiter=',', skiprows=1)
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            self._eventos_sim = arr[:, :7]
            self._n_eventos_sim = len(arr)
            centros, conteos, xlim = self._histograma_sim(arr[:, 7])
            self._datos_sim_masas_pc = centros
            self._datos_sim_conteos_pc = conteos
            self._datos_sim_masas = centros
            self._datos_sim_conteos = conteos
            self._sim_xlim_max = xlim
            if self._n_eventos_sim > 0:
                self._sim_masa_actual = float(arr[0, 6])
        except (OSError, ValueError) as e:
            print(f"[aviso] No pude cargar simulacion_eventos.csv previo: {e}",
                  file=sys.stderr)

    def log(self, consola, mensaje):
        consola.config(state="normal")
        consola.insert("end", mensaje + "\n")
        consola.see("end")
        consola.config(state="disabled")

    def _avisar_ocupado(self, consola):
        self.log(consola, "")
        self.log(consola, "  ╔══════════════════════════════════════════╗")
        self.log(consola, "  ║   OCUPADO: ya hay una prueba corriendo   ║")
        self.log(consola, "  ╚══════════════════════════════════════════╝")
        self.log(consola, "")
        if hasattr(self.root, "bell"):
            self.root.bell()

    def _refrescar_label_recursos(self):
        self.lbl_recursos.config(
            text=(f"CPU: {self.hilos_locales} hilos  ·  "
                  f"RPi: {len(self.rpi_hosts)} nodos"))

    def _panel_izq(self, tab, titulo, descripcion,
                    boton_rapido, boton_bench, cmd_rapido, cmd_bench,
                    combo=True, extra=None, etiqueta_combo="Hilos:",
                    aviso_sin_recursos=None, usar_nodos_rpi=False):
        contenedor = ttk.Frame(tab, width=500)
        contenedor.pack(side="left", fill="y", padx=10, pady=10)
        contenedor.pack_propagate(False)

        lienzo = tk.Canvas(contenedor, highlightthickness=0, bg=COLORES["bg"])
        barra = ttk.Scrollbar(contenedor, orient="vertical",
                              command=lienzo.yview)
        panel = ttk.Frame(lienzo)
        lienzo.create_window((0, 0), window=panel, anchor="nw", width=470)
        lienzo.configure(yscrollcommand=barra.set)
        panel.bind("<Configure>",
                   lambda e: lienzo.configure(scrollregion=lienzo.bbox("all")))
        lienzo.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")

        def rueda(event):
            lienzo.yview_scroll(int(-1 * (event.delta / 120)), "units")
        lienzo.bind("<Enter>", lambda e: lienzo.bind_all("<MouseWheel>", rueda))
        lienzo.bind("<Leave>", lambda e: lienzo.unbind_all("<MouseWheel>"))

        ttk.Label(panel, text=titulo,
                  font=("Segoe UI", 15, "bold"),
                  foreground=COLORES["accent"]).pack(pady=(10, 4))
        ttk.Label(panel, text=descripcion, wraplength=440, justify="left",
                  foreground=COLORES["fg_dim"]).pack(pady=5)

        if combo:
            marco = ttk.LabelFrame(panel, text="Prueba individual",
                                   padding=12, style="Card.TLabelframe")
            marco.pack(fill="x", pady=10)
            ttk.Label(marco, text=etiqueta_combo).pack(side="left", padx=5)

            if usar_nodos_rpi:
                valores = list(self.secuencia_nodos_rpi)
            else:
                valores = list(self.secuencia_hilos)

            cb = ttk.Combobox(marco, values=valores, width=5, state="readonly")
            cb.current(0)
            cb.pack(side="left", padx=5)

            if usar_nodos_rpi:
                self.combos_rpi[id(cb)] = cb

            if aviso_sin_recursos:
                def _intentar():
                    if aviso_sin_recursos():
                        return
                    cmd_rapido(cb.get())
                ttk.Button(marco, text=boton_rapido, command=_intentar,
                           style="Accent.TButton").pack(side="left", padx=5)
            else:
                ttk.Button(marco, text=boton_rapido,
                           command=lambda: cmd_rapido(cb.get()),
                           style="Accent.TButton").pack(side="left", padx=5)

        ttk.Button(panel, text=boton_bench, command=cmd_bench,
                   style="Accent.TButton").pack(fill="x", pady=10)

        if extra:
            extra(panel)

        return panel

    def _tabla(self, parent, cols, headers, widths, titulo):
        ttk.Label(parent, text=titulo, font=("Segoe UI", 10, "bold"),
                  foreground=COLORES["accent"]).pack(anchor="w", pady=(8, 0))
        marco = ttk.Frame(parent)
        marco.pack(fill="x", pady=5)

        t = ttk.Treeview(marco, columns=cols, show="headings", height=6)
        for c, h, w in zip(cols, headers, widths):
            t.heading(c, text=h, anchor="center")
            t.column(c, width=w, minwidth=w, anchor="center", stretch=False)

        sb_v = ttk.Scrollbar(marco, orient="vertical", command=t.yview)
        sb_h = ttk.Scrollbar(marco, orient="horizontal", command=t.xview)
        t.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)
        t.grid(row=0, column=0, sticky="nsew")
        sb_v.grid(row=0, column=1, sticky="ns")
        sb_h.grid(row=1, column=0, sticky="ew")
        marco.grid_rowconfigure(0, weight=1)
        marco.grid_columnconfigure(0, weight=1)
        return t

    def _consola(self, parent, altura=10):
        ttk.Label(parent, text="Consola:",
                  foreground=COLORES["accent"],
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(10, 4))
        c = scrolledtext.ScrolledText(parent, state="disabled",
                                       bg=COLORES["console_bg"],
                                       fg=COLORES["console_fg"],
                                       font=("Consolas", 9), height=altura,
                                       insertbackground=COLORES["console_fg"],
                                       borderwidth=0)
        c.pack(fill="x", pady=(0, 10))
        return c

    def _frame_presets(self, parent, var_preset, callback_cambio=None):
        marco = ttk.LabelFrame(parent, text="Pruebas base",
                               padding=10, style="Card.TLabelframe")
        marco.pack(fill="x", pady=5)

        for nombre, mn, mx, masa, sigma in PRESETS_MASA:
            if masa is None:
                etq = f"{nombre}   (espectro completo)"
            else:
                etq = (f"{nombre}   [{mn:.1f}–{mx:.1f} GeV]  "
                       f"m = {masa} GeV,  σ = {sigma} GeV")
            rb = ttk.Radiobutton(marco, text=etq, variable=var_preset,
                                  value=nombre, style="Modern.TRadiobutton")
            rb.pack(anchor="w")
            if callback_cambio:
                rb.config(command=callback_cambio)
        return marco

    # ============================================================
    #  Inicio
    # ============================================================
    def tab_inicio_armar(self):
        lienzo = tk.Canvas(self.tab_inicio, highlightthickness=0,
                            bg=COLORES["bg"])
        barra = ttk.Scrollbar(self.tab_inicio, orient="vertical",
                              command=lienzo.yview)
        cont = ttk.Frame(lienzo)
        lienzo.create_window((0, 0), window=cont, anchor="nw")
        lienzo.configure(yscrollcommand=barra.set)
        cont.bind("<Configure>",
                  lambda e: lienzo.configure(scrollregion=lienzo.bbox("all")))
        lienzo.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")

        self._logos_refs = []

        try:
            logo = os.path.join(self.ruta_otros, "Logo_SIMEX-RACSO.ico")
            if os.path.exists(logo):
                img = Image.open(logo).convert("RGBA")
                img = img.resize((160, 160), Image.LANCZOS)
                foto = ImageTk.PhotoImage(img)
                self._logos_refs.append(foto)
                ttk.Label(cont, image=foto).pack(pady=(20, 5))
        except (FileNotFoundError, OSError) as e:
            print(f"[aviso] No pude cargar el logo: {e}", file=sys.stderr)

        ttk.Label(cont, text="SIMEX-RACSO",
                  font=("Segoe UI", 28, "bold"),
                  foreground=COLORES["accent"]).pack()
        ttk.Label(cont,
                  text="Validación cinemática con datos CMS y simulación Monte Carlo",
                  font=("Segoe UI", 12, "italic"),
                  foreground=COLORES["fg_dim"],
                  wraplength=1000, justify="center").pack(pady=(0, 15))

        ttk.Label(cont, text="Oscar Pablo Morales Zuñiga",
                  font=("Segoe UI", 13, "bold")).pack()
        ttk.Label(cont,
                  text="Facultad de Ciencias Físico Matemáticas (BUAP)  ·  "
                       "Ingeniería en Sistemas Computacionales (UVEG)",
                  font=("Segoe UI", 10), foreground=COLORES["fg_dim"],
                  wraplength=1000, justify="center").pack()
        ttk.Label(cont,
                  text="oscaripingui@gmail.com  ·  +52 744-153-5937",
                  font=("Segoe UI", 10),
                  foreground=COLORES["fg_dim"]).pack(pady=(0, 20))

        ttk.Separator(cont, orient="horizontal").pack(fill="x",
                                                       padx=60, pady=10)

        texto = []

        texto.append(("Qué hace esta aplicación",
            "La app tiene dos frentes. Por un lado lee el dataset público "
            "del CMS Open Data, filtra eventos por rango de masa según la "
            "prueba que yo escoja (J/psi, Upsilon, Z o el espectro "
            "completo), recalcula la masa invariante de cada par de muones "
            "y compara contra la columna M del CSV.\n\n"
            "Por otro lado tengo un kernel de simulación que genera eventos "
            "desde cero, sin leer ningún archivo. Le pido una masa objetivo "
            "y una resolución σ, y construye cada evento de tal manera que "
            "la fórmula de masa invariante se cumpla.\n\n"
            "Las dos rutas tienen su propia pestaña de reconstrucción 3D."))

        texto.append(("Las cuatro pruebas base",
            "En Colisiones (Local y RPi) tengo cuatro pruebas base:\n\n"
            "   J/psi    →  [2.5, 3.7] GeV    m = 3.096 GeV,  σ = 0.05\n"
            "   Upsilon  →  [8.5, 10.5] GeV   m = 9.460 GeV,  σ = 0.15\n"
            "   Z        →  [80, 100] GeV     m = 91.1876 GeV, σ = 2.5\n"
            "   Higgs    →  [115, 135] GeV    m = 125.0 GeV,  σ = 4.0\n\n"
            "En Simulación los mismos presets ajustan la masa y el σ.\n\n"
            "Aviso: el dataset es de 2011 y no tiene estadística de Higgs."))

        texto.append(("Qué es el σ de la simulación",
            "El kernel construye cada evento con una masa muestreada de "
            "una gaussiana centrada en la masa objetivo con desviación σ. "
            "Con σ=0 obtienes una línea vertical (delta). Con σ>0 obtienes "
            "un pico ancho, comparable al del CMS."))

        texto.append(("Cómo usar las gráficas",
            "Cada gráfica tiene abajo la barra de herramientas de "
            "Matplotlib: home, atrás, adelante, pan (mano), zoom, "
            "configurar y guardar. También puedes arrastrar directamente "
            "sobre la gráfica para hacer zoom a una zona."))

        texto.append(("Recursos que se detectan solos",
            f"Esta copia detectó {self.hilos_locales} hilos lógicos en la "
            "CPU. Los combos se arman con esa cuenta. Las Raspberry Pi se "
            "detectan revisando la tabla ARP."))

        texto.append(("Sobre mí",
            "Soy Oscar Pablo Morales Zuñiga. Estudio Física en la FCFM de "
            "la BUAP y también Ingeniería en Sistemas Computacionales en "
            "la UVEG."))

        for titulo_s, cuerpo in texto:
            ttk.Label(cont, text=titulo_s,
                      font=("Segoe UI", 13, "bold"),
                      foreground=COLORES["accent"]).pack(anchor="w",
                                                          padx=70,
                                                          pady=(15, 5))
            ttk.Label(cont, text=cuerpo, wraplength=1080, justify="left",
                      font=("Segoe UI", 10)).pack(anchor="w", padx=90,
                                                  pady=(0, 5))

        ttk.Separator(cont, orient="horizontal").pack(fill="x",
                                                       padx=60, pady=25)

        pie = ttk.Frame(cont)
        pie.pack(pady=(0, 30))
        for nombre, ancho in [("logo_buap.jpeg", 140),
                              ("uveg_logo.jpg", 140),
                              ("SMF-Horizontal.png", 240)]:
            r = os.path.join(self.ruta_otros, nombre)
            if not os.path.exists(r):
                continue
            try:
                img = Image.open(r).convert("RGBA")
                w, h = img.size
                nuevo = int(h * (ancho / w))
                img = img.resize((ancho, nuevo), Image.LANCZOS)
                foto = ImageTk.PhotoImage(img)
                self._logos_refs.append(foto)
                ttk.Label(pie, image=foto).pack(side="left", padx=25)
            except (FileNotFoundError, OSError) as e:
                print(f"[aviso] No pude cargar {nombre}: {e}",
                      file=sys.stderr)

        ttk.Label(cont, text="© 2026 Oscar Pablo Morales Zuñiga  ·  "
                              "Licencia MIT",
                  font=("Segoe UI", 9, "italic"),
                  foreground=COLORES["fg_dim"]).pack(pady=(0, 25))

    # ============================================================
    #  Referencias
    # ============================================================
    def tab_refs_armar(self):
        marco = ttk.Frame(self.tab_refs)
        marco.pack(fill="both", expand=True, padx=20, pady=20)

        ttk.Label(marco, text="Referencias",
                  font=("Segoe UI", 16, "bold"),
                  foreground=COLORES["accent"]).pack(anchor="w", pady=(0, 4))

        caja = scrolledtext.ScrolledText(marco, wrap="word",
                                          font=("Consolas", 10),
                                          bg=COLORES["bg2"],
                                          fg=COLORES["fg"],
                                          borderwidth=0)
        caja.pack(fill="both", expand=True)

        refs = """[1] CMS Collaboration. (2019). Events with two muons from
    2011 (Primary dataset DoubleMu 2011A). CERN Open Data Portal.
    DOI: 10.7483/OPENDATA.CMS.RZ34.QR6N

[2] McCauley, T. (2019). Dimuon spectrum (educational).
    CERN Open Data Portal.

[3] CMS Collaboration. (2011). Primary Datasets - 2011 Data Taking.

[4] CMS Collaboration. (2012). Observation of a new boson at 125 GeV.
    Physics Letters B, 716(1), 30-61. arXiv:1207.7235

[5] CMS Collaboration. (2010). Performance of CMS muon reconstruction.
    JINST, 5, T03022. arXiv:0911.4994

[6] CMS Collaboration. (2008). The CMS experiment at the CERN LHC.
    JINST, 3, S08004.

[7] Einstein, A. (1905). Zur Elektrodynamik bewegter Körper.

[8] Minkowski, H. (1908). Raum und Zeit.

[9] Landau, L. D., & Lifshitz, E. M. (1975). The Classical Theory of
    Fields. Pergamon Press.

[10] Particle Data Group (Beringer, J. et al.). (2012). Review of
     Particle Physics. Physical Review D, 86, 010001.

[11] Ellis, R. K., Stirling, W. J., & Webber, B. R. (1996). QCD and
     Collider Physics. Cambridge University Press.

[12] Amdahl, G. M. (1967). Validity of the single processor approach.

[13] Gustafson, J. L. (1988). Reevaluating Amdahl's Law.

[14] Message Passing Interface Forum. (2021). MPI 4.0.

[15] Gropp, W., Lusk, E., & Skjellum, A. (2014). Using MPI (3rd ed.).

[16] Metropolis, N., & Ulam, S. (1949). The Monte Carlo Method.

[17] Matsumoto, M., & Nishimura, T. (1998). Mersenne Twister.

[18] Cox, S. J. et al. (2013). Iridis-pi: a low-cost, compact
     demonstration cluster.

[19] Tso, F. P. et al. (2013). The Glasgow Raspberry Pi Cloud.

[20] Raspberry Pi Foundation. (2023). Raspberry Pi 5 Product Brief.

[21] Hunter, J. D. (2007). Matplotlib.

[22] Harris, C. R. et al. (2020). Array programming with NumPy.

[23] Ylonen, T., & Lonvick, C. (2006). The Secure Shell (SSH) Protocol.

[24] WSL Documentation. (2024). Windows Subsystem for Linux.
"""
        caja.insert("1.0", refs)
        caja.config(state="disabled")

    # ============================================================
    #  Hilos Local
    # ============================================================
    def tab_mc_pc_armar(self):
        def bench():
            self.benchmark_local("mc_core", self.cons_mc_pc,
                                 self.panel_mc_pc)

        panel = self._panel_izq(
            self.tab_mc_pc,
            "Benchmark Monte Carlo Local",
            f"Mide el overhead puro de MPI con carga estocástica.\n"
            f"Este equipo tiene {self.hilos_locales} hilos lógicos.",
            "Ejecutar",
            "Iniciar benchmark (10 iteraciones)",
            lambda h: self.ejecutar_local("mc_core", h, self.cons_mc_pc),
            bench
        )
        self.cons_mc_pc = self._consola(panel)

        der = ttk.Frame(self.tab_mc_pc)
        der.pack(side="right", fill="both", expand=True, padx=10, pady=10)
        self.panel_mc_pc = PanelGraficas(
            der,
            [("Todas", "todas"), ("Tiempo", "tiempo"), ("Amdahl", "amdahl")],
            self._dibujar_mc_pc,
            figsize=(7, 7)
        )
        self._dibujar_mc_pc("todas")

    def _dibujar_mc_pc(self, modo):
        fig = self.panel_mc_pc.fig
        fig.clear()
        self.ax_mc_pc_time = None
        self.ax_mc_pc_amd = None

        if modo == "todas":
            gs = fig.add_gridspec(2, 1, hspace=0.45, top=0.94, bottom=0.08,
                                  left=0.14, right=0.96)
            self.ax_mc_pc_time = fig.add_subplot(gs[0])
            self.ax_mc_pc_amd = fig.add_subplot(gs[1])
        elif modo == "tiempo":
            self.ax_mc_pc_time = fig.add_subplot(
                111, position=[0.14, 0.10, 0.82, 0.82])
        else:
            self.ax_mc_pc_amd = fig.add_subplot(
                111, position=[0.14, 0.10, 0.82, 0.82])

        self._plot_tiempos_amdahl(
            self.ax_mc_pc_time, self.ax_mc_pc_amd,
            self.hilos_mc, self.tiempos_mc, "#2e7d32",
            "Monte Carlo local")

        for ax in (self.ax_mc_pc_time, self.ax_mc_pc_amd):
            if ax:
                PanelGraficas.aplicar_estilo(ax)
        self.panel_mc_pc.canvas.draw()

    # ============================================================
    #  Colisiones Local
    # ============================================================
    def tab_col_pc_armar(self):
        def bench():
            self.benchmark_col_local()

        def extra(parent):
            self._frame_presets(parent, self.preset_col_pc,
                                 callback_cambio=self._refrescar_col_pc)

        panel = self._panel_izq(
            self.tab_col_pc,
            "Validación cinemática (local)",
            "Filtra el CSV del CMS por rango de masa y recalcula la masa "
            "invariante de cada evento. Comparo con la columna M del CMS.",
            "Ejecutar",
            "Iniciar benchmark (10 iteraciones)",
            lambda h: self.correr_col_local(h),
            bench, extra=extra
        )

        self.tabla_col_pc = self._tabla(
            panel,
            ("hilos", "tiempo", "eventos", "dif_media", "dif_sigma",
             "speedup"),
            ["Hilos", "Tiempo (s)", "Eventos", "Delta media (GeV)",
             "Delta sigma (GeV)", "Speedup"],
            [55, 90, 95, 95, 90, 75],
            "Resultados por número de hilos:"
        )
        self.lbl_ts_col_pc = ttk.Label(panel, text="Última ejecución: -",
                                        font=("Consolas", 9),
                                        foreground=COLORES["fg_dim"])
        self.lbl_ts_col_pc.pack(anchor="w", pady=(5, 0))
        self.cons_col_pc = self._consola(panel, altura=10)

        der = ttk.Frame(self.tab_col_pc)
        der.pack(side="right", fill="both", expand=True, padx=10, pady=10)
        self.panel_col_pc = PanelGraficas(
            der,
            [("Espectro", "espectro"),
             ("Tiempos", "tiempos"),
             ("MC vs CMS", "comparacion")],
            self._dibujar_col_pc,
            figsize=(9, 8)
        )
        self._dibujar_col_pc("comparacion")

    def _refrescar_col_pc(self):
        mn, mx, _, _ = rango_de_preset(self.preset_col_pc.get())
        self._col_rango_min = mn
        self._col_rango_max = mx
        self.panel_col_pc.redibujar()

    def _dibujar_col_pc(self, modo):
        fig = self.panel_col_pc.fig
        fig.clear()
        self.ax_col_pc_esp = None
        self.ax_col_pc_t = None
        self.ax_col_pc_cmp_cms = None
        self.ax_col_pc_cmp_recalc = None

        if modo == "espectro":
            self.ax_col_pc_esp = fig.add_subplot(
                111, position=[0.12, 0.10, 0.84, 0.82])
        elif modo == "tiempos":
            self.ax_col_pc_t = fig.add_subplot(
                111, position=[0.14, 0.12, 0.82, 0.80])
        else:
            gs = fig.add_gridspec(2, 1, hspace=0.55, top=0.94, bottom=0.08,
                                  left=0.12, right=0.96)
            self.ax_col_pc_cmp_cms = fig.add_subplot(gs[0])
            self.ax_col_pc_cmp_recalc = fig.add_subplot(gs[1])

        if self.ax_col_pc_esp:
            if (self._datos_col_masas is not None
                    and self._datos_col_conteos is not None):
                self._plot_espectro(self.ax_col_pc_esp,
                                    self._datos_col_masas,
                                    self._datos_col_conteos,
                                    self._datos_col_cms,
                                    preset=self.preset_col_pc.get())
            else:
                self._plot_espectro_vacio(self.ax_col_pc_esp)

        if self.ax_col_pc_t:
            if self._datos_col_tiempos:
                self._plot_tiempos(self.ax_col_pc_t, self.secuencia_hilos,
                                    self._datos_col_tiempos)
            else:
                self._plot_tiempos_vacio(self.ax_col_pc_t)

        if self.ax_col_pc_cmp_cms and self.ax_col_pc_cmp_recalc:
            self._plot_comparacion(self.ax_col_pc_cmp_cms,
                                    self.ax_col_pc_cmp_recalc,
                                    self._datos_col_masas,
                                    self._datos_col_conteos,
                                    self._datos_col_cms,
                                    preset=self.preset_col_pc.get())

        for ax in (self.ax_col_pc_esp, self.ax_col_pc_t,
                   self.ax_col_pc_cmp_cms, self.ax_col_pc_cmp_recalc):
            if ax:
                PanelGraficas.aplicar_estilo(ax)
        self.panel_col_pc.canvas.draw()

    # ============================================================
    #  Hilos RPi
    # ============================================================
    def tab_mc_rpi_armar(self):
        def bench():
            self.benchmark_rpi("mc_core", self.cons_mc_rpi,
                               self.panel_mc_rpi)

        def extra(parent):
            ttk.Button(parent, text="Escanear red",
                       command=self.escanear_red,
                       style="Accent.TButton").pack(fill="x", pady=5)
            self.lbl_pis_mc = ttk.Label(parent,
                                        text="Raspberry Pi detectadas: 0",
                                        foreground=COLORES["fg_dim"])
            self.lbl_pis_mc.pack(anchor="w")

            cfg = ttk.LabelFrame(parent, text="Conexión SSH",
                                 padding=10, style="Card.TLabelframe")
            cfg.pack(fill="x", pady=5)
            ttk.Label(cfg, text="Usuario:").pack(side="left", padx=3)
            ttk.Entry(cfg, textvariable=self.rpi_user,
                      width=10).pack(side="left", padx=3)
            ttk.Label(cfg, text="Ruta:").pack(side="left", padx=3)
            ttk.Entry(cfg, textvariable=self.rpi_path,
                      width=15).pack(side="left", padx=3)

        panel = self._panel_izq(
            self.tab_mc_rpi,
            "Benchmark Monte Carlo en clúster",
            "Corre el Monte Carlo distribuido entre las Raspberry Pi.",
            "Ejecutar",
            "Iniciar benchmark (10 iteraciones)",
            lambda n: self.ejecutar_rpi("mc_core", n, self.cons_mc_rpi),
            bench, extra=extra, etiqueta_combo="Nodos:",
            aviso_sin_recursos=self._avisar_sin_rpi,
            usar_nodos_rpi=True
        )
        self.cons_mc_rpi = self._consola(panel)

        der = ttk.Frame(self.tab_mc_rpi)
        der.pack(side="right", fill="both", expand=True, padx=10, pady=10)
        self.panel_mc_rpi = PanelGraficas(
            der,
            [("Todas", "todas"), ("Tiempo", "tiempo"), ("Amdahl", "amdahl")],
            self._dibujar_mc_rpi,
            figsize=(7, 7)
        )
        self._dibujar_mc_rpi("todas")

    def _avisar_sin_rpi(self):
        if not self.rpi_hosts:
            messagebox.showwarning("Sin Raspberry Pi",
                "No hay nodos detectados en la red.\n\n"
                "Primero pulsa 'Escanear red'. Si aun así no aparecen, "
                "revisa la conexión o la configuración de la tabla ARP.")
            return True
        return False

    def _dibujar_mc_rpi(self, modo):
        fig = self.panel_mc_rpi.fig
        fig.clear()
        self.ax_mc_rpi_time = None
        self.ax_mc_rpi_amd = None

        if modo == "todas":
            gs = fig.add_gridspec(2, 1, hspace=0.45, top=0.94, bottom=0.08,
                                  left=0.14, right=0.96)
            self.ax_mc_rpi_time = fig.add_subplot(gs[0])
            self.ax_mc_rpi_amd = fig.add_subplot(gs[1])
        elif modo == "tiempo":
            self.ax_mc_rpi_time = fig.add_subplot(
                111, position=[0.14, 0.10, 0.82, 0.82])
        else:
            self.ax_mc_rpi_amd = fig.add_subplot(
                111, position=[0.14, 0.10, 0.82, 0.82])

        self._plot_tiempos_amdahl(
            self.ax_mc_rpi_time, self.ax_mc_rpi_amd,
            self.hilos_rpi_mc, self.tiempos_rpi_mc, "#6a1b9a",
            "Monte Carlo en Raspberry Pi")

        for ax in (self.ax_mc_rpi_time, self.ax_mc_rpi_amd):
            if ax:
                PanelGraficas.aplicar_estilo(ax)
        self.panel_mc_rpi.canvas.draw()

    # ============================================================
    #  Colisiones RPi
    # ============================================================
    def tab_col_rpi_armar(self):
        def bench():
            self.benchmark_col_rpi()

        def extra(parent):
            ttk.Button(parent, text="Escanear red",
                       command=self.escanear_red,
                       style="Accent.TButton").pack(fill="x", pady=5)
            self.lbl_pis_col = ttk.Label(parent,
                                         text="Raspberry Pi detectadas: 0",
                                         foreground=COLORES["fg_dim"])
            self.lbl_pis_col.pack(anchor="w")

            cfg = ttk.LabelFrame(parent, text="Conexión SSH",
                                 padding=10, style="Card.TLabelframe")
            cfg.pack(fill="x", pady=5)
            ttk.Label(cfg, text="Usuario:").pack(side="left", padx=3)
            ttk.Entry(cfg, textvariable=self.rpi_user,
                      width=10).pack(side="left", padx=3)
            ttk.Label(cfg, text="Ruta:").pack(side="left", padx=3)
            ttk.Entry(cfg, textvariable=self.rpi_path,
                      width=15).pack(side="left", padx=3)

            self._frame_presets(parent, self.preset_col_rpi,
                                 callback_cambio=self._refrescar_col_rpi)

        panel = self._panel_izq(
            self.tab_col_rpi,
            "Validación cinemática en clúster",
            "Reparte el recálculo de masa invariante entre las Raspberry Pi.",
            "Ejecutar",
            "Iniciar benchmark (10 iteraciones)",
            lambda n: self.correr_col_rpi(n),
            bench, extra=extra, etiqueta_combo="Nodos:",
            aviso_sin_recursos=self._avisar_sin_rpi,
            usar_nodos_rpi=True
        )

        self.tabla_col_rpi = self._tabla(
            panel,
            ("nodos", "tiempo", "eventos", "dif_media", "dif_sigma",
             "speedup"),
            ["Nodos", "Tiempo (s)", "Eventos", "Delta media (GeV)",
             "Delta sigma (GeV)", "Speedup"],
            [55, 90, 95, 95, 90, 75],
            "Resultados por número de nodos:"
        )
        self.lbl_ts_col_rpi = ttk.Label(panel, text="Última ejecución: -",
                                         font=("Consolas", 9),
                                         foreground=COLORES["fg_dim"])
        self.lbl_ts_col_rpi.pack(anchor="w", pady=(5, 0))
        self.cons_col_rpi = self._consola(panel, altura=10)

        der = ttk.Frame(self.tab_col_rpi)
        der.pack(side="right", fill="both", expand=True, padx=10, pady=10)
        self.panel_col_rpi = PanelGraficas(
            der,
            [("Espectro", "espectro"),
             ("Tiempos", "tiempos"),
             ("MC vs CMS", "comparacion")],
            self._dibujar_col_rpi,
            figsize=(9, 8)
        )
        self._dibujar_col_rpi("comparacion")

    def _refrescar_col_rpi(self):
        mn, mx, _, _ = rango_de_preset(self.preset_col_rpi.get())
        self._col_rango_min_rpi = mn
        self._col_rango_max_rpi = mx
        self.panel_col_rpi.redibujar()

    def _dibujar_col_rpi(self, modo):
        fig = self.panel_col_rpi.fig
        fig.clear()
        self.ax_col_rpi_esp = None
        self.ax_col_rpi_t = None
        self.ax_col_rpi_cmp_cms = None
        self.ax_col_rpi_cmp_recalc = None

        if modo == "espectro":
            self.ax_col_rpi_esp = fig.add_subplot(
                111, position=[0.12, 0.10, 0.84, 0.82])
        elif modo == "tiempos":
            self.ax_col_rpi_t = fig.add_subplot(
                111, position=[0.14, 0.12, 0.82, 0.80])
        else:
            gs = fig.add_gridspec(2, 1, hspace=0.55, top=0.94, bottom=0.08,
                                  left=0.12, right=0.96)
            self.ax_col_rpi_cmp_cms = fig.add_subplot(gs[0])
            self.ax_col_rpi_cmp_recalc = fig.add_subplot(gs[1])

        if self.ax_col_rpi_esp:
            if (self._datos_rpi_col_masas is not None
                    and self._datos_rpi_col_conteos is not None):
                self._plot_espectro(self.ax_col_rpi_esp,
                                    self._datos_rpi_col_masas,
                                    self._datos_rpi_col_conteos,
                                    self._datos_rpi_col_cms,
                                    preset=self.preset_col_rpi.get())
            else:
                self._plot_espectro_vacio(self.ax_col_rpi_esp)

        if self.ax_col_rpi_t:
            if self._datos_rpi_col_tiempos:
                self._plot_tiempos(self.ax_col_rpi_t, self.hilos_rpi_col,
                                    self._datos_rpi_col_tiempos)
            else:
                self._plot_tiempos_vacio(self.ax_col_rpi_t, "Nodos (p)")

        if self.ax_col_rpi_cmp_cms and self.ax_col_rpi_cmp_recalc:
            self._plot_comparacion(self.ax_col_rpi_cmp_cms,
                                    self.ax_col_rpi_cmp_recalc,
                                    self._datos_rpi_col_masas,
                                    self._datos_rpi_col_conteos,
                                    self._datos_rpi_col_cms,
                                    preset=self.preset_col_rpi.get())

        for ax in (self.ax_col_rpi_esp, self.ax_col_rpi_t,
                   self.ax_col_rpi_cmp_cms, self.ax_col_rpi_cmp_recalc):
            if ax:
                PanelGraficas.aplicar_estilo(ax)
        self.panel_col_rpi.canvas.draw()

    # ============================================================
    #  Simulación Local
    # ============================================================
    def tab_sim_pc_armar(self):
        def bench():
            self.benchmark_sim_local()

        def extra(parent):
            self._frame_presets(parent, self.preset_sim_pc,
                                 callback_cambio=self._aplicar_preset_sim_pc)

            cfg = ttk.LabelFrame(parent, text="Parámetros (editables)",
                                  padding=10, style="Card.TLabelframe")
            cfg.pack(fill="x", pady=5)

            fila = ttk.Frame(cfg); fila.pack(fill="x", pady=2)
            ttk.Label(fila, text="Masa objetivo (GeV):").pack(side="left")
            ttk.Entry(fila, textvariable=self.sim_masa,
                      width=12).pack(side="left", padx=5)

            fila = ttk.Frame(cfg); fila.pack(fill="x", pady=2)
            ttk.Label(fila, text="Resolución σ (GeV):").pack(side="left")
            ttk.Entry(fila, textvariable=self.sim_sigma,
                      width=8).pack(side="left", padx=5)
            ttk.Label(fila, text="(0 = línea vertical)",
                      font=("Segoe UI", 8, "italic"),
                      foreground=COLORES["fg_dim"]).pack(side="left")

            fila = ttk.Frame(cfg); fila.pack(fill="x", pady=2)
            ttk.Label(fila, text="Número de eventos:").pack(side="left")
            ttk.Entry(fila, textvariable=self.sim_eventos,
                      width=12).pack(side="left", padx=5)

            fila = ttk.Frame(cfg); fila.pack(fill="x", pady=2)
            ttk.Label(fila, text="pT mín (GeV):").pack(side="left")
            ttk.Entry(fila, textvariable=self.sim_pt_min,
                      width=8).pack(side="left", padx=5)
            ttk.Label(fila, text="pT máx (GeV):").pack(side="left")
            ttk.Entry(fila, textvariable=self.sim_pt_max,
                      width=8).pack(side="left", padx=5)

            fila = ttk.Frame(cfg); fila.pack(fill="x", pady=2)
            ttk.Label(fila, text="eta mín:").pack(side="left")
            ttk.Entry(fila, textvariable=self.sim_eta_min,
                      width=8).pack(side="left", padx=5)
            ttk.Label(fila, text="eta máx:").pack(side="left")
            ttk.Entry(fila, textvariable=self.sim_eta_max,
                      width=8).pack(side="left", padx=5)

            ttk.Label(parent,
                      text=("El kernel NO lee ningún CSV. Genera eventos "
                            "desde cero despejando cos(Δφ) de la fórmula\n"
                            "m² = 2·pT₁·pT₂·[cosh(Δη) − cos(Δφ)].\n\n"
                            "Con σ > 0 cada evento muestrea su masa de una\n"
                            "gaussiana centrada en la masa objetivo."),
                      font=("Segoe UI", 9, "italic"),
                      foreground=COLORES["fg_dim"],
                      wraplength=440, justify="left").pack(pady=5)

        panel = self._panel_izq(
            self.tab_sim_pc,
            "Simulación Monte Carlo Local",
            "Genera eventos con masa invariante fija usando MPI en esta PC.",
            "Ejecutar",
            "Iniciar benchmark (5 iteraciones)",
            lambda h: self.ejecutar_sim_local(h),
            bench, extra=extra
        )

        self.tabla_sim_pc = self._tabla(
            panel,
            ("hilos", "tiempo", "eventos", "speedup"),
            ["Hilos", "Tiempo (s)", "Eventos", "Speedup"],
            [60, 95, 110, 80],
            "Resultados por número de hilos:"
        )

        self.cons_sim_pc = self._consola(panel, altura=8)

        der = ttk.Frame(self.tab_sim_pc)
        der.pack(side="right", fill="both", expand=True, padx=10, pady=10)
        self.panel_sim_pc = PanelGraficas(
            der,
            [("Espectro", "espectro"),
             ("Tiempos", "tiempos")],
            self._dibujar_sim_pc,
            figsize=(8, 7)
        )
        self._dibujar_sim_pc("espectro")

    def _aplicar_preset_sim_pc(self):
        _, _, masa, sigma = rango_de_preset(self.preset_sim_pc.get())
        if masa is not None:
            self.sim_masa.set(f"{masa}")
            self.sim_sigma.set(f"{sigma}")

    def _dibujar_sim_pc(self, modo):
        """Usa solo los datos de la pestaña Simulación Local."""
        fig = self.panel_sim_pc.fig
        fig.clear()

        if modo == "espectro":
            ax = fig.add_subplot(111, position=[0.12, 0.10, 0.84, 0.82])
            hay_sim = (self._datos_sim_masas_pc is not None
                       and self._datos_sim_conteos_pc is not None)

            if (self._datos_col_masas is not None
                    and self._datos_col_cms is not None):
                ax.plot(self._datos_col_masas, self._datos_col_cms,
                        color="#111111", ls=":", lw=1.3, alpha=0.9,
                        label="CMS (columna M)", zorder=3)

            if hay_sim:
                ax.plot(self._datos_sim_masas_pc, self._datos_sim_conteos_pc,
                        color="#d32f2f", lw=2.4, alpha=1.0,
                        label="Simulación local", zorder=5)

            _, _, masa_preset, _ = rango_de_preset(self.preset_sim_pc.get())
            if masa_preset is not None:
                ax.axvline(masa_preset, color="#555555", ls=":",
                            lw=1.4, alpha=0.8, zorder=4,
                            label=f"m teórica = {masa_preset} GeV")

            ax.set_yscale('log')
            ax.set_title("Espectro de masa - simulación local",
                          fontsize=11, pad=12)
            ax.set_xlabel("m(mu mu) [GeV]")
            ax.set_ylabel("Eventos por bin (log)")
            ax.legend(loc="upper right", fontsize=8)
            PanelGraficas.aplicar_estilo(ax)

        elif modo == "tiempos":
            ax = fig.add_subplot(111, position=[0.14, 0.12, 0.82, 0.80])
            if self.hilos_sim and self.tiempos_sim:
                ax.plot(self.hilos_sim, self.tiempos_sim, marker='o',
                        color="#2e7d32", lw=2)
                ax.set_xticks(self.hilos_sim)
            ax.set_title("Tiempo de simulación vs hilos", fontsize=11)
            ax.set_xlabel("Hilos (p)")
            ax.set_ylabel("Tiempo (s)")
            PanelGraficas.aplicar_estilo(ax)

        self.panel_sim_pc.canvas.draw()

    # ============================================================
    #  Simulación RPi
    # ============================================================
    def tab_sim_rpi_armar(self):
        def bench():
            self.benchmark_sim_rpi()

        def extra(parent):
            ttk.Button(parent, text="Escanear red",
                       command=self.escanear_red,
                       style="Accent.TButton").pack(fill="x", pady=5)
            self.lbl_pis_sim = ttk.Label(parent,
                                         text="Raspberry Pi detectadas: 0",
                                         foreground=COLORES["fg_dim"])
            self.lbl_pis_sim.pack(anchor="w")

            cfg = ttk.LabelFrame(parent, text="Conexión SSH",
                                  padding=10, style="Card.TLabelframe")
            cfg.pack(fill="x", pady=5)
            ttk.Label(cfg, text="Usuario:").pack(side="left", padx=3)
            ttk.Entry(cfg, textvariable=self.rpi_user,
                      width=10).pack(side="left", padx=3)
            ttk.Label(cfg, text="Ruta:").pack(side="left", padx=3)
            ttk.Entry(cfg, textvariable=self.rpi_path,
                      width=15).pack(side="left", padx=3)

            self._frame_presets(parent, self.preset_sim_rpi,
                                 callback_cambio=self._aplicar_preset_sim_rpi)

            cfg2 = ttk.LabelFrame(parent, text="Parámetros (editables)",
                                   padding=10, style="Card.TLabelframe")
            cfg2.pack(fill="x", pady=5)

            fila = ttk.Frame(cfg2); fila.pack(fill="x", pady=2)
            ttk.Label(fila, text="Masa objetivo (GeV):").pack(side="left")
            ttk.Entry(fila, textvariable=self.sim_masa,
                      width=12).pack(side="left", padx=5)

            fila = ttk.Frame(cfg2); fila.pack(fill="x", pady=2)
            ttk.Label(fila, text="Resolución σ (GeV):").pack(side="left")
            ttk.Entry(fila, textvariable=self.sim_sigma,
                      width=8).pack(side="left", padx=5)
            ttk.Label(fila, text="(0 = línea vertical)",
                      font=("Segoe UI", 8, "italic"),
                      foreground=COLORES["fg_dim"]).pack(side="left")

            fila = ttk.Frame(cfg2); fila.pack(fill="x", pady=2)
            ttk.Label(fila, text="Número de eventos:").pack(side="left")
            ttk.Entry(fila, textvariable=self.sim_eventos,
                      width=12).pack(side="left", padx=5)

            fila = ttk.Frame(cfg2); fila.pack(fill="x", pady=2)
            ttk.Label(fila, text="pT mín (GeV):").pack(side="left")
            ttk.Entry(fila, textvariable=self.sim_pt_min,
                      width=8).pack(side="left", padx=5)
            ttk.Label(fila, text="pT máx (GeV):").pack(side="left")
            ttk.Entry(fila, textvariable=self.sim_pt_max,
                      width=8).pack(side="left", padx=5)

            fila = ttk.Frame(cfg2); fila.pack(fill="x", pady=2)
            ttk.Label(fila, text="eta mín:").pack(side="left")
            ttk.Entry(fila, textvariable=self.sim_eta_min,
                      width=8).pack(side="left", padx=5)
            ttk.Label(fila, text="eta máx:").pack(side="left")
            ttk.Entry(fila, textvariable=self.sim_eta_max,
                      width=8).pack(side="left", padx=5)

        panel = self._panel_izq(
            self.tab_sim_rpi,
            "Simulación Monte Carlo en clúster",
            "Reparte la generación de eventos entre las Raspberry Pi.",
            "Ejecutar",
            "Iniciar benchmark (5 iteraciones)",
            lambda n: self.ejecutar_sim_rpi(n),
            bench, extra=extra, etiqueta_combo="Nodos:",
            aviso_sin_recursos=self._avisar_sin_rpi,
            usar_nodos_rpi=True
        )

        self.tabla_sim_rpi = self._tabla(
            panel,
            ("nodos", "tiempo", "eventos", "speedup"),
            ["Nodos", "Tiempo (s)", "Eventos", "Speedup"],
            [60, 95, 110, 80],
            "Resultados por número de nodos:"
        )

        self.cons_sim_rpi = self._consola(panel, altura=8)

        der = ttk.Frame(self.tab_sim_rpi)
        der.pack(side="right", fill="both", expand=True, padx=10, pady=10)
        self.panel_sim_rpi = PanelGraficas(
            der,
            [("Espectro", "espectro"),
             ("Tiempos", "tiempos")],
            self._dibujar_sim_rpi,
            figsize=(8, 7)
        )
        self._dibujar_sim_rpi("espectro")

    def _aplicar_preset_sim_rpi(self):
        _, _, masa, sigma = rango_de_preset(self.preset_sim_rpi.get())
        if masa is not None:
            self.sim_masa.set(f"{masa}")
            self.sim_sigma.set(f"{sigma}")

    def _dibujar_sim_rpi(self, modo):
        """Usa solo los datos de la pestaña Simulación RPi."""
        fig = self.panel_sim_rpi.fig
        fig.clear()

        if modo == "espectro":
            ax = fig.add_subplot(111, position=[0.12, 0.10, 0.84, 0.82])
            hay_sim = (self._datos_sim_masas_rpi is not None
                       and self._datos_sim_conteos_rpi is not None)

            if (self._datos_col_masas is not None
                    and self._datos_col_cms is not None):
                ax.plot(self._datos_col_masas, self._datos_col_cms,
                        color="#111111", ls=":", lw=1.3, alpha=0.9,
                        label="CMS (columna M)", zorder=3)

            if hay_sim:
                ax.plot(self._datos_sim_masas_rpi, self._datos_sim_conteos_rpi,
                        color="#d32f2f", lw=2.4, alpha=1.0,
                        label="Simulación RPi", zorder=5)

            _, _, masa_preset, _ = rango_de_preset(self.preset_sim_rpi.get())
            if masa_preset is not None:
                ax.axvline(masa_preset, color="#555555", ls=":",
                            lw=1.4, alpha=0.8, zorder=4,
                            label=f"m teórica = {masa_preset} GeV")

            ax.set_yscale('log')
            ax.set_title("Espectro de masa - simulación RPi",
                          fontsize=11, pad=12)
            ax.set_xlabel("m(mu mu) [GeV]")
            ax.set_ylabel("Eventos por bin (log)")
            ax.legend(loc="upper right", fontsize=8)
            PanelGraficas.aplicar_estilo(ax)

        elif modo == "tiempos":
            ax = fig.add_subplot(111, position=[0.14, 0.12, 0.82, 0.80])
            if self.hilos_rpi_sim and self.tiempos_rpi_sim:
                ax.plot(self.hilos_rpi_sim, self.tiempos_rpi_sim, marker='o',
                        color="#6a1b9a", lw=2)
                ax.set_xticks(self.hilos_rpi_sim)
            ax.set_title("Tiempo de simulación vs nodos", fontsize=11)
            ax.set_xlabel("Nodos (p)")
            ax.set_ylabel("Tiempo (s)")
            PanelGraficas.aplicar_estilo(ax)

        self.panel_sim_rpi.canvas.draw()

    # ============================================================
    #  Reconstrucción CMS
    # ============================================================
    def tab_recon_armar(self):
        izq = ttk.Frame(self.tab_recon_cms, width=500)
        izq.pack(side="left", fill="y", padx=10, pady=10)
        izq.pack_propagate(False)

        lienzo = tk.Canvas(izq, highlightthickness=0, bg=COLORES["bg"],
                            width=470)
        barra = ttk.Scrollbar(izq, orient="vertical", command=lienzo.yview)
        cont = ttk.Frame(lienzo)
        lienzo.create_window((0, 0), window=cont, anchor="nw", width=460)
        lienzo.configure(yscrollcommand=barra.set)
        cont.bind("<Configure>",
                  lambda e: lienzo.configure(scrollregion=lienzo.bbox("all")))
        lienzo.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")

        def rueda(event):
            lienzo.yview_scroll(int(-1 * (event.delta / 120)), "units")
        lienzo.bind("<Enter>", lambda e: lienzo.bind_all("<MouseWheel>", rueda))
        lienzo.bind("<Leave>", lambda e: lienzo.unbind_all("<MouseWheel>"))

        ttk.Label(cont, text="Video de la colisión (CMS)",
                  font=("Segoe UI", 15, "bold"),
                  foreground=COLORES["accent"]).pack(pady=(8, 4))
        ttk.Label(cont,
                  text="Cada evento se convierte en una animación de cinco "
                       "segundos. Los muones viajan hacia el vértice, "
                       "colisionan y aparece la resonancia.",
                  wraplength=450, justify="left",
                  foreground=COLORES["fg_dim"]).pack(pady=5)

        pre = ttk.LabelFrame(cont, text="Precomputación de eventos (usa MPI)",
                             padding=10, style="Card.TLabelframe")
        pre.pack(fill="x", pady=8)

        ttk.Label(pre, text=("Aquí sí se usan hilos o nodos: anim_core "
                             "reparte el procesamiento del CSV entre "
                             "procesos."),
                  font=("Segoe UI", 8, "italic"),
                  foreground=COLORES["fg_dim"],
                  wraplength=430, justify="left").pack(anchor="w", pady=(0, 4))

        ttk.Radiobutton(pre,
                        text=f"En esta PC ({self.hilos_locales} hilos)",
                        variable=self.modo_anim, value="pc",
                        command=self._actualizar_hilos_anim,
                        style="Modern.TRadiobutton").pack(anchor="w")
        self.radio_rpi_recon = ttk.Radiobutton(
            pre,
            text="En el clúster de Raspberry Pi (0 nodos)",
            variable=self.modo_anim, value="rpi",
            command=self._actualizar_hilos_anim,
            style="Modern.TRadiobutton")
        self.radio_rpi_recon.pack(anchor="w")

        fila = ttk.Frame(pre)
        fila.pack(fill="x", pady=6)
        ttk.Label(fila, text="Hilos o nodos:").pack(side="left")
        self.combo_hilos_anim = ttk.Combobox(fila,
                                              values=self.secuencia_hilos,
                                              width=6, state="readonly")
        self.combo_hilos_anim.current(0)
        self.combo_hilos_anim.pack(side="left", padx=6)

        ttk.Button(pre, text="Precomputar eventos",
                   command=self._precomputar_animacion,
                   style="Accent.TButton").pack(fill="x", pady=(6, 0))

        sel = ttk.LabelFrame(cont, text="Evento a animar",
                             padding=10, style="Card.TLabelframe")
        sel.pack(fill="x", pady=8)

        fila = ttk.Frame(sel)
        fila.pack(fill="x", pady=4)
        ttk.Label(fila, text="Número:").pack(side="left")
        self.entry_evento = ttk.Entry(fila, width=10)
        self.entry_evento.pack(side="left", padx=5)
        ttk.Button(fila, text="Ir",
                   command=self._ir_a_evento).pack(side="left", padx=2)
        ttk.Button(fila, text="Aleatorio",
                   command=self._evento_aleatorio).pack(side="left", padx=2)

        self.slider_evento = ttk.Scale(sel, from_=0,
                                        to=max(1, self._n_eventos_cms - 1),
                                        orient="horizontal",
                                        command=self._slider_callback)
        self.slider_evento.pack(fill="x", pady=(6, 2))
        self.lbl_slider = ttk.Label(sel,
                                     text=f"0 / {max(0, self._n_eventos_cms - 1)}",
                                     font=("Consolas", 10),
                                     foreground=COLORES["fg_dim"])
        self.lbl_slider.pack(anchor="center")

        info = ttk.LabelFrame(cont, text="Datos del evento",
                              padding=10, style="Card.TLabelframe")
        info.pack(fill="x", pady=8)

        self.lbl_evento_masa = ttk.Label(info, text="m(mu mu) = - GeV",
                                          font=("Consolas", 12, "bold"),
                                          foreground=COLORES["accent"])
        self.lbl_evento_masa.pack(anchor="w", pady=(0, 8))

        self.lbl_evento_muon1 = ttk.Label(
            info, text="Muón 1: pT=-, eta=-, phi=-",
            font=("Consolas", 9), foreground="#c62828")
        self.lbl_evento_muon1.pack(anchor="w")
        self.lbl_evento_muon2 = ttk.Label(
            info, text="Muón 2: pT=-, eta=-, phi=-",
            font=("Consolas", 9), foreground="#1565c0")
        self.lbl_evento_muon2.pack(anchor="w")

        ctrl = ttk.LabelFrame(cont, text="Reproducción",
                              padding=10, style="Card.TLabelframe")
        ctrl.pack(fill="x", pady=8)

        ttk.Button(ctrl, text="Generar video (medir tiempo)",
                   command=self._generar_video,
                   style="Accent.TButton").pack(fill="x", pady=3)

        self.btn_play = ttk.Button(ctrl,
                                    text="Reproducir colisión (5 s)",
                                    command=self._toggle_animacion,
                                    style="Play.TButton")
        self.btn_play.pack(fill="x", pady=3)

        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(ctrl, variable=self.progress_var,
                        maximum=100.0).pack(fill="x", pady=(6, 2))

        self.lbl_estado_anim = ttk.Label(ctrl, text="Listo",
                                          font=("Consolas", 9),
                                          foreground=COLORES["fg_dim"],
                                          wraplength=440, justify="left")
        self.lbl_estado_anim.pack(anchor="w", pady=(5, 0))

        marco_t = ttk.LabelFrame(cont, text="Tiempos medidos",
                                 padding=8, style="Card.TLabelframe")
        marco_t.pack(fill="x", pady=8)
        self.tabla_anim = ttk.Treeview(
            marco_t, columns=("modo", "hilos", "tiempo", "n"),
            show="headings", height=5)
        for col, txt, w in zip(("modo", "hilos", "tiempo", "n"),
                                ["Tarea", "Hilos o nodos", "Tiempo (s)",
                                 "Frames"],
                                [110, 100, 90, 70]):
            self.tabla_anim.heading(col, text=txt, anchor="center")
            self.tabla_anim.column(col, width=w, anchor="center")
        self.tabla_anim.pack(fill="x")

        der = ttk.Frame(self.tab_recon_cms)
        der.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        fig = Figure(figsize=(9, 8), dpi=100)
        self.ax_recon = fig.add_subplot(111, projection='3d')
        self.cv_recon = FigureCanvasTkAgg(fig, master=der)
        self.cv_recon.get_tk_widget().pack(fill="both", expand=True)

        toolbar = NavigationToolbar2Tk(self.cv_recon, der,
                                        pack_toolbar=False)
        toolbar.update()
        toolbar.pack(fill="x")

        self._anim_corriendo = False
        self._anim_job = None
        self._anim_frame_actual = 0
        self._anim_n_frames = 250

        self._dibujar_reconstruccion(0, t_anim=0.0)

    # ============================================================
    #  Reconstrucción Simulada
    # ============================================================
    def tab_recon_sim_armar(self):
        izq = ttk.Frame(self.tab_recon_sim, width=500)
        izq.pack(side="left", fill="y", padx=10, pady=10)
        izq.pack_propagate(False)

        lienzo = tk.Canvas(izq, highlightthickness=0, bg=COLORES["bg"],
                            width=470)
        barra = ttk.Scrollbar(izq, orient="vertical", command=lienzo.yview)
        cont = ttk.Frame(lienzo)
        lienzo.create_window((0, 0), window=cont, anchor="nw", width=460)
        lienzo.configure(yscrollcommand=barra.set)
        cont.bind("<Configure>",
                  lambda e: lienzo.configure(scrollregion=lienzo.bbox("all")))
        lienzo.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")

        def rueda(event):
            lienzo.yview_scroll(int(-1 * (event.delta / 120)), "units")
        lienzo.bind("<Enter>", lambda e: lienzo.bind_all("<MouseWheel>", rueda))
        lienzo.bind("<Leave>", lambda e: lienzo.unbind_all("<MouseWheel>"))

        ttk.Label(cont, text="Video de la colisión simulada",
                  font=("Segoe UI", 15, "bold"),
                  foreground=COLORES["accent"]).pack(pady=(8, 4))
        ttk.Label(cont,
                  text="Eventos generados desde cero con masa invariante "
                       "fija. Cada evento se convierte en una animación 3D "
                       "de cinco segundos.",
                  wraplength=450, justify="left",
                  foreground=COLORES["fg_dim"]).pack(pady=5)

        pre = ttk.LabelFrame(cont, text="Carga de eventos simulados",
                             padding=10, style="Card.TLabelframe")
        pre.pack(fill="x", pady=8)

        ttk.Label(pre,
                  text=("Aquí NO se usan hilos: los eventos ya vienen "
                        "generados en simulacion_eventos.csv. Solo se "
                        "cargan y se animan."),
                  font=("Segoe UI", 8, "italic"),
                  foreground=COLORES["fg_dim"],
                  wraplength=430, justify="left").pack(anchor="w", pady=(0, 4))

        ttk.Button(pre, text="Cargar simulacion_eventos.csv",
                   command=self._recargar_eventos_sim,
                   style="Accent.TButton").pack(fill="x", pady=(6, 0))

        sel = ttk.LabelFrame(cont, text="Evento a animar",
                             padding=10, style="Card.TLabelframe")
        sel.pack(fill="x", pady=8)

        fila = ttk.Frame(sel)
        fila.pack(fill="x", pady=4)
        ttk.Label(fila, text="Número:").pack(side="left")
        self.entry_evento_sim = ttk.Entry(fila, width=10)
        self.entry_evento_sim.pack(side="left", padx=5)
        ttk.Button(fila, text="Ir",
                   command=self._ir_a_evento_sim).pack(side="left", padx=2)
        ttk.Button(fila, text="Aleatorio",
                   command=self._evento_aleatorio_sim).pack(side="left", padx=2)

        self.slider_evento_sim = ttk.Scale(
            sel, from_=0, to=max(1, self._n_eventos_sim - 1),
            orient="horizontal", command=self._slider_callback_sim)
        self.slider_evento_sim.pack(fill="x", pady=(6, 2))
        self.lbl_slider_sim = ttk.Label(
            sel, text=f"0 / {max(0, self._n_eventos_sim - 1)}",
            font=("Consolas", 10), foreground=COLORES["fg_dim"])
        self.lbl_slider_sim.pack(anchor="center")

        info = ttk.LabelFrame(cont, text="Datos del evento",
                              padding=10, style="Card.TLabelframe")
        info.pack(fill="x", pady=8)

        self.lbl_evento_masa_sim = ttk.Label(
            info, text="m_target = - GeV",
            font=("Consolas", 12, "bold"),
            foreground=COLORES["accent"])
        self.lbl_evento_masa_sim.pack(anchor="w", pady=(0, 8))

        self.lbl_evento_muon1_sim = ttk.Label(
            info, text="Muón 1: pT=-, eta=-, phi=-",
            font=("Consolas", 9), foreground="#c62828")
        self.lbl_evento_muon1_sim.pack(anchor="w")
        self.lbl_evento_muon2_sim = ttk.Label(
            info, text="Muón 2: pT=-, eta=-, phi=-",
            font=("Consolas", 9), foreground="#1565c0")
        self.lbl_evento_muon2_sim.pack(anchor="w")

        ctrl = ttk.LabelFrame(cont, text="Reproducción",
                              padding=10, style="Card.TLabelframe")
        ctrl.pack(fill="x", pady=8)

        ttk.Button(ctrl, text="Generar video (medir tiempo)",
                   command=self._generar_video_sim,
                   style="Accent.TButton").pack(fill="x", pady=3)

        self.btn_play_sim = ttk.Button(
            ctrl, text="Reproducir colisión (5 s)",
            command=self._toggle_animacion_sim,
            style="Play.TButton")
        self.btn_play_sim.pack(fill="x", pady=3)

        self.progress_var_sim = tk.DoubleVar(value=0.0)
        ttk.Progressbar(ctrl, variable=self.progress_var_sim,
                        maximum=100.0).pack(fill="x", pady=(6, 2))

        self.lbl_estado_anim_sim = ttk.Label(
            ctrl, text="Listo",
            font=("Consolas", 9), foreground=COLORES["fg_dim"],
            wraplength=440, justify="left")
        self.lbl_estado_anim_sim.pack(anchor="w", pady=(5, 0))

        marco_t = ttk.LabelFrame(cont, text="Tiempos medidos",
                                 padding=8, style="Card.TLabelframe")
        marco_t.pack(fill="x", pady=8)
        self.tabla_anim_sim = ttk.Treeview(
            marco_t, columns=("modo", "hilos", "tiempo", "n"),
            show="headings", height=5)
        for col, txt, w in zip(("modo", "hilos", "tiempo", "n"),
                                ["Tarea", "Hilos o nodos", "Tiempo (s)",
                                 "Frames"],
                                [110, 100, 90, 70]):
            self.tabla_anim_sim.heading(col, text=txt, anchor="center")
            self.tabla_anim_sim.column(col, width=w, anchor="center")
        self.tabla_anim_sim.pack(fill="x")

        der = ttk.Frame(self.tab_recon_sim)
        der.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        fig = Figure(figsize=(9, 8), dpi=100)
        self.ax_recon_sim = fig.add_subplot(111, projection='3d')
        self.cv_recon_sim = FigureCanvasTkAgg(fig, master=der)
        self.cv_recon_sim.get_tk_widget().pack(fill="both", expand=True)

        toolbar = NavigationToolbar2Tk(self.cv_recon_sim, der,
                                       pack_toolbar=False)
        toolbar.update()
        toolbar.pack(fill="x")

        self._anim_corriendo_sim = False
        self._anim_job_sim = None
        self._anim_frame_actual_sim = 0
        self._anim_n_frames_sim = 250

        self._dibujar_reconstruccion_sim(0, t_anim=0.0)

    # ---------- Reconstrucción sim: callbacks ----------
    def _recargar_eventos_sim(self):
        ruta = os.path.join(self.ruta_windows, "simulacion_eventos.csv")
        if not os.path.exists(ruta):
            messagebox.showwarning("Sin archivo",
                "No existe simulacion_eventos.csv. Corre primero "
                "una simulación desde la sub-pestaña 'Simulación'.")
            return
        try:
            arr = np.loadtxt(ruta, delimiter=',', skiprows=1)
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            self._eventos_sim = arr[:, :7]
            self._n_eventos_sim = len(arr)
            self._evento_sim_actual = 0

            centros, conteos, xlim = self._histograma_sim(arr[:, 7])
            self._datos_sim_masas = centros
            self._datos_sim_conteos = conteos
            self._sim_xlim_max = xlim
            if self._n_eventos_sim > 0:
                self._sim_masa_actual = float(arr[0, 6])

            self.slider_evento_sim.config(to=max(1, self._n_eventos_sim - 1))
            self.lbl_slider_sim.config(text=f"0 / {self._n_eventos_sim - 1}")
            self.slider_evento_sim.set(0)
            self._anim_frame_actual_sim = 0
            self.progress_var_sim.set(0.0)
            self._dibujar_reconstruccion_sim(0, t_anim=0.0)
            messagebox.showinfo("Listo",
                f"Cargué {self._n_eventos_sim} eventos simulados.")
        except (OSError, ValueError) as e:
            messagebox.showerror("Error",
                f"No pude leer simulacion_eventos.csv:\n{e}")

    def _slider_callback_sim(self, valor):
        if self._n_eventos_sim <= 0:
            return
        try:
            idx = int(float(valor))
        except (TypeError, ValueError):
            return
        idx = max(0, min(idx, self._n_eventos_sim - 1))
        self._evento_sim_actual = idx
        self.lbl_slider_sim.config(text=f"{idx} / {self._n_eventos_sim - 1}")
        self._detener_animacion_sim(silencioso=True)
        self._dibujar_reconstruccion_sim(idx, t_anim=1.0)

    def _evento_aleatorio_sim(self):
        if self._n_eventos_sim <= 0:
            return
        idx = random.randint(0, self._n_eventos_sim - 1)
        self.slider_evento_sim.set(idx)

    def _ir_a_evento_sim(self):
        if self._n_eventos_sim <= 0:
            return
        try:
            n = int(self.entry_evento_sim.get())
        except (TypeError, ValueError):
            messagebox.showwarning("Valor inválido",
                f"Escribe un número entre 0 y {self._n_eventos_sim - 1}.")
            return
        if n < 0 or n >= self._n_eventos_sim:
            messagebox.showwarning("Fuera de rango",
                f"El evento debe estar entre 0 y "
                f"{self._n_eventos_sim - 1}.")
            return
        self.slider_evento_sim.set(n)

    def _generar_video_sim(self):
        if self._n_eventos_sim <= 0:
            messagebox.showwarning("Sin datos",
                "Primero carga eventos simulados.")
            return
        n_frames = self._anim_n_frames_sim
        self.lbl_estado_anim_sim.config(
            text=f"Generando {n_frames} frames...",
            foreground=COLORES["accent"])
        self.root.update_idletasks()

        t0 = time.perf_counter()
        for i in range(n_frames):
            t_norm = i / (n_frames - 1)
            self._dibujar_reconstruccion_sim(self._evento_sim_actual,
                                              t_anim=t_norm, draw=False)
        t1 = time.perf_counter()
        self.cv_recon_sim.draw()
        t_fin = time.perf_counter()

        self.lbl_estado_anim_sim.config(
            text=(f"Video listo. Cómputo: {t1-t0:.3f} s  ·  "
                  f"Con dibujo final: {t_fin-t0:.3f} s"),
            foreground=COLORES["success"])
        self.tabla_anim_sim.insert("", "end", values=(
            "Video Sim", "-", f"{t1-t0:.4f}", f"{n_frames}"))

    def _toggle_animacion_sim(self):
        if self._anim_corriendo_sim:
            self._detener_animacion_sim()
        else:
            self._iniciar_animacion_sim()

    def _iniciar_animacion_sim(self):
        if self._n_eventos_sim <= 0:
            return
        self._anim_corriendo_sim = True
        self._anim_frame_actual_sim = 0
        self.btn_play_sim.config(text="Detener animación")
        self.lbl_estado_anim_sim.config(text="Reproduciendo...",
                                         foreground=COLORES["success"])
        self.progress_var_sim.set(0.0)
        self._anim_t0_sim = time.perf_counter()
        self._anim_job_sim = self.root.after(0, self._paso_animacion_sim)

    def _detener_animacion_sim(self, silencioso=False):
        self._anim_corriendo_sim = False
        if self._anim_job_sim is not None:
            try:
                self.root.after_cancel(self._anim_job_sim)
            except TclError:
                # El job ya se disparó y no se puede cancelar, no es
                # un problema real.
                pass
            self._anim_job_sim = None
        self.btn_play_sim.config(text="Reproducir colisión (5 s)")
        if not silencioso:
            self.lbl_estado_anim_sim.config(text="Detenida",
                                             foreground=COLORES["fg_dim"])

    def _paso_animacion_sim(self):
        if not self._anim_corriendo_sim:
            return
        n = self._anim_n_frames_sim
        i = self._anim_frame_actual_sim
        t_norm = i / (n - 1)
        self._dibujar_reconstruccion_sim(self._evento_sim_actual,
                                          t_anim=t_norm, draw=True)
        self.progress_var_sim.set(t_norm * 100.0)

        self._anim_frame_actual_sim += 1
        if self._anim_frame_actual_sim >= n:
            t_total = time.perf_counter() - self._anim_t0_sim
            self._anim_corriendo_sim = False
            self.btn_play_sim.config(text="Reproducir colisión (5 s)")
            self.lbl_estado_anim_sim.config(
                text=f"Reproducción terminada en {t_total:.2f} s "
                     f"({n} frames)",
                foreground=COLORES["success"])
            self.tabla_anim_sim.insert("", "end", values=(
                "Playback Sim", "-", f"{t_total:.4f}", f"{n}"))
            self._anim_job_sim = None
            return
        self._anim_job_sim = self.root.after(20, self._paso_animacion_sim)

    def _dibujar_reconstruccion_sim(self, idx, t_anim=1.0, draw=True):
        ax = self.ax_recon_sim
        ax.clear()

        if self._eventos_sim is None or self._n_eventos_sim == 0:
            ax.text2D(0.5, 0.5,
                      "Sin datos simulados.\nGenera eventos en la "
                      "sub-pestaña 'Simulación' y\nluego pulsa "
                      "'Cargar simulacion_eventos.csv'.",
                      transform=ax.transAxes, ha='center', va='center',
                      fontsize=11, color=COLORES["fg_dim"])
            ax.set_title("Reconstrucción de evento simulado", fontsize=11)
            if draw:
                self.cv_recon_sim.draw()
            return

        idx = max(0, min(idx, self._n_eventos_sim - 1))
        ev = self._eventos_sim[idx]
        pt1, eta1, phi1 = float(ev[0]), float(ev[1]), float(ev[2])
        pt2, eta2, phi2 = float(ev[3]), float(ev[4]), float(ev[5])
        M_target = float(ev[6])

        m2 = 2.0 * pt1 * pt2 * (np.cosh(eta1 - eta2) - np.cos(phi1 - phi2))
        m_calc = float(np.sqrt(m2)) if m2 > 0 else 0.0

        self.lbl_evento_masa_sim.config(
            text=f"m_target = {M_target:.4f} GeV  ·  "
                 f"m_calc = {m_calc:.4f} GeV")
        self.lbl_evento_muon1_sim.config(
            text=f"Muón 1: pT={pt1:.2f}, eta={eta1:.2f}, phi={phi1:.2f}")
        self.lbl_evento_muon2_sim.config(
            text=f"Muón 2: pT={pt2:.2f}, eta={eta2:.2f}, phi={phi2:.2f}")

        def unit(eta, phi):
            v = np.array([np.cos(phi), np.sin(phi), np.sinh(eta)])
            return v / (np.linalg.norm(v) + 1e-12)

        u1 = unit(eta1, phi1)
        u2 = unit(eta2, phi2)
        R = max(pt1, pt2) * 1.5

        if t_anim < 0.45:
            f = 1.0 - (t_anim / 0.45)
            p1 = -u1 * R * f
            p2 = -u2 * R * f
            r_muon, r_res = 400, 0
        elif t_anim < 0.55:
            p1 = p2 = np.array([0.0, 0.0, 0.0])
            r_muon, r_res = 400, 400
        else:
            t_exp = (t_anim - 0.55) / 0.45
            p1 = u1 * R * t_exp
            p2 = u2 * R * t_exp
            r_muon = 400
            r_res = int(400 + 900 * (1.0 - t_exp))

        ax.scatter([p1[0]], [p1[1]], [p1[2]], color='#e53935', s=r_muon,
                   edgecolors='#7f1010', linewidths=2, depthshade=False,
                   label=f"Muón 1 (pT={pt1:.1f} GeV)")
        ax.scatter([p2[0]], [p2[1]], [p2[2]], color='#1e88e5', s=r_muon,
                   edgecolors='#0d47a1', linewidths=2, depthshade=False,
                   label=f"Muón 2 (pT={pt2:.1f} GeV)")

        ax.plot([p1[0], 0], [p1[1], 0], [p1[2], 0],
                color='#e53935', lw=1.4, alpha=0.35)
        ax.plot([p2[0], 0], [p2[1], 0], [p2[2], 0],
                color='#1e88e5', lw=1.4, alpha=0.35)

        if t_anim >= 0.45:
            ax.scatter([0], [0], [0], color='#ffca28', s=r_res,
                       edgecolors='#a67c00', linewidths=3, depthshade=False,
                       zorder=20,
                       label=f"Resonancia simulada (m={M_target:.2f} GeV)")
        else:
            ax.scatter([0], [0], [0], color='#ffca28', s=150,
                       edgecolors='#a67c00', linewidths=2,
                       depthshade=False, zorder=10)

        ax.set_xlabel("x [GeV]")
        ax.set_ylabel("y [GeV]")
        ax.set_zlabel("z [GeV]")
        ax.set_xlim(-R, R)
        ax.set_ylim(-R, R)
        ax.set_zlim(-R, R)

        if t_anim < 0.45:
            fase = "Aproximación"
        elif t_anim < 0.55:
            fase = "Colisión"
        elif t_anim < 0.75:
            fase = "Expansión"
        else:
            fase = "Decaimiento"
        ax.set_title(f"Evento sim #{idx}  ·  {fase}  ·  "
                     f"m_target = {M_target:.2f} GeV",
                     fontsize=11, pad=12)

        ax.legend(loc="upper right", fontsize=8)

        PanelGraficas.aplicar_estilo(ax)
        if draw:
            self.cv_recon_sim.draw()

    # ============================================================
    #  Reconstrucción CMS: callbacks
    # ============================================================
    def _actualizar_hilos_anim(self):
        modo = self.modo_anim.get()
        n_rpi = len(self.rpi_hosts)
        if modo == "rpi":
            if n_rpi > 0:
                valores = list(range(1, n_rpi + 1))
            else:
                valores = [1]
            self.radio_rpi_recon.config(
                text=f"En el clúster de Raspberry Pi ({n_rpi} nodos)")
        else:
            valores = self.secuencia_hilos
        self.combo_hilos_anim.config(values=valores)
        self.combo_hilos_anim.current(0)

    def _precomputar_animacion(self):
        if self.prueba_en_curso:
            self._avisar_ocupado(self.cons_col_pc)
            return
        if not self.binarios_listos:
            messagebox.showwarning("Sin binarios",
                "Los binarios todavía se están compilando.")
            return

        modo = self.modo_anim.get()
        try:
            n = int(self.combo_hilos_anim.get())
        except (TypeError, ValueError):
            n = 1

        if modo == "pc":
            self._precomputar_pc(n)
        else:
            if not self.rpi_hosts:
                messagebox.showwarning("Sin nodos",
                    "Primero escanea la red desde la pestaña Hilos RPi.")
                return
            self._precomputar_rpi(n)

    def _precomputar_pc(self, n):
        self.prueba_en_curso = True
        consola = self.cons_col_pc
        self.log(consola, f"\nPrecomputando {n} hilo(s) en esta PC...")

        def tarea():
            cmd = (f"wsl bash -c \"cd '{self.ruta_wsl}' && "
                   f"mpirun -np {n} ./anim_core\"")
            rc, out, err = self._ejecutar_proceso(cmd, timeout=300)
            if rc != 0:
                self.log(consola, f"[Error]\n{err}")
                self.prueba_en_curso = False
                return
            self.log(consola, out.strip())
            t = self._tiempo(out)
            n_ev = self._n_eventos_de(out)
            if t is not None:
                self.root.after(0, self._registrar_tiempo,
                                "Precomp PC", n, t, n_ev)
                self.root.after(0, self._recargar_eventos)
            self.prueba_en_curso = False
        threading.Thread(target=tarea, daemon=True).start()

    def _precomputar_rpi(self, n):
        self.prueba_en_curso = True
        consola = self.cons_col_rpi
        self.log(consola, f"\nPrecomputando {n} nodo(s) en el clúster...")

        def tarea():
            cmd = self._cmd_rpi("anim_core", int(n))
            if not cmd:
                self.prueba_en_curso = False
                return
            rc, out, err = self._ejecutar_proceso(cmd, timeout=300, shell=False)
            if rc != 0:
                self.log(consola, f"[Error SSH]\n{err.strip()}")
                self.prueba_en_curso = False
                return
            self.log(consola, out.strip())
            t = self._tiempo(out)
            n_ev = self._n_eventos_de(out)
            if t is not None:
                self.root.after(0, self._registrar_tiempo,
                                "Precomp RPi", n, t, n_ev)
            csv = self._leer_csv_remoto("animacion_eventos.csv")
            if csv:
                with open(os.path.join(self.ruta_windows,
                                        "animacion_eventos.csv"), "w") as f:
                    f.write(csv)
                self.root.after(0, self._recargar_eventos)
            self.prueba_en_curso = False
        threading.Thread(target=tarea, daemon=True).start()

    def _n_eventos_de(self, salida):
        m = re.search(r'Eventos precomputados:\s*(\d+)', salida)
        return int(m.group(1)) if m else 0

    def _registrar_tiempo(self, modo, n, t, n_ev):
        self.tabla_anim.insert("", "end", values=(
            modo, n, f"{t:.4f}", f"{n_ev:,}".replace(",", " ")))

    def _recargar_eventos(self):
        ruta = os.path.join(self.ruta_windows, "animacion_eventos.csv")
        if not os.path.exists(ruta):
            return
        try:
            arr = np.loadtxt(ruta, delimiter=',', skiprows=1,
                             max_rows=100_000)
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            self._eventos_cms = arr[:, [0, 1, 2, 3, 4, 5, 6]]
            self._n_eventos_cms = len(self._eventos_cms)
            self.slider_evento.config(to=max(1, self._n_eventos_cms - 1))
            self.lbl_slider.config(text=f"0 / {self._n_eventos_cms - 1}")
            self._evento_actual = 0
            self.slider_evento.set(0)
            self._anim_frame_actual = 0
            self.progress_var.set(0.0)
            self._dibujar_reconstruccion(0, t_anim=0.0)
            messagebox.showinfo("Listo",
                f"Se precomputaron {self._n_eventos_cms} eventos.")
        except (OSError, ValueError) as e:
            messagebox.showerror("Error",
                f"No pude leer animacion_eventos.csv:\n{e}")

    def _slider_callback(self, valor):
        if self._n_eventos_cms <= 0:
            return
        try:
            idx = int(float(valor))
        except (TypeError, ValueError):
            return
        idx = max(0, min(idx, self._n_eventos_cms - 1))
        self._evento_actual = idx
        self.lbl_slider.config(text=f"{idx} / {self._n_eventos_cms - 1}")
        self._detener_animacion(silencioso=True)
        self._dibujar_reconstruccion(idx, t_anim=1.0)

    def _evento_aleatorio(self):
        if self._n_eventos_cms <= 0:
            return
        idx = random.randint(0, self._n_eventos_cms - 1)
        self.slider_evento.set(idx)

    def _ir_a_evento(self):
        if self._n_eventos_cms <= 0:
            return
        try:
            n = int(self.entry_evento.get())
        except (TypeError, ValueError):
            messagebox.showwarning("Valor inválido",
                f"Escribe un número entre 0 y {self._n_eventos_cms - 1}.")
            return
        if n < 0 or n >= self._n_eventos_cms:
            messagebox.showwarning("Fuera de rango",
                f"El evento debe estar entre 0 y {self._n_eventos_cms - 1}.")
            return
        self.slider_evento.set(n)

    def _generar_video(self):
        if self._n_eventos_cms <= 0:
            messagebox.showwarning("Sin datos",
                "Primero precomputa eventos.")
            return
        n_frames = self._anim_n_frames
        self.lbl_estado_anim.config(
            text=f"Generando {n_frames} frames...",
            foreground=COLORES["accent"])
        self.root.update_idletasks()

        t0 = time.perf_counter()
        for i in range(n_frames):
            t_norm = i / (n_frames - 1)
            self._dibujar_reconstruccion(self._evento_actual,
                                          t_anim=t_norm, draw=False)
        t1 = time.perf_counter()
        self.cv_recon.draw()
        t_fin = time.perf_counter()

        self.lbl_estado_anim.config(
            text=(f"Video listo. Cómputo: {t1-t0:.3f} s  ·  "
                  f"Con dibujo final: {t_fin-t0:.3f} s"),
            foreground=COLORES["success"])
        self.tabla_anim.insert("", "end", values=(
            "Video PC", "-", f"{t1-t0:.4f}", f"{n_frames}"))

    def _toggle_animacion(self):
        if self._anim_corriendo:
            self._detener_animacion()
        else:
            self._iniciar_animacion()

    def _iniciar_animacion(self):
        if self._n_eventos_cms <= 0:
            return
        self._anim_corriendo = True
        self._anim_frame_actual = 0
        self.btn_play.config(text="Detener animación")
        self.lbl_estado_anim.config(text="Reproduciendo...",
                                     foreground=COLORES["success"])
        self.progress_var.set(0.0)
        self._anim_t0 = time.perf_counter()
        self._anim_job = self.root.after(0, self._paso_animacion)

    def _detener_animacion(self, silencioso=False):
        self._anim_corriendo = False
        if self._anim_job is not None:
            try:
                self.root.after_cancel(self._anim_job)
            except TclError:
                pass
            self._anim_job = None
        self.btn_play.config(text="Reproducir colisión (5 s)")
        if not silencioso:
            self.lbl_estado_anim.config(text="Detenida",
                                         foreground=COLORES["fg_dim"])

    def _paso_animacion(self):
        if not self._anim_corriendo:
            return
        n = self._anim_n_frames
        i = self._anim_frame_actual
        t_norm = i / (n - 1)
        self._dibujar_reconstruccion(self._evento_actual, t_anim=t_norm,
                                      draw=True)
        self.progress_var.set(t_norm * 100.0)

        self._anim_frame_actual += 1
        if self._anim_frame_actual >= n:
            t_total = time.perf_counter() - self._anim_t0
            self._anim_corriendo = False
            self.btn_play.config(text="Reproducir colisión (5 s)")
            self.lbl_estado_anim.config(
                text=f"Reproducción terminada en {t_total:.2f} s "
                     f"({n} frames)",
                foreground=COLORES["success"])
            self.tabla_anim.insert("", "end", values=(
                "Playback", "-", f"{t_total:.4f}", f"{n}"))
            self._anim_job = None
            return
        self._anim_job = self.root.after(20, self._paso_animacion)

    def _dibujar_reconstruccion(self, idx, t_anim=1.0, draw=True):
        ax = self.ax_recon
        ax.clear()

        if self._eventos_cms is None or self._n_eventos_cms == 0:
            ax.text2D(0.5, 0.5,
                      "Sin datos.\nUsa el botón Precomputar eventos.",
                      transform=ax.transAxes, ha='center', va='center',
                      fontsize=12, color=COLORES["fg_dim"])
            ax.set_title("Reconstrucción visual", fontsize=11)
            if draw:
                self.cv_recon.draw()
            return

        idx = max(0, min(idx, self._n_eventos_cms - 1))
        ev = self._eventos_cms[idx]
        pt1, eta1, phi1 = float(ev[0]), float(ev[1]), float(ev[2])
        pt2, eta2, phi2 = float(ev[3]), float(ev[4]), float(ev[5])
        M = float(ev[6])

        self.lbl_evento_masa.config(text=f"m(mu mu) = {M:.2f} GeV")
        self.lbl_evento_muon1.config(
            text=f"Muón 1: pT={pt1:.2f}, eta={eta1:.2f}, phi={phi1:.2f}")
        self.lbl_evento_muon2.config(
            text=f"Muón 2: pT={pt2:.2f}, eta={eta2:.2f}, phi={phi2:.2f}")

        def unit(eta, phi):
            v = np.array([np.cos(phi), np.sin(phi), np.sinh(eta)])
            return v / (np.linalg.norm(v) + 1e-12)

        u1 = unit(eta1, phi1)
        u2 = unit(eta2, phi2)
        R = max(pt1, pt2) * 1.5

        if t_anim < 0.45:
            f = 1.0 - (t_anim / 0.45)
            p1 = -u1 * R * f
            p2 = -u2 * R * f
            r_muon, r_res = 400, 0
        elif t_anim < 0.55:
            p1 = p2 = np.array([0.0, 0.0, 0.0])
            r_muon, r_res = 400, 400
        else:
            t_exp = (t_anim - 0.55) / 0.45
            p1 = u1 * R * t_exp
            p2 = u2 * R * t_exp
            r_muon = 400
            r_res = int(400 + 900 * (1.0 - t_exp))

        ax.scatter([p1[0]], [p1[1]], [p1[2]], color='#e53935', s=r_muon,
                   edgecolors='#7f1010', linewidths=2, depthshade=False,
                   label=f"Muón 1 (pT={pt1:.1f} GeV)")
        ax.scatter([p2[0]], [p2[1]], [p2[2]], color='#1e88e5', s=r_muon,
                   edgecolors='#0d47a1', linewidths=2, depthshade=False,
                   label=f"Muón 2 (pT={pt2:.1f} GeV)")

        ax.plot([p1[0], 0], [p1[1], 0], [p1[2], 0],
                color='#e53935', lw=1.4, alpha=0.35)
        ax.plot([p2[0], 0], [p2[1], 0], [p2[2], 0],
                color='#1e88e5', lw=1.4, alpha=0.35)

        if t_anim >= 0.45:
            ax.scatter([0], [0], [0], color='#ffca28', s=r_res,
                       edgecolors='#a67c00', linewidths=3, depthshade=False,
                       zorder=20, label=f"Resonancia (m={M:.2f} GeV)")
        else:
            ax.scatter([0], [0], [0], color='#ffca28', s=150,
                       edgecolors='#a67c00', linewidths=2,
                       depthshade=False, zorder=10)

        ax.set_xlabel("x [GeV]")
        ax.set_ylabel("y [GeV]")
        ax.set_zlabel("z [GeV]")
        ax.set_xlim(-R, R)
        ax.set_ylim(-R, R)
        ax.set_zlim(-R, R)

        if t_anim < 0.45:
            fase = "Aproximación"
        elif t_anim < 0.55:
            fase = "Colisión"
        elif t_anim < 0.75:
            fase = "Expansión"
        else:
            fase = "Decaimiento"
        ax.set_title(f"Evento #{idx}  ·  {fase}  ·  "
                     f"m(mu mu) = {M:.2f} GeV",
                     fontsize=11, pad=12)

        ax.legend(loc="upper right", fontsize=8)

        PanelGraficas.aplicar_estilo(ax)
        if draw:
            self.cv_recon.draw()

    # ============================================================
    #  Plots compartidos
    # ============================================================
    def _plot_tiempos_amdahl(self, ax_t, ax_a, hilos, tiempos, color, titulo):
        if ax_t:
            ax_t.clear()
            if hilos:
                ax_t.plot(hilos, tiempos, marker='o', color=color,
                          linewidth=2)
                ax_t.set_xticks(hilos)
            ax_t.set_title(f"Tiempo de ejecución - {titulo}", fontsize=11)
            ax_t.set_xlabel("Hilos (p)")
            ax_t.set_ylabel("Tiempo (s)")
        if ax_a:
            ax_a.clear()
            if hilos:
                speedup = [tiempos[0] / t if t > 0 else 0 for t in tiempos]
                ax_a.plot(hilos, speedup, marker='s', color=color,
                          linewidth=2, label="Medición empírica")
                ax_a.plot(hilos, hilos, linestyle=':', color='gray',
                          label="Amdahl (ideal)")
                ax_a.set_xticks(hilos)
            ax_a.set_title("Eficiencia y escalabilidad", fontsize=11)
            ax_a.set_xlabel("Hilos (p)")
            ax_a.set_ylabel("Aceleración S(p)")
            ax_a.legend(fontsize=9)

    def _plot_espectro(self, ax, masas, recalc, cms, preset=None):
        ax.clear()
        if recalc is not None:
            ax.plot(masas, recalc, color="#e53935", lw=1.5,
                    label="Recalculado")
        if cms is not None:
            ax.plot(masas, cms, color="#111111", ls=":", lw=1.2,
                    label="Columna M del CMS")
        if preset is not None:
            _, _, masa, _ = rango_de_preset(preset)
            if masa is not None:
                ax.axvline(masa, color="#555555", ls=":",
                            lw=1.5, alpha=0.85,
                            label=f"m teórica = {masa} GeV")
        ax.set_yscale('log')
        ax.set_title("Espectro de masa invariante m(mu mu)",
                     fontsize=11, pad=12)
        ax.set_xlabel("m(mu mu) [GeV]")
        ax.set_ylabel("Eventos por bin (escala log)")
        ax.legend(loc="upper right", fontsize=8)

    def _plot_espectro_vacio(self, ax):
        ax.set_title("Espectro de masa invariante m(mu mu)", fontsize=11)
        ax.set_xlabel("m(mu mu) [GeV]")
        ax.set_ylabel("Eventos por bin (escala log)")

    def _plot_tiempos(self, ax, hilos, tiempos):
        ax.clear()
        ax.plot(hilos, tiempos, marker="o", color="#1e88e5", lw=2)
        ax.set_title("Tiempo de ejecución vs hilos", fontsize=11, pad=12)
        ax.set_xlabel("Hilos (p)")
        ax.set_ylabel("Tiempo (s)")
        ax.set_xticks(hilos)

    def _plot_tiempos_vacio(self, ax, xlabel="Hilos (p)"):
        ax.set_title("Tiempo de ejecución vs hilos", fontsize=11)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("Tiempo (s)")

    def _plot_comparacion(self, ax_cms, ax_recalc, masas, recalc, cms,
                           preset=None):
        ax_cms.clear()
        ax_recalc.clear()

        masa_teorica = None
        if preset is not None:
            _, _, masa_teorica, _ = rango_de_preset(preset)

        if masas is not None and cms is not None:
            c = np.asarray(cms, dtype=float)
            if c.sum() > 0:
                ax_cms.step(masas, c / c.sum(), where='mid',
                            color="#111111", lw=1.6,
                            label="Columna M del CMS")
        if masa_teorica is not None:
            ax_cms.axvline(masa_teorica, color="#555555", ls=":",
                            lw=1.4, alpha=0.8,
                            label=f"m teórica = {masa_teorica} GeV")
        ax_cms.set_yscale('log')
        ax_cms.set_xlim(0, 120)
        ax_cms.set_title("Datos del CMS (columna M)", fontsize=10)
        ax_cms.set_xlabel("m(mu mu) [GeV]")
        ax_cms.set_ylabel("Fracción por bin (log)")
        ax_cms.legend(loc="upper right", fontsize=8)

        if masas is not None and recalc is not None:
            r = np.asarray(recalc, dtype=float)
            if r.sum() > 0:
                ax_recalc.step(masas, r / r.sum(), where='mid',
                               color="#e53935", lw=1.6,
                               label="Recalculado por mi código")
            if masa_teorica is not None:
                ax_recalc.axvline(masa_teorica, color="#555555", ls=":",
                                    lw=1.4, alpha=0.8)
            ax_recalc.set_yscale('log')
            ax_recalc.set_xlim(0, 120)
            ax_recalc.legend(loc="upper right", fontsize=8)

            if self._n_eventos > 0:
                txt = (f"Delta media = {self._diff_media:.2e} GeV\n"
                       f"Delta sigma = {self._diff_sigma:.2e} GeV\n"
                       f"N = {self._n_eventos:,}".replace(",", " "))
                ax_recalc.text(0.02, 0.05, txt,
                               transform=ax_recalc.transAxes,
                               fontsize=8, verticalalignment='bottom',
                               bbox=dict(boxstyle='round',
                                         facecolor=COLORES["bg2"],
                                         edgecolor=COLORES["border"],
                                         alpha=0.9))
        else:
            ax_recalc.text(0.5, 0.5,
                           "Presiona Ejecutar para generar el recálculo",
                           transform=ax_recalc.transAxes,
                           ha='center', va='center', fontsize=10,
                           color=COLORES["fg_dim"])

        ax_recalc.set_title("Mi recálculo desde (pT, eta, phi)", fontsize=10)
        ax_recalc.set_xlabel("m(mu mu) [GeV]")
        ax_recalc.set_ylabel("Fracción por bin (log)")

    # ============================================================
    #  Reporte PDF
    # ============================================================
    def tab_reporte_armar(self):
        marco = ttk.Frame(self.tab_reporte)
        marco.pack(expand=True, fill="both", padx=40, pady=20)

        ttk.Label(marco, text="Reporte académico",
                  font=("Segoe UI", 16, "bold"),
                  foreground=COLORES["accent"]).pack(pady=10)
        ttk.Label(marco,
                  text="Oscar Pablo Morales Zuñiga - BUAP / UVEG",
                  font=("Segoe UI", 11, "italic"),
                  foreground=COLORES["fg_dim"]).pack()
        ttk.Separator(marco, orient="horizontal").pack(fill="x", pady=15)

        ttk.Label(marco, text="Marca lo que quieras incluir:",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=10)

        self.chk_mc_pc_tabla     = tk.BooleanVar(value=True)
        self.chk_mc_pc_grafica   = tk.BooleanVar(value=True)
        self.chk_col_pc_tabla    = tk.BooleanVar(value=True)
        self.chk_col_pc_grafica  = tk.BooleanVar(value=True)
        self.chk_mc_rpi_tabla    = tk.BooleanVar(value=False)
        self.chk_mc_rpi_grafica  = tk.BooleanVar(value=False)
        self.chk_col_rpi_tabla   = tk.BooleanVar(value=False)
        self.chk_col_rpi_grafica = tk.BooleanVar(value=False)
        self.chk_sim_pc_tabla    = tk.BooleanVar(value=True)
        self.chk_sim_pc_grafica  = tk.BooleanVar(value=True)
        self.chk_sim_rpi_tabla   = tk.BooleanVar(value=False)
        self.chk_sim_rpi_grafica = tk.BooleanVar(value=False)

        secciones = [
            ("Hilos Local (Monte Carlo)",
             self.chk_mc_pc_tabla, self.chk_mc_pc_grafica),
            ("Colisiones Local",
             self.chk_col_pc_tabla, self.chk_col_pc_grafica),
            ("Hilos Raspberry Pi",
             self.chk_mc_rpi_tabla, self.chk_mc_rpi_grafica),
            ("Colisiones Raspberry Pi",
             self.chk_col_rpi_tabla, self.chk_col_rpi_grafica),
            ("Simulación Local",
             self.chk_sim_pc_tabla, self.chk_sim_pc_grafica),
            ("Simulación Raspberry Pi",
             self.chk_sim_rpi_tabla, self.chk_sim_rpi_grafica),
        ]

        grid = ttk.Frame(marco)
        grid.pack(anchor="w", padx=20, pady=10)
        ttk.Label(grid, text="Sección", font=("Segoe UI", 10, "bold"),
                  width=28).grid(row=0, column=0, sticky="w", padx=5)
        ttk.Label(grid, text="Tabla", font=("Segoe UI", 10, "bold"),
                  width=8).grid(row=0, column=1, padx=5)
        ttk.Label(grid, text="Gráfica", font=("Segoe UI", 10, "bold"),
                  width=8).grid(row=0, column=2, padx=5)

        for i, (nombre, ct, cg) in enumerate(secciones, start=1):
            ttk.Label(grid, text=nombre).grid(row=i, column=0, sticky="w",
                                              padx=5, pady=3)
            ttk.Checkbutton(grid, variable=ct).grid(row=i, column=1, padx=5)
            ttk.Checkbutton(grid, variable=cg).grid(row=i, column=2, padx=5)

        ttk.Separator(marco, orient="horizontal").pack(fill="x", pady=20)
        ttk.Button(marco, text="Compilar PDF",
                   command=self.generar_pdf,
                   style="Accent.TButton").pack(pady=10)

    # ============================================================
    #  Ejecución y benchmarks
    # ============================================================
    def ejecutar_local(self, exe, hilos, consola):
        if self.prueba_en_curso:
            self._avisar_ocupado(consola)
            return
        if not self.binarios_listos:
            self.log(consola, "Aún se está compilando. Espera.")
            return
        self.prueba_en_curso = True
        self.log(consola, f"\nEjecutando {exe} con {hilos} hilo(s)...")

        def tarea():
            cmd = (f"wsl bash -c \"cd '{self.ruta_wsl}' && "
                   f"mpirun -np {hilos} ./{exe}\"")
            rc, out, err = self._ejecutar_proceso(cmd, timeout=300)
            if rc == 0:
                self.log(consola, out.strip())
            else:
                self.log(consola, f"[Error]\n{err}")
            self.prueba_en_curso = False
        threading.Thread(target=tarea, daemon=True).start()

    def _cmd_rpi(self, exe, n):
        """Comando SSH para correr un binario en el clúster. La ruta va
        entre comillas simples para que aguante espacios y caracteres
        especiales del shell sin romperse."""
        if not self.rpi_hosts:
            return None
        n = min(n, len(self.rpi_hosts))
        hosts = ",".join(self.rpi_hosts[:n])
        master = self.rpi_hosts[0]
        user = self.rpi_user.get()
        ruta = self.rpi_path.get()
        interno = (f"cd '{ruta}' && mpirun --host {hosts} "
                   f"--map-by node -np {n} ./{exe}")
        return ['wsl', 'ssh',
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'BatchMode=yes',
                '-o', 'ConnectTimeout=10',
                f'{user}@{master}', interno]

    def _leer_csv_remoto(self, nombre):
        """Traigo un archivo de la Raspberry Pi maestra vía ssh cat."""
        if not self.rpi_hosts:
            return None
        master = self.rpi_hosts[0]
        user = self.rpi_user.get()
        ruta = self.rpi_path.get()
        cmd = ['wsl', 'ssh', '-o', 'StrictHostKeyChecking=no',
               '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
               f'{user}@{master}', f"cat '{ruta}/{nombre}'"]
        rc, out, _ = self._ejecutar_proceso(cmd, timeout=30, shell=False)
        return out if rc == 0 else None

    def ejecutar_rpi(self, exe, nodos, consola):
        if self.prueba_en_curso:
            self._avisar_ocupado(consola)
            return
        if not self.binarios_listos:
            self.log(consola, "Aún se está compilando. Espera.")
            return
        if not self.rpi_hosts:
            self.log(consola, "No hay Raspberry Pi detectadas.")
            return
        self.prueba_en_curso = True
        self.log(consola, f"\nEjecutando {exe} en {nodos} nodo(s)...")

        def tarea():
            cmd = self._cmd_rpi(exe, int(nodos))
            if not cmd:
                self.prueba_en_curso = False
                return
            rc, out, err = self._ejecutar_proceso(cmd, timeout=180, shell=False)
            if rc == 0:
                self.log(consola, out.strip())
            else:
                self.log(consola, f"[Error SSH]\n{err.strip()}")
            self.prueba_en_curso = False
        threading.Thread(target=tarea, daemon=True).start()

    def _tiempo(self, salida):
        m = re.search(r'\|\s*([0-9]+(?:\.[0-9]+)?'
                       r'(?:[eE][-+]?[0-9]+)?)\s*s\s*\|', salida)
        if not m:
            m = re.search(r'\|\s*([0-9]+(?:\.[0-9]+)?'
                           r'(?:[eE][-+]?[0-9]+)?)\s*s', salida)
        return float(m.group(1)) if m else None

    def benchmark_local(self, exe, consola, panel):
        if self.prueba_en_curso or not self.binarios_listos:
            if self.prueba_en_curso:
                self._avisar_ocupado(consola)
            return
        self.prueba_en_curso = True
        self.log(consola, f"\nBenchmark local de {exe}...")

        def tarea():
            tiempos = []
            for h in self.secuencia_hilos:
                self.log(consola, f"[-] {h} hilo(s)...")
                its = []
                for _ in range(10):
                    cmd = (f"wsl bash -c \"cd '{self.ruta_wsl}' && "
                           f"mpirun -np {h} ./{exe}\"")
                    rc, out, _ = self._ejecutar_proceso(cmd, timeout=120)
                    if rc == 0:
                        t = self._tiempo(out)
                        if t is not None:
                            its.append(t)
                if its:
                    prom = sum(its) / len(its)
                    tiempos.append(prom)
                    self.log(consola, f"    Promedio: {prom:.5f} s")
                else:
                    tiempos.append(0.0)

            if all(t > 0 for t in tiempos):
                self.hilos_mc, self.tiempos_mc = \
                    self.secuencia_hilos, tiempos
                self.root.after(0, panel.redibujar)
            self.prueba_en_curso = False
        threading.Thread(target=tarea, daemon=True).start()

    def benchmark_rpi(self, exe, consola, panel):
        if self.prueba_en_curso or not self.binarios_listos:
            if self.prueba_en_curso:
                self._avisar_ocupado(consola)
            return
        if not self.rpi_hosts:
            self.log(consola, "No hay Raspberry Pi detectadas.")
            return
        self.prueba_en_curso = True
        self.log(consola, f"\nBenchmark RPi de {exe}...")

        def tarea():
            tiempos = []
            max_n = len(self.rpi_hosts)
            secuencia = list(range(1, max_n + 1))
            for h in secuencia:
                self.log(consola, f"[-] {h} nodo(s)...")
                its = []
                for _ in range(10):
                    cmd = self._cmd_rpi(exe, h)
                    if not cmd:
                        continue
                    rc, out, _ = self._ejecutar_proceso(cmd, timeout=120,
                                                        shell=False)
                    if rc == 0:
                        t = self._tiempo(out)
                        if t is not None:
                            its.append(t)
                if its:
                    prom = sum(its) / len(its)
                    tiempos.append(prom)
                    self.log(consola, f"    Promedio: {prom:.5f} s")
                else:
                    tiempos.append(0.0)

            if all(t > 0 for t in tiempos):
                self.hilos_rpi_mc, self.tiempos_rpi_mc = secuencia, tiempos
                self.root.after(0, panel.redibujar)
            self.prueba_en_curso = False
        threading.Thread(target=tarea, daemon=True).start()

    def _parsear_colision(self):
        rh = os.path.join(self.ruta_windows, "histograma_colision.csv")
        rs = os.path.join(self.ruta_windows, "estadisticas_colision.csv")
        try:
            if not os.path.exists(rh) or os.path.getsize(rh) < 5:
                return None, None, None, 0, 0.0, 0.0, 0.0
            if not os.path.exists(rs) or os.path.getsize(rs) < 5:
                return None, None, None, 0, 0.0, 0.0, 0.0

            masas, recalc, cms = [], [], []
            with open(rh) as f:
                next(f)
                for l in f:
                    p = l.strip().split(",")
                    if len(p) != 3:
                        continue
                    a, b, c = p
                    masas.append(float(a))
                    recalc.append(int(b))
                    cms.append(int(c))
            if not masas:
                return None, None, None, 0, 0.0, 0.0, 0.0

            with open(rs) as f:
                next(f)
                linea = f.readline().strip()
                if not linea:
                    return None, None, None, 0, 0.0, 0.0, 0.0
                p = linea.split(",")
                if len(p) < 4:
                    return None, None, None, 0, 0.0, 0.0, 0.0
                ev, dm, ds, t = p[0], p[1], p[2], p[3]
            return (masas, recalc, cms, int(ev), float(dm),
                    float(ds), float(t))
        except (OSError, ValueError, IndexError):
            return None, None, None, 0, 0.0, 0.0, 0.0

    def correr_col_local(self, hilos):
        if self.prueba_en_curso or not self.binarios_listos:
            if self.prueba_en_curso:
                self._avisar_ocupado(self.cons_col_pc)
            return
        self.prueba_en_curso = True
        mn = self._col_rango_min
        mx = self._col_rango_max
        self.log(self.cons_col_pc,
                 f"\nValidador local con {hilos} hilo(s) "
                 f"y rango [{mn:.2f}, {mx:.2f}] GeV...")

        def tarea():
            cmd = (f"wsl bash -c \"cd '{self.ruta_wsl}' && "
                   f"mpirun -np {hilos} ./colision_core {mn} {mx}\"")
            rc, out, err = self._ejecutar_proceso(cmd, timeout=300)
            if rc != 0:
                self.log(self.cons_col_pc, f"[Error]\n{err}")
                self.prueba_en_curso = False
                return
            self.log(self.cons_col_pc, out.strip())

            masas, recalc, cms, ev, dm, ds, t = self._parsear_colision()
            if masas is not None:
                self._datos_col_masas = masas
                self._datos_col_conteos = recalc
                self._datos_col_cms = cms
                self._diff_media = dm
                self._diff_sigma = ds
                self._n_eventos = ev

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.lbl_ts_col_pc.config(text=f"Última ejecución: {ts}")
            self.tabla_col_pc.insert("", "end", values=(
                hilos, f"{t:.4f}", f"{ev:,}".replace(",", " "),
                f"{dm:.2e}", f"{ds:.2e}", "1.00x"))
            self.root.after(0, self.panel_col_pc.redibujar)
            self.prueba_en_curso = False
        threading.Thread(target=tarea, daemon=True).start()

    def benchmark_col_local(self):
        if self.prueba_en_curso or not self.binarios_listos:
            if self.prueba_en_curso:
                self._avisar_ocupado(self.cons_col_pc)
            return
        self.prueba_en_curso = True
        mn = self._col_rango_min
        mx = self._col_rango_max
        self.log(self.cons_col_pc,
                 f"\nBenchmark local, rango [{mn:.2f}, {mx:.2f}] GeV...")

        def tarea():
            tiempos, stats = [], {}
            for h in self.secuencia_hilos:
                self.log(self.cons_col_pc, f"[-] {h} hilo(s)...")
                its = []
                for _ in range(10):
                    cmd = (f"wsl bash -c \"cd '{self.ruta_wsl}' && "
                           f"mpirun -np {h} ./colision_core {mn} {mx}\"")
                    rc, out, _ = self._ejecutar_proceso(cmd, timeout=300)
                    if rc == 0:
                        t = self._tiempo(out)
                        if t is not None:
                            its.append(t)
                        me = re.search(
                            r'Eventos procesados:\s*(\d+)', out)
                        md = re.search(
                            r'Diferencia media[^:]*:\s*([0-9eE.+\-]+)',
                            out)
                        ms = re.search(
                            r'Desviacion estandar de la diferencia:\s*'
                            r'([0-9eE.+\-]+)', out)
                        if me and md and ms:
                            stats[h] = (me.group(1), md.group(1),
                                        ms.group(1))
                if its:
                    prom = sum(its) / len(its)
                    tiempos.append(prom)
                    self.log(self.cons_col_pc,
                             f"    Promedio: {prom:.5f} s")
                    ev, dm, ds = stats.get(h, ("0", "0", "0"))
                    self.tabla_col_pc.insert("", "end", values=(
                        h, f"{prom:.4f}",
                        f"{int(ev):,}".replace(",", " "),
                        f"{float(dm):.2e}", f"{float(ds):.2e}",
                        f"{tiempos[0]/prom:.2f}x"))
                else:
                    tiempos.append(0.0)

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.lbl_ts_col_pc.config(text=f"Última ejecución: {ts}")
            self.hilos_col, self.tiempos_col = \
                self.secuencia_hilos, tiempos
            self._datos_col_tiempos = tiempos

            masas, recalc, cms, *_ = self._parsear_colision()
            if masas is not None:
                self._datos_col_masas = masas
                self._datos_col_conteos = recalc
                self._datos_col_cms = cms

            self.root.after(0, self.panel_col_pc.redibujar)
            self.prueba_en_curso = False
        threading.Thread(target=tarea, daemon=True).start()

    def correr_col_rpi(self, nodos):
        if self.prueba_en_curso or not self.binarios_listos:
            if self.prueba_en_curso:
                self._avisar_ocupado(self.cons_col_rpi)
            return
        if not self.rpi_hosts:
            self.log(self.cons_col_rpi, "No hay Raspberry Pi detectadas.")
            return
        self.prueba_en_curso = True
        mn = self._col_rango_min_rpi
        mx = self._col_rango_max_rpi
        self.log(self.cons_col_rpi,
                 f"\nValidador en {nodos} nodo(s), "
                 f"rango [{mn:.2f}, {mx:.2f}] GeV...")

        def tarea():
            cmd = self._cmd_rpi("colision_core", int(nodos))
            if not cmd:
                self.prueba_en_curso = False
                return
            cmd[-1] = cmd[-1] + f" {mn} {mx}"
            rc, out, err = self._ejecutar_proceso(cmd, timeout=180, shell=False)
            if rc != 0:
                self.log(self.cons_col_rpi, f"[Error SSH]\n{err.strip()}")
                self.prueba_en_curso = False
                return
            self.log(self.cons_col_rpi, out.strip())

            ch = self._leer_csv_remoto("histograma_colision.csv")
            cs = self._leer_csv_remoto("estadisticas_colision.csv")
            if not ch or not cs:
                self.log(self.cons_col_rpi,
                         "No pude leer los CSV del nodo.")
                self.prueba_en_curso = False
                return

            masas, recalc, cms = [], [], []
            for i, l in enumerate(ch.splitlines()):
                if i == 0:
                    continue
                p = l.strip().split(",")
                if len(p) != 3:
                    continue
                a, b, c = p
                masas.append(float(a))
                recalc.append(int(b))
                cms.append(int(c))

            lineas = cs.splitlines()
            if len(lineas) < 2:
                self.prueba_en_curso = False
                return
            partes = lineas[1].strip().split(",")
            ev, dm, ds, t = partes[0], partes[1], partes[2], partes[3]

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.lbl_ts_col_rpi.config(text=f"Última ejecución: {ts}")
            self.tabla_col_rpi.insert("", "end", values=(
                nodos, f"{float(t):.4f}",
                f"{int(ev):,}".replace(",", " "),
                f"{float(dm):.2e}", f"{float(ds):.2e}", "1.00x"))

            self._datos_rpi_col_masas = masas
            self._datos_rpi_col_conteos = recalc
            self._datos_rpi_col_cms = cms
            self.root.after(0, self.panel_col_rpi.redibujar)
            self.prueba_en_curso = False
        threading.Thread(target=tarea, daemon=True).start()

    def benchmark_col_rpi(self):
        if self.prueba_en_curso or not self.binarios_listos:
            if self.prueba_en_curso:
                self._avisar_ocupado(self.cons_col_rpi)
            return
        if not self.rpi_hosts:
            self.log(self.cons_col_rpi, "No hay Raspberry Pi detectadas.")
            return
        self.prueba_en_curso = True
        mn = self._col_rango_min_rpi
        mx = self._col_rango_max_rpi
        self.log(self.cons_col_rpi,
                 f"\nBenchmark RPi, rango [{mn:.2f}, {mx:.2f}] GeV...")

        def tarea():
            tiempos, stats = [], {}
            max_n = len(self.rpi_hosts)
            secuencia = list(range(1, max_n + 1))

            for h in secuencia:
                self.log(self.cons_col_rpi, f"[-] {h} nodo(s)...")
                its = []
                for _ in range(10):
                    cmd = self._cmd_rpi("colision_core", h)
                    if not cmd:
                        continue
                    cmd[-1] = cmd[-1] + f" {mn} {mx}"
                    rc, out, _ = self._ejecutar_proceso(cmd, timeout=180,
                                                        shell=False)
                    if rc == 0:
                        t = self._tiempo(out)
                        if t is not None:
                            its.append(t)
                        me = re.search(
                            r'Eventos procesados:\s*(\d+)', out)
                        md = re.search(
                            r'Diferencia media[^:]*:\s*([0-9eE.+\-]+)',
                            out)
                        ms = re.search(
                            r'Desviacion estandar de la diferencia:\s*'
                            r'([0-9eE.+\-]+)', out)
                        if me and md and ms:
                            stats[h] = (me.group(1), md.group(1),
                                        ms.group(1))
                if its:
                    prom = sum(its) / len(its)
                    tiempos.append(prom)
                    self.log(self.cons_col_rpi,
                             f"    Promedio: {prom:.5f} s")
                    ev, dm, ds = stats.get(h, ("0", "0", "0"))
                    self.tabla_col_rpi.insert("", "end", values=(
                        h, f"{prom:.4f}",
                        f"{int(ev):,}".replace(",", " "),
                        f"{float(dm):.2e}", f"{float(ds):.2e}",
                        f"{tiempos[0]/prom:.2f}x"))
                else:
                    tiempos.append(0.0)

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.lbl_ts_col_rpi.config(text=f"Última ejecución: {ts}")
            self.hilos_rpi_col, self.tiempos_rpi_col = secuencia, tiempos
            self._datos_rpi_col_tiempos = tiempos

            ch = self._leer_csv_remoto("histograma_colision.csv")
            if ch:
                masas, recalc, cms = [], [], []
                for i, l in enumerate(ch.splitlines()):
                    if i == 0:
                        continue
                    p = l.strip().split(",")
                    if len(p) != 3:
                        continue
                    a, b, c = p
                    masas.append(float(a))
                    recalc.append(int(b))
                    cms.append(int(c))
                self._datos_rpi_col_masas = masas
                self._datos_rpi_col_conteos = recalc
                self._datos_rpi_col_cms = cms

            self.root.after(0, self.panel_col_rpi.redibujar)
            self.prueba_en_curso = False
        threading.Thread(target=tarea, daemon=True).start()

    # ============================================================
    #  Simulación
    # ============================================================
    def _leer_params_sim(self):
        try:
            masa    = float(self.sim_masa.get())
            n_ev    = int(self.sim_eventos.get())
            pt_min  = float(self.sim_pt_min.get())
            pt_max  = float(self.sim_pt_max.get())
            eta_min = float(self.sim_eta_min.get())
            eta_max = float(self.sim_eta_max.get())
            sigma   = float(self.sim_sigma.get())
        except ValueError:
            messagebox.showerror("Parámetros inválidos",
                "Revisa que todos los campos numéricos sean válidos.")
            return None
        if pt_min >= pt_max or eta_min >= eta_max:
            messagebox.showerror("Rangos inválidos",
                "pT mín debe ser menor que pT máx, y eta mín menor que "
                "eta máx.")
            return None
        if masa <= 0 or n_ev <= 0:
            messagebox.showerror("Valores inválidos",
                "La masa y el número de eventos deben ser positivos.")
            return None
        if sigma < 0:
            messagebox.showerror("Sigma inválido",
                "La resolución (sigma) no puede ser negativa.")
            return None
        return masa, n_ev, pt_min, pt_max, eta_min, eta_max, sigma

    def _armar_cmd_sim_local(self, hilos, params):
        masa, n_ev, pt_min, pt_max, eta_min, eta_max, sigma = params
        return (f"wsl bash -c \"cd '{self.ruta_wsl}' && "
                f"mpirun -np {hilos} ./sim_core "
                f"{n_ev} {masa} {pt_min} {pt_max} {eta_min} {eta_max} "
                f"{sigma}\"")

    def _armar_cmd_sim_rpi(self, n_nodos, params):
        if not self.rpi_hosts:
            return None
        masa, n_ev, pt_min, pt_max, eta_min, eta_max, sigma = params
        n = min(int(n_nodos), len(self.rpi_hosts))
        hosts = ",".join(self.rpi_hosts[:n])
        master = self.rpi_hosts[0]
        user = self.rpi_user.get()
        ruta = self.rpi_path.get()
        interno = (f"cd '{ruta}' && mpirun --host {hosts} "
                   f"--map-by node -np {n} ./sim_core "
                   f"{n_ev} {masa} {pt_min} {pt_max} {eta_min} {eta_max} "
                   f"{sigma}")
        return ['wsl', 'ssh',
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'BatchMode=yes',
                '-o', 'ConnectTimeout=10',
                f'{user}@{master}', interno]

    def ejecutar_sim_local(self, hilos):
        if self.prueba_en_curso or not self.binarios_listos:
            if self.prueba_en_curso:
                self._avisar_ocupado(self.cons_sim_pc)
            return
        params = self._leer_params_sim()
        if not params:
            return
        masa, n_ev, _, _, _, _, sigma = params
        self.prueba_en_curso = True
        self.log(self.cons_sim_pc,
                 f"\nSimulando {n_ev} eventos con masa {masa} GeV "
                 f"y σ={sigma} GeV usando {hilos} hilo(s)...")

        def tarea():
            cmd = self._armar_cmd_sim_local(hilos, params)
            rc, out, err = self._ejecutar_proceso(cmd, timeout=300)
            if rc != 0:
                self.log(self.cons_sim_pc, f"[Error]\n{err}")
                self.prueba_en_curso = False
                return
            self.log(self.cons_sim_pc, out.strip())
            t = self._tiempo(out)
            if t is not None:
                if self._sim_baseline_s is None:
                    self._sim_baseline_s = t
                sp = (self._sim_baseline_s / t) if t > 0 else 0
                self.root.after(0, self._insertar_fila_sim,
                                self.tabla_sim_pc,
                                hilos, t, n_ev, sp)
            self.root.after(0, self._cargar_simulacion, "pc")
            self.prueba_en_curso = False
        threading.Thread(target=tarea, daemon=True).start()

    def _insertar_fila_sim(self, tabla, n, t, n_ev, sp):
        tabla.insert("", "end", values=(
            n, f"{t:.4f}", f"{n_ev:,}".replace(",", " "), f"{sp:.2f}x"))

    def benchmark_sim_local(self):
        if self.prueba_en_curso or not self.binarios_listos:
            if self.prueba_en_curso:
                self._avisar_ocupado(self.cons_sim_pc)
            return
        params = self._leer_params_sim()
        if not params:
            return
        masa, n_ev, _, _, _, _, sigma = params
        self.prueba_en_curso = True
        self.log(self.cons_sim_pc,
                 f"\nBenchmark sim local ({n_ev} eventos, "
                 f"masa {masa} GeV, σ={sigma} GeV)...")

        def tarea():
            tiempos = []
            for h in self.secuencia_hilos:
                self.log(self.cons_sim_pc, f"[-] {h} hilo(s)...")
                its = []
                for _ in range(5):
                    cmd = self._armar_cmd_sim_local(h, params)
                    rc, out, _ = self._ejecutar_proceso(cmd, timeout=300)
                    if rc == 0:
                        t = self._tiempo(out)
                        if t is not None and t > 0:
                            its.append(t)
                if its:
                    prom = sum(its) / len(its)
                    tiempos.append(prom)
                    self.log(self.cons_sim_pc,
                             f"    Promedio: {prom:.4f} s")
                else:
                    tiempos.append(0.0)

            if tiempos and tiempos[0] > 0:
                self._sim_baseline_s = tiempos[0]

            for h, t in zip(self.secuencia_hilos, tiempos):
                if t > 0:
                    sp = (tiempos[0] / t) if tiempos[0] > 0 else 0
                    self.root.after(0, self._insertar_fila_sim,
                                    self.tabla_sim_pc, h, t, n_ev, sp)

            if all(t > 0 for t in tiempos):
                self.hilos_sim, self.tiempos_sim = \
                    self.secuencia_hilos, tiempos

            self.root.after(0, self._cargar_simulacion, "pc")
            self.prueba_en_curso = False
        threading.Thread(target=tarea, daemon=True).start()

    def ejecutar_sim_rpi(self, nodos):
        if self.prueba_en_curso or not self.binarios_listos:
            if self.prueba_en_curso:
                self._avisar_ocupado(self.cons_sim_rpi)
            return
        if not self.rpi_hosts:
            self.log(self.cons_sim_rpi, "No hay Raspberry Pi detectadas.")
            return
        params = self._leer_params_sim()
        if not params:
            return
        masa, n_ev, _, _, _, _, sigma = params
        self.prueba_en_curso = True
        self.log(self.cons_sim_rpi,
                 f"\nSimulando {n_ev} eventos con masa {masa} GeV "
                 f"y σ={sigma} GeV en {nodos} nodo(s)...")

        def tarea():
            cmd = self._armar_cmd_sim_rpi(nodos, params)
            if not cmd:
                self.prueba_en_curso = False
                return
            rc, out, err = self._ejecutar_proceso(cmd, timeout=300, shell=False)
            if rc != 0:
                self.log(self.cons_sim_rpi, f"[Error SSH]\n{err.strip()}")
                self.prueba_en_curso = False
                return
            self.log(self.cons_sim_rpi, out.strip())
            t = self._tiempo(out)
            if t is not None:
                if self._sim_rpi_baseline_s is None:
                    self._sim_rpi_baseline_s = t
                sp = (self._sim_rpi_baseline_s / t) if t > 0 else 0
                self.root.after(0, self._insertar_fila_sim,
                                self.tabla_sim_rpi,
                                nodos, t, n_ev, sp)
            csv = self._leer_csv_remoto("simulacion_eventos.csv")
            if csv:
                with open(os.path.join(self.ruta_windows,
                                        "simulacion_eventos.csv"),
                          "w") as f:
                    f.write(csv)
                self.root.after(0, self._cargar_simulacion, "rpi")
            self.prueba_en_curso = False
        threading.Thread(target=tarea, daemon=True).start()

    def benchmark_sim_rpi(self):
        if self.prueba_en_curso or not self.binarios_listos:
            if self.prueba_en_curso:
                self._avisar_ocupado(self.cons_sim_rpi)
            return
        if not self.rpi_hosts:
            self.log(self.cons_sim_rpi, "No hay Raspberry Pi detectadas.")
            return
        params = self._leer_params_sim()
        if not params:
            return
        masa, n_ev, _, _, _, _, sigma = params
        self.prueba_en_curso = True
        self.log(self.cons_sim_rpi,
                 f"\nBenchmark sim RPi ({n_ev} eventos, "
                 f"masa {masa} GeV, σ={sigma} GeV)...")

        def tarea():
            tiempos = []
            max_n = len(self.rpi_hosts)
            secuencia = list(range(1, max_n + 1))
            for h in secuencia:
                self.log(self.cons_sim_rpi, f"[-] {h} nodo(s)...")
                its = []
                for _ in range(5):
                    cmd = self._armar_cmd_sim_rpi(h, params)
                    if not cmd:
                        continue
                    rc, out, _ = self._ejecutar_proceso(cmd, timeout=300,
                                                        shell=False)
                    if rc == 0:
                        t = self._tiempo(out)
                        if t is not None and t > 0:
                            its.append(t)
                if its:
                    prom = sum(its) / len(its)
                    tiempos.append(prom)
                    self.log(self.cons_sim_rpi,
                             f"    Promedio: {prom:.4f} s")
                else:
                    tiempos.append(0.0)

            if tiempos and tiempos[0] > 0:
                self._sim_rpi_baseline_s = tiempos[0]

            for h, t in zip(secuencia, tiempos):
                if t > 0:
                    sp = (tiempos[0] / t) if tiempos[0] > 0 else 0
                    self.root.after(0, self._insertar_fila_sim,
                                    self.tabla_sim_rpi, h, t, n_ev, sp)

            if all(t > 0 for t in tiempos):
                self.hilos_rpi_sim, self.tiempos_rpi_sim = \
                    secuencia, tiempos

            csv = self._leer_csv_remoto("simulacion_eventos.csv")
            if csv:
                with open(os.path.join(self.ruta_windows,
                                        "simulacion_eventos.csv"),
                          "w") as f:
                    f.write(csv)

            self.root.after(0, self._cargar_simulacion, "rpi")
            self.prueba_en_curso = False
        threading.Thread(target=tarea, daemon=True).start()

    def _cargar_simulacion(self, origen="pc"):
        """
        Lee simulacion_eventos.csv y actualiza solo el panel indicado.
        origen = "pc" actualiza Simulación Local; "rpi" actualiza RPi.
        En ambos casos también actualiza el "último cargado" que usa
        la pestaña de Reconstrucción Sim.
        """
        ruta = os.path.join(self.ruta_windows, "simulacion_eventos.csv")
        if not os.path.exists(ruta):
            return
        try:
            arr = np.loadtxt(ruta, delimiter=',', skiprows=1)
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            self._eventos_sim = arr[:, :7]
            self._n_eventos_sim = len(arr)
            self._evento_sim_actual = 0

            centros, conteos, xlim = self._histograma_sim(arr[:, 7])
            self._sim_xlim_max = xlim
            if self._n_eventos_sim > 0:
                self._sim_masa_actual = float(arr[0, 6])

            self._datos_sim_masas = centros
            self._datos_sim_conteos = conteos

            if origen == "rpi":
                self._datos_sim_masas_rpi = centros
                self._datos_sim_conteos_rpi = conteos
                self.panel_sim_rpi.redibujar()
            else:
                self._datos_sim_masas_pc = centros
                self._datos_sim_conteos_pc = conteos
                self.panel_sim_pc.redibujar()

            self.slider_evento_sim.config(
                to=max(1, self._n_eventos_sim - 1))
            self.lbl_slider_sim.config(
                text=f"0 / {self._n_eventos_sim - 1}")
            self.slider_evento_sim.set(0)
            self._anim_frame_actual_sim = 0
            self.progress_var_sim.set(0.0)
            self._dibujar_reconstruccion_sim(0, t_anim=0.0)

            consola = self.cons_sim_rpi if origen == "rpi" else self.cons_sim_pc
            self.log(consola,
                     f"[+] Simulación cargada ({origen}): "
                     f"{self._n_eventos_sim} eventos.")
        except (OSError, ValueError) as e:
            consola = self.cons_sim_rpi if origen == "rpi" else self.cons_sim_pc
            self.log(consola,
                     f"[Error] No pude leer simulacion_eventos.csv: {e}")

    # ============================================================
    #  Compilación y escaneo de red
    # ============================================================
    def compilar_binarios(self):
        def tarea():
            with open(os.path.join(self.ruta_windows, "mc_core.cpp"),
                      "w") as f:
                f.write(CPP_SIMULADOR)
            with open(os.path.join(self.ruta_windows,
                                    "colision_core.cpp"), "w") as f:
                f.write(CPP_COLISION)
            with open(os.path.join(self.ruta_windows, "anim_core.cpp"),
                      "w") as f:
                f.write(CPP_ANIMACION)
            with open(os.path.join(self.ruta_windows, "sim_core.cpp"),
                      "w") as f:
                f.write(CPP_SIMULACION)

            tareas = [
                ("mc_core.cpp",       "mc_core",
                 "Monte Carlo",       self.cons_mc_pc),
                ("colision_core.cpp", "colision_core",
                 "Validador CMS",     self.cons_col_pc),
                ("anim_core.cpp",     "anim_core",
                 "Precomputación",    self.cons_col_pc),
                ("sim_core.cpp",      "sim_core",
                 "Simulación",        self.cons_sim_pc),
            ]

            for src, dst, nombre, consola in tareas:
                self.log(consola, f"Compilando {nombre}...")
                cmd = (f"wsl bash -c \"cd '{self.ruta_wsl}' && "
                       f"mpicxx {src} -o {dst} -O3\"")
                rc, _, err = self._ejecutar_proceso(cmd, timeout=120)
                if rc == 0:
                    self.log(consola, f"{nombre} listo.")
                else:
                    self.log(consola,
                             f"Error compilando {nombre}:\n{err}")
                    return

            self.binarios_listos = True
            self.log(self.cons_mc_pc,
                     "\nTodos los binarios compilados correctamente.")
        threading.Thread(target=tarea, daemon=True).start()

    def escanear_red(self):
        def tarea():
            consolas = (self.cons_mc_rpi, self.cons_col_rpi,
                        self.cons_sim_rpi)
            for c in consolas:
                self.log(c, "\nBuscando Raspberry Pi en la red...")
            rc, out, err = self._ejecutar_proceso("arp -a", timeout=30)
            if rc != 0:
                for c in consolas:
                    self.log(c, f"Error ejecutando arp -a: {err}")
                return

            hosts = []
            for l in out.splitlines():
                if "b8-27-eb" in l or "dc-a6-32" in l:
                    m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", l)
                    if m:
                        hosts.append(m.group(1))
            hosts = list(set(hosts))
            self.rpi_hosts = hosts

            if hosts:
                self.secuencia_nodos_rpi = list(range(1, len(hosts) + 1))
                texto = f"Raspberry Pi detectadas: {len(hosts)}"
                for c in consolas:
                    self.log(c, f"Nodos: {', '.join(hosts)}")
                self.lbl_pis_mc.config(text=texto)
                self.lbl_pis_col.config(text=texto)
                self.lbl_pis_sim.config(text=texto)
            else:
                self.secuencia_nodos_rpi = [1]
                for c in consolas:
                    self.log(c, "No encontré ningún nodo.")
                self.lbl_pis_mc.config(
                    text="Raspberry Pi detectadas: 0")
                self.lbl_pis_col.config(
                    text="Raspberry Pi detectadas: 0")
                self.lbl_pis_sim.config(
                    text="Raspberry Pi detectadas: 0")

            for cb in self.combos_rpi.values():
                cb.config(values=self.secuencia_nodos_rpi)
                cb.current(0)

            self.root.after(0, self._refrescar_label_recursos)
            self.root.after(0, self._actualizar_hilos_anim)
        threading.Thread(target=tarea, daemon=True).start()

    # ============================================================
    #  PDF
    # ============================================================
    def _logo_png(self):
        ico = os.path.join(self.ruta_otros, "Logo_SIMEX-RACSO.ico")
        if not os.path.exists(ico):
            return None
        try:
            img = Image.open(ico).convert("RGBA")
            img.thumbnail((400, 400), Image.LANCZOS)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            img.save(tmp.name, "PNG")
            return tmp.name
        except (OSError, ValueError) as e:
            print(f"[aviso] No pude convertir el logo a PNG: {e}",
                  file=sys.stderr)
            return None

    def _grafica_temp(self, panel):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        panel.fig.savefig(tmp.name, dpi=150, bbox_inches="tight",
                          facecolor=COLORES["graph_bg"])
        return tmp.name

    def generar_pdf(self):
        sel = {
            "mc_pc":   (self.chk_mc_pc_tabla.get(),
                        self.chk_mc_pc_grafica.get()),
            "col_pc":  (self.chk_col_pc_tabla.get(),
                        self.chk_col_pc_grafica.get()),
            "mc_rpi":  (self.chk_mc_rpi_tabla.get(),
                        self.chk_mc_rpi_grafica.get()),
            "col_rpi": (self.chk_col_rpi_tabla.get(),
                        self.chk_col_rpi_grafica.get()),
            "sim_pc":  (self.chk_sim_pc_tabla.get(),
                        self.chk_sim_pc_grafica.get()),
            "sim_rpi": (self.chk_sim_rpi_tabla.get(),
                        self.chk_sim_rpi_grafica.get()),
        }
        if not any(any(v) for v in sel.values()):
            messagebox.showwarning("Sin selección",
                "Marca al menos una sección para el PDF.")
            return
        try:
            pdf = FPDF()
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.add_page()

            logo = self._logo_png()
            if logo:
                pdf.image(logo, x=90, y=10, w=30)
                pdf.ln(35)
            else:
                pdf.ln(10)

            pdf.set_font("Arial", "B", 22)
            pdf.set_text_color(122, 31, 31)
            pdf.cell(0, 12, txt="SIMEX-RACSO", ln=True, align='C')

            pdf.set_text_color(60, 60, 60)
            pdf.set_font("Arial", "I", 11)
            pdf.cell(0, 6,
                     txt=("Simulador de eventos de colisión con "
                          "clúster de bajo costo"),
                     ln=True, align='C')

            pdf.set_text_color(120, 120, 120)
            pdf.set_font("Arial", "", 9)
            pdf.cell(0, 5,
                     txt="Oscar Pablo Morales Zuñiga  ·  BUAP / UVEG",
                     ln=True, align='C')
            pdf.cell(0, 5,
                     txt=f"Fecha: "
                         f"{datetime.now().strftime('%Y-%m-%d %H:%M')}",
                     ln=True, align='C')
            pdf.ln(8)
            pdf.set_text_color(0, 0, 0)

            if any(sel["mc_pc"]):
                self._pdf_seccion(pdf, "1. Hilos Local (Monte Carlo)",
                                  self.hilos_mc, self.tiempos_mc,
                                  tabla=sel["mc_pc"][0],
                                  grafica=(self._grafica_temp(self.panel_mc_pc)
                                           if sel["mc_pc"][1] else None))
            if any(sel["col_pc"]):
                self._pdf_seccion(pdf, "2. Validación cinemática (Local)",
                                  self.hilos_col, self.tiempos_col,
                                  tabla=sel["col_pc"][0],
                                  grafica=(self._grafica_temp(self.panel_col_pc)
                                           if sel["col_pc"][1] else None))
            if any(sel["mc_rpi"]):
                self._pdf_seccion(pdf, "3. Hilos Raspberry Pi",
                                  self.hilos_rpi_mc, self.tiempos_rpi_mc,
                                  tabla=sel["mc_rpi"][0],
                                  grafica=(self._grafica_temp(self.panel_mc_rpi)
                                           if sel["mc_rpi"][1] else None))
            if any(sel["col_rpi"]):
                self._pdf_seccion(pdf,
                                  "4. Validación cinemática (Clúster RPi)",
                                  self.hilos_rpi_col, self.tiempos_rpi_col,
                                  tabla=sel["col_rpi"][0],
                                  grafica=(self._grafica_temp(self.panel_col_rpi)
                                           if sel["col_rpi"][1] else None))
            if any(sel["sim_pc"]):
                self._pdf_seccion(pdf, "5. Simulación Monte Carlo Local",
                                  self.hilos_sim, self.tiempos_sim,
                                  tabla=sel["sim_pc"][0],
                                  grafica=(self._grafica_temp(self.panel_sim_pc)
                                           if sel["sim_pc"][1] else None))
            if any(sel["sim_rpi"]):
                self._pdf_seccion(pdf,
                                  "6. Simulación Monte Carlo (Clúster RPi)",
                                  self.hilos_rpi_sim, self.tiempos_rpi_sim,
                                  tabla=sel["sim_rpi"][0],
                                  grafica=(self._grafica_temp(self.panel_sim_rpi)
                                           if sel["sim_rpi"][1] else None))

            ruta = os.path.join(self.ruta_windows,
                                "Documento_Evaluacion_Cluster.pdf")
            pdf.output(ruta)
            abrir_archivo(ruta)
            messagebox.showinfo("Listo", "PDF generado.")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _pdf_seccion(self, pdf, titulo, hilos, tiempos,
                     tabla=False, grafica=None):
        if not tiempos:
            return
        pdf.set_font("Arial", "B", 12)
        pdf.set_text_color(122, 31, 31)
        pdf.cell(0, 8, txt=titulo, ln=True)
        pdf.set_text_color(0, 0, 0)

        if tabla:
            pdf.set_font("Arial", "B", 9)
            pdf.cell(40, 6, "Hilos o nodos", border=1, align='C')
            pdf.cell(50, 6, "Tiempo (s)", border=1, align='C')
            pdf.cell(50, 6, "Speedup", border=1, align='C')
            pdf.ln()
            pdf.set_font("Arial", "", 9)
            for h, t in zip(hilos, tiempos):
                if t > 0:
                    s = tiempos[0] / t
                    pdf.cell(40, 6, str(h), border=1, align='C')
                    pdf.cell(50, 6, f"{t:.4f}", border=1, align='C')
                    pdf.cell(50, 6, f"{s:.2f}x", border=1, align='C')
                    pdf.ln()
            pdf.ln(3)

        if grafica and os.path.exists(grafica):
            pdf.image(grafica, w=170)
            pdf.ln(3)
        pdf.ln(5)


if __name__ == "__main__":
    root = tk.Tk()
    app = ClusterControlApp(root)
    root.mainloop()