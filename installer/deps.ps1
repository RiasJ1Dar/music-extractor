# Music Extractor dependencies (installer\deps.ps1), run hidden by the setup wizard (MusicExtractor-Setup.exe);
# the wizard is only the UI, this script does the work. Developers can run it directly from a checkout.
# Downloads and installs into this folder: ffmpeg (winget, or a portable build into
# tools\ffmpeg), uv (tools\uv), Python 3.11 + .venv, PyTorch 2.6 (CUDA 12.4 if an NVIDIA GPU is present,
# else CPU), Demucs, audio-separator, PySide6 and the default separation models.
# Safe to run again: finished steps are skipped and interrupted downloads resume from uv's cache.
#   -FromSetup   progress markers for the wizard (##STEP n / ##INFO text), no shortcut
#   -Cpu         force the CPU build of PyTorch
#   -AllModels   download every offered model now (otherwise they download on first use)
#   -InstallDownloader  install Downloader (github.com/RiasJ1Dar/downloader) if missing; every big
#                file (PyTorch, models, uv, ffmpeg) is then fetched with it: segmented, resumable
#   -NoShortcut  do not create the desktop shortcut
param([switch]$FromSetup, [switch]$Cpu, [switch]$AllModels, [switch]$InstallDownloader, [switch]$NoShortcut)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'          # Invoke-WebRequest is very slow with a progress bar
[Console]::OutputEncoding = [Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$env:PYTHONIOENCODING = 'utf-8'
$root = Split-Path $PSScriptRoot -Parent            # app folder (this script lives in installer\)
$tools = Join-Path $root 'tools'
$py = Join-Path $root '.venv\Scripts\python.exe'
$logFile = Join-Path $root 'install.log'
Set-Content $logFile "Music Extractor install $(Get-Date -Format s)" -Encoding UTF8

function Log($t) { Add-Content $logFile $t -Encoding UTF8 }
function Step($n, $t) {
    Log "== $n/7 $t"
    if ($FromSetup) { Write-Output "##STEP $n" } else { Write-Host "`n== $n/7 $t" -ForegroundColor Cyan }
}
function Info($t) { Log $t; if ($FromSetup) { Write-Output "##INFO $t" } else { Write-Host $t } }
function Ok($t) { Log "OK $t"; if (-not $FromSetup) { Write-Host "OK  $t" -ForegroundColor Green } }
function Run {
    # native command: full output goes to the log, printable lines are shown as progress detail
    $exe = $args[0]; $rest = @($args | Select-Object -Skip 1)
    $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'   # stderr lines are not errors
    & $exe @rest 2>&1 | ForEach-Object {
        $line = "$_"; Log $line
        if ($line -match '^[\x20-\x7E]{3,}$') {
            if ($FromSetup) { Write-Output "##INFO $($line.Substring(0, [Math]::Min(120, $line.Length)))" } else { Write-Host $line }
        }
    }
    $code = $LASTEXITCODE; $ErrorActionPreference = $old
    if ($code -ne 0) { throw "command failed ($code): $exe $($rest -join ' ')" }
}
function Find-DL {
    $c = Get-Command dl -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $p = "$env:LOCALAPPDATA\Programs\Downloader\dl.exe"
    if (Test-Path $p) { return $p }
    return $null
}
function Download($url, $out) {
    # finished = file present, no Downloader state left, our .ok marker written
    if ((Test-Path $out) -and (Test-Path "$out.ok") -and -not (Test-Path "$out.dlpart")) { Info "already downloaded: $(Split-Path $out -Leaf)"; return }
    $dl = Find-DL
    Info "downloading $(Split-Path $out -Leaf)$(if ($dl) { ' (Downloader)' })"
    for ($i = 1; $i -le 3; $i++) {
        try {
            if ($dl) { Run $dl --lang en get $url -o $out }        # resumes from its own state file
            else { Invoke-WebRequest $url -OutFile $out -UseBasicParsing }
            Set-Content "$out.ok" 'ok'; return
        } catch { if ($i -eq 3) { throw }; Info "retry ${i}: $($_.Exception.Message)"; Start-Sleep 5 }
    }
}
function Find-FFmpeg {
    $c = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    foreach ($p in @("$env:LOCALAPPDATA\Microsoft\WinGet\Links\ffmpeg.exe", "$tools\ffmpeg\bin\ffmpeg.exe")) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

try {
    Step 1 'ffmpeg'
    $ff = Find-FFmpeg
    if (-not $ff -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        Info 'winget install Gyan.FFmpeg'
        $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements --silent 2>&1 | ForEach-Object { Log "$_" }
        $ErrorActionPreference = $old
        $ff = Find-FFmpeg
    }
    if (-not $ff) {
        $zip = Join-Path $env:TEMP 'musicx-ffmpeg.zip'; $tmp = Join-Path $env:TEMP 'musicx-ffmpeg'
        Download 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' $zip
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
        Expand-Archive $zip $tmp
        New-Item -ItemType Directory -Force $tools | Out-Null
        if (Test-Path "$tools\ffmpeg") { Remove-Item "$tools\ffmpeg" -Recurse -Force }
        Move-Item (Get-ChildItem $tmp -Directory | Select-Object -First 1).FullName "$tools\ffmpeg"
        Remove-Item $zip, "$zip.ok", $tmp -Recurse -Force -ErrorAction SilentlyContinue
        $ff = Find-FFmpeg
    }
    if (-not $ff) { throw 'ffmpeg could not be installed' }
    Ok "ffmpeg: $ff"

    Step 2 'Downloader, uv'
    if ($InstallDownloader -and -not (Find-DL)) {
        # latest release of github.com/RiasJ1Dar/downloader: web MSI, per-user, no UAC; checked against SHA256SUMS
        $rel = Invoke-RestMethod 'https://api.github.com/repos/RiasJ1Dar/downloader/releases/latest' -UseBasicParsing
        $msiAsset = $rel.assets | Where-Object { $_.name -like '*-web.msi' } | Select-Object -First 1
        $sumAsset = $rel.assets | Where-Object { $_.name -eq 'SHA256SUMS.txt' } | Select-Object -First 1
        if ($msiAsset) {
            $msi = Join-Path $env:TEMP $msiAsset.name
            Info "Downloader $($rel.tag_name): $($msiAsset.name)"
            Invoke-WebRequest $msiAsset.browser_download_url -OutFile $msi -UseBasicParsing
            if ($sumAsset) {
                $sums = (Invoke-WebRequest $sumAsset.browser_download_url -UseBasicParsing).Content
                $want = ($sums -split "`n" | Where-Object { $_ -match [regex]::Escape($msiAsset.name) } | ForEach-Object { ($_ -split '\s+')[0] }) | Select-Object -First 1
                $have = (Get-FileHash $msi -Algorithm SHA256).Hash
                if (-not $want -or $want.ToLower() -ne $have.ToLower()) { throw "Downloader MSI checksum mismatch" }
            }
            $p = Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /qn /norestart" -Wait -PassThru
            Remove-Item $msi -Force -ErrorAction SilentlyContinue
            if ($p.ExitCode -ne 0) { Info "Downloader install exit code $($p.ExitCode), continuing without it" }
        }
    }
    $dlExe = Find-DL
    Ok $(if ($dlExe) { "Downloader: $dlExe" } else { 'Downloader not installed: built-in downloads' })
    $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uv -and (Test-Path "$tools\uv\uv.exe")) { $uv = "$tools\uv\uv.exe" }
    if (-not $uv) {
        $zip = Join-Path $env:TEMP 'musicx-uv.zip'
        Download 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' $zip
        New-Item -ItemType Directory -Force "$tools\uv" | Out-Null
        Expand-Archive $zip "$tools\uv" -Force
        Remove-Item $zip, "$zip.ok" -Force -ErrorAction SilentlyContinue
        $uv = Get-ChildItem "$tools\uv" -Recurse -Filter uv.exe | Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $uv) { throw 'uv could not be installed' }
    Ok "uv: $uv"

    Step 3 'Python 3.11'
    if (-not (Test-Path $py)) { Run $uv venv --python 3.11 (Join-Path $root '.venv') }
    Ok (& $py --version)

    Step 4 'PyTorch'
    $nvidia = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'NVIDIA' }
    $gpu = [bool]$nvidia -and -not $Cpu
    $index = if ($gpu) { 'https://download.pytorch.org/whl/cu124' } else { 'https://download.pytorch.org/whl/cpu' }
    Info $(if ($gpu) { "GPU: $($nvidia[0].Name) - CUDA build" } else { 'CPU build' })
    $flavor = if ($gpu) { 'cu124' } else { 'cpu' }
    $pins = @("torch==2.6.0+$flavor", "torchaudio==2.6.0+$flavor", "torchvision==0.21.0+$flavor")
    $have = ''
    try { $ErrorActionPreference = 'Continue'; $have = (& $py -c "import torch; print(torch.__version__)" 2>&1 | Select-Object -Last 1) } catch {} finally { $ErrorActionPreference = 'Stop' }
    if ($have -ne "2.6.0+$flavor" -and -not (Find-DL)) {
        # no Downloader: uv fetches the wheels itself (one stream, retries; finished wheels stay in its cache)
        Run $uv pip install --python $py @pins --index-url $index
    }
    elseif ($have -ne "2.6.0+$flavor") {
        # with Downloader the wheels (2.4 GB for CUDA) are fetched segmented and resumable, then installed locally
        $wheels = Join-Path $tools 'wheels'; New-Item -ItemType Directory -Force $wheels | Out-Null
        foreach ($w in @("torch-2.6.0%2B$flavor", "torchaudio-2.6.0%2B$flavor", "torchvision-0.21.0%2B$flavor")) {
            $file = "$w-cp311-cp311-win_amd64.whl"
            Download "$index/$file" (Join-Path $wheels ($file -replace '%2B', '+'))
        }
        Run $uv pip install --python $py --find-links $wheels @pins
        Remove-Item $wheels -Recurse -Force                     # installed: 2.4 GB no longer needed
    }
    Ok 'PyTorch'

    Step 5 'packages'
    Run $uv pip install --python $py -r (Join-Path $root 'requirements.txt')
    if ($gpu) { Run $uv pip install --python $py "audio-separator[gpu]==0.47.0" "onnxruntime-gpu==1.22.0" }   # 1.22 = CUDA 12, as in PyTorch
    else { Run $uv pip install --python $py "audio-separator[cpu]==0.47.0" }
    Ok 'packages'

    Step 6 'models'
    $which = if ($AllModels) { 'all' } else { 'default' }
    Run $py -m musicx.core.models --download $which
    Ok 'models'

    Step 7 'check'
    Run $py -c "import torch, demucs, audio_separator, PySide6, soundfile, scipy; print('CUDA:', torch.cuda.is_available())"
    if (-not $FromSetup -and -not $NoShortcut) {
        $ws = New-Object -ComObject WScript.Shell
        $lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Music Extractor.lnk'))
        $lnk.TargetPath = Join-Path $root '.venv\Scripts\pythonw.exe'
        $lnk.Arguments = '-m musicx.gui.app'
        $lnk.WorkingDirectory = $root
        $lnk.IconLocation = Join-Path $root 'musicx\gui\icon.ico'
        $lnk.Save()
        Ok 'desktop shortcut'
    }
    Log 'DONE'
    if (-not $FromSetup) { Write-Host "`nВстановлення завершено." -ForegroundColor Green }
    exit 0
} catch {
    Log "ERROR: $($_.Exception.Message)"
    if ($FromSetup) { Write-Output "##INFO ERROR: $($_.Exception.Message)" } else { Write-Host "`nПОМИЛКА: $($_.Exception.Message)`nЖурнал: $logFile" -ForegroundColor Red }
    exit 1
}
