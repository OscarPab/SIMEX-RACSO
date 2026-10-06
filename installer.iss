; ============================================================
;  SIMEX-RACSO - Instalador Windows
;  Oscar Pablo Morales Zuñiga - BUAP / UVEG
; ============================================================

#define MiApp "SIMEX-RACSO"
#define MiVersion "1.0.0.0"
#define MiAutor "Oscar Pablo Morales Zuñiga"
#define MiEmail "oscaripingui@gmail.com"
#define MiExe "SIMEX-RACSO.exe"

; Carpeta del proyecto detectada automáticamente desde la ubicación
; del .iss. Ya no hay rutas absolutas hardcodeadas: si mueves el
; proyecto de carpeta, el .iss sigue funcionando sin editar nada.
#define CarpetaProyecto AddBackslash(SourcePath)
#define CarpetaSalida CarpetaProyecto + "installer_output"

[Setup]
AppId={{8D2F4A19-3B7C-4E51-9A2D-6C1F5E8B0D43}
AppName={#MiApp}
AppVersion={#MiVersion}
AppVerName={#MiApp} {#MiVersion}
AppPublisher={#MiAutor}
AppPublisherURL=https://github.com/oscaripingui
AppSupportURL=mailto:{#MiEmail}
AppUpdatesURL=https://github.com/oscaripingui
DefaultDirName={autopf}\{#MiApp}
DefaultGroupName={#MiApp}
DisableProgramGroupPage=yes
LicenseFile={#CarpetaProyecto}LICENSE.txt
OutputDir={#CarpetaSalida}
OutputBaseFilename=SIMEX-RACSO-Setup-{#MiVersion}
SetupIconFile={#CarpetaProyecto}otros\Logo_SIMEX-RACSO.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UninstallDisplayIcon={app}\{#MiExe}
UninstallDisplayName={#MiApp}
VersionInfoVersion={#MiVersion}
VersionInfoCompany={#MiAutor}
VersionInfoDescription=Simulador de eventos de colisión con clúster MPI
VersionInfoCopyright=© 2026 {#MiAutor}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
; El ejecutable principal (contiene el bundle de PyInstaller con
; otros/, el CSV y todos los recursos embebidos en su interior).
Source: "{#CarpetaProyecto}dist\{#MiExe}"; DestDir: "{app}"; Flags: ignoreversion

; Copia visible de otros/ para el usuario (logos + CSV editables).
; Nota: son ~14 MB que ya están embebidos en el .exe; esto es
; solo para que el usuario los vea en disco si quiere tocarlos.
Source: "{#CarpetaProyecto}otros\*"; DestDir: "{app}\otros"; Flags: ignoreversion recursesubdirs createallsubdirs

; El CSV principal en la raíz (por si el usuario lo quiere ahí a mano).
Source: "{#CarpetaProyecto}datos_cern.csv"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; LICENSE y README visibles en la carpeta de instalación.
Source: "{#CarpetaProyecto}LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#CarpetaProyecto}README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MiApp}"; Filename: "{app}\{#MiExe}"
Name: "{group}\Desinstalar {#MiApp}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MiApp}"; Filename: "{app}\{#MiExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MiExe}"; Description: "Ejecutar {#MiApp} ahora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Artefactos que la app escribe en la carpeta de instalación.
; Los borro todos para no dejar basura tras desinstalar.

; Datos y caché
Type: files; Name: "{app}\datos_cern.csv"
Type: files; Name: "{app}\cern_cache.dat"

; Resultados de los kernels
Type: files; Name: "{app}\histograma_colision.csv"
Type: files; Name: "{app}\estadisticas_colision.csv"
Type: files; Name: "{app}\animacion_eventos.csv"
Type: files; Name: "{app}\simulacion_eventos.csv"

; PDF generado
Type: files; Name: "{app}\Documento_Evaluacion_Cluster.pdf"

; Fuentes C++ que la app escribe en disco al arrancar
Type: files; Name: "{app}\mc_core.cpp"
Type: files; Name: "{app}\colision_core.cpp"
Type: files; Name: "{app}\anim_core.cpp"
Type: files; Name: "{app}\sim_core.cpp"

; Binarios compilados con mpicxx
Type: files; Name: "{app}\mc_core"
Type: files; Name: "{app}\colision_core"
Type: files; Name: "{app}\anim_core"
Type: files; Name: "{app}\sim_core"

; Carpeta de recursos copiada (logos + CSV + fuentes)
Type: filesandordirs; Name: "{app}\otros"

[Code]
{ ---------------------------------------------------------------
  Verificaciones previas a la instalación:
  1. Windows 10 o superior.
  2. Avisar si WSL no está presente, porque la app no funciona
     sin WSL2 + Ubuntu + OpenMPI. No bloqueo la instalación pero
     aviso, así el usuario sabe por qué la app no arranca bien.
  --------------------------------------------------------------- }

function InitializeSetup(): Boolean;
var
  Version: TWindowsVersion;
  WSLPath1, WSLPath2: String;
  WSLExiste: Boolean;
begin
  { 1. Verificar Windows 10+ }
  GetWindowsVersionEx(Version);
  if Version.Major < 10 then
  begin
    MsgBox('SIMEX-RACSO requiere Windows 10 o superior.' + #13#10 +
           'Tu versión actual no es compatible.',
           mbError, MB_OK);
    Result := False;
    Exit;
  end;

  { 2. Comprobar si WSL está instalado. En Windows de 64 bits el
       wsl.exe vive en System32; en WOW64 vive en Sysnative.
       Pruebo ambos por si acaso. }
  WSLPath1 := ExpandConstant('{sys}\wsl.exe');
  WSLPath2 := ExpandConstant('{sysnative}\wsl.exe');
  WSLExiste := FileExists(WSLPath1) or FileExists(WSLPath2);

  if not WSLExiste then
  begin
    if MsgBox(
      'No detecté WSL en este equipo.' + #13#10 + #13#10 +
      'SIMEX-RACSO necesita WSL2 con Ubuntu y OpenMPI instalados ' +
      'para compilar y ejecutar los kernels C++.' + #13#10 + #13#10 +
      'Revisa el README.md para los pasos de instalación.' + #13#10 + #13#10 +
      '¿Deseas continuar con la instalación de todos modos?',
      mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := False;
      Exit;
    end;
  end;

  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    { Aquí puedo hacer tareas post-instalación si hacen falta
      (por ejemplo, crear carpetas adicionales o escribir un
      archivo de configuración inicial). }
  end;
end;