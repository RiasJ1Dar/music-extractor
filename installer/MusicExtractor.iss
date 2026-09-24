; Music Extractor — Windows setup wizard (Inno Setup 6.3+).
; Build:  ISCC.exe installer\MusicExtractor.iss   ->  dist\MusicExtractor-Setup-<version>.exe
; The wizard copies the app, then runs installer\deps.ps1, which downloads ffmpeg, Python 3.11, PyTorch
; (CUDA or CPU), Demucs / audio-separator and the default models, reporting progress back here.

#define AppName "Music Extractor"
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define AppURL "https://github.com/RiasJ1Dar/music-extractor"

[Setup]
AppId={{6B2E7C1A-3F4D-4E8B-9A51-2C7D0E9F4B12}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=RiasJ1Dar
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
DefaultDirName={localappdata}\Programs\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=MusicExtractor-Setup-{#AppVersion}
SetupIconFile=..\musicx\gui\icon.ico
UninstallDisplayIcon={app}\musicx\gui\icon.ico
UninstallDisplayName={#AppName}
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110
ShowLanguageDialog=auto
; per-user install without elevation: Windows' RedirectionGuard (on by default since Inno Setup 6.5) only
; protects elevated installers, and it would stop uv from following its own Python junctions
RedirectionGuard=no

[Languages]
Name: "uk"; MessagesFile: "compiler:Languages\Ukrainian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
uk.TaskCpu=Версія для процесора (якщо немає відеокарти NVIDIA; працює в кілька разів повільніше)
en.TaskCpu=CPU-only version (no NVIDIA graphics card; several times slower)
uk.TaskAllModels=Завантажити всі моделі зараз (~3 ГБ; інакше кожна завантажиться при першому використанні)
en.TaskAllModels=Download all models now (~3 GB; otherwise each downloads on first use)
uk.TaskDownloader=Встановити Downloader — менеджер завантажень із докачуванням; ним качатимуться PyTorch і моделі
en.TaskDownloader=Install Downloader — a download manager with resume; PyTorch and the models are fetched with it
uk.Group=Додатково:
en.Group=Additional options:
uk.Step0=Підготовка…
en.Step0=Preparing…
uk.Step1=Крок 1 з 7: ffmpeg
en.Step1=Step 1 of 7: ffmpeg
uk.Step2=Крок 2 з 7: Downloader і менеджер пакетів uv
en.Step2=Step 2 of 7: Downloader and the uv package manager
uk.Step3=Крок 3 з 7: Python 3.11
en.Step3=Step 3 of 7: Python 3.11
uk.Step4=Крок 4 з 7: PyTorch — найдовший крок, ~2.4 ГБ (при обриві продовжиться з того ж місця)
en.Step4=Step 4 of 7: PyTorch — the longest step, ~2.4 GB (resumes if interrupted)
uk.Step5=Крок 5 з 7: Demucs, audio-separator, PySide6
en.Step5=Step 5 of 7: Demucs, audio-separator, PySide6
uk.Step6=Крок 6 з 7: завантаження моделей
en.Step6=Step 6 of 7: downloading models
uk.Step7=Крок 7 з 7: перевірка
en.Step7=Step 7 of 7: checking the installation
uk.Failed=Не вдалося встановити залежності.%n%nДеталі в журналі:%n%1%n%nПеревірте інтернет і запустіть інсталятор ще раз — уже завантажене не завантажуватиметься повторно.
en.Failed=Installing the dependencies failed.%n%nSee the log:%n%1%n%nCheck your internet connection and run the setup again — finished steps are skipped.
uk.RemoveData=Видалити також кеш розділень і завантажені моделі (%1)?
en.RemoveData=Also delete the separation cache and downloaded models (%1)?

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "downloader"; Description: "{cm:TaskDownloader}"; GroupDescription: "{cm:Group}"; Check: DownloaderMissing
Name: "cpu"; Description: "{cm:TaskCpu}"; GroupDescription: "{cm:Group}"; Flags: unchecked
Name: "allmodels"; Description: "{cm:TaskAllModels}"; GroupDescription: "{cm:Group}"; Flags: unchecked

[Files]
Source: "..\musicx\*"; DestDir: "{app}\musicx"; Excludes: "__pycache__,*.pyc"; Flags: recursesubdirs ignoreversion
Source: "deps.ps1"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m musicx.gui.app"; WorkingDir: "{app}"; IconFilename: "{app}\musicx\gui\icon.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m musicx.gui.app"; WorkingDir: "{app}"; IconFilename: "{app}\musicx\gui\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m musicx.gui.app"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\musicx"
Type: files; Name: "{app}\install.log"
Type: filesandordirs; Name: "{app}\installer"
Type: dirifempty; Name: "{app}"

[Code]
function DownloaderMissing: Boolean;
begin
  Result := not FileExists(ExpandConstant('{localappdata}\Programs\Downloader\dl.exe'));
end;

var
  DepsOk: Boolean;
  StepCount: Integer;

function StepText(N: Integer): String;
begin
  Result := CustomMessage('Step' + IntToStr(N));
end;

procedure OnLog(const S: String; const Error, FirstLine: Boolean);
var
  Line: String;
  N: Integer;
begin
  Line := Trim(S);
  if Copy(Line, 1, 7) = '##STEP ' then
  begin
    N := StrToIntDef(Copy(Line, 8, 1), 0);
    WizardForm.StatusLabel.Caption := StepText(N);
    WizardForm.FilenameLabel.Caption := '';
    WizardForm.ProgressGauge.Position := WizardForm.ProgressGauge.Min +
      (WizardForm.ProgressGauge.Max - WizardForm.ProgressGauge.Min) * (N - 1) div StepCount;
  end
  else if Copy(Line, 1, 7) = '##INFO ' then
    WizardForm.FilenameLabel.Caption := Copy(Line, 8, 200);
end;

procedure InstallDependencies;
var
  Params: String;
  Code: Integer;
begin
  StepCount := 7;
  WizardForm.StatusLabel.Caption := CustomMessage('Step0');
  WizardForm.ProgressGauge.Style := npbstNormal;
  WizardForm.ProgressGauge.Position := WizardForm.ProgressGauge.Min;
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\installer\deps.ps1') + '" -FromSetup';
  if WizardIsTaskSelected('cpu') then Params := Params + ' -Cpu';
  if WizardIsTaskSelected('allmodels') then Params := Params + ' -AllModels';
  if DownloaderMissing and WizardIsTaskSelected('downloader') then Params := Params + ' -InstallDownloader';
  DepsOk := ExecAndLogOutput(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params,
    ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code, @OnLog) and (Code = 0);
  WizardForm.ProgressGauge.Position := WizardForm.ProgressGauge.Max;
  if not DepsOk then
    SuppressibleMsgBox(FmtMessage(CustomMessage('Failed'), [ExpandConstant('{app}\install.log')]), mbCriticalError, MB_OK, IDOK);
end;

function GetCustomSetupExitCode: Integer;
begin
  { silent installs can see the failure too }
  if DepsOk then Result := 0 else Result := 1;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then InstallDependencies;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  { without the dependencies the "launch now" checkbox would only produce an error }
  if (CurPageID = wpFinished) and not DepsOk then
    WizardForm.RunList.Visible := False;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{localappdata}\MusicExtractor');
    if DirExists(Data) and not UninstallSilent then
      if MsgBox(FmtMessage(CustomMessage('RemoveData'), [Data]), mbConfirmation, MB_YESNO) = IDYES then
        DelTree(Data, True, True, True);
  end;
end;
