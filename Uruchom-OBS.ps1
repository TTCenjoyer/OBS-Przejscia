# Launcher OBS dla turnieju TTC: instaluje/aktualizuje dodatki i uruchamia OBS z gotowymi ustawieniami.
# Ustawienia są w launcher.json obok tego pliku (powstaje przy pierwszym uruchomieniu).
param([switch]$NoStart, [switch]$DryRun)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$configPath = Join-Path $root 'launcher.json'

function Info($text) { Write-Host $text }
function Warn($text) { Write-Host ('UWAGA: ' + $text) -ForegroundColor Yellow }
function Fail($text) { Write-Host ('BŁĄD: ' + $text) -ForegroundColor Red; exit 1 }

# --- ustawienia ---
$defaults = [ordered]@{
    server     = 'https://turniej.kirsiak.com'   # adres serwera turnieju; na turnieju np. http://192.168.1.10:3000
    obsPath    = ''                              # pusty = znajdź obs64.exe automatycznie
    collection = ''                              # nazwa kolekcji scen do uruchomienia; pusty = ostatnia użyta
    microphone = ''                              # dokładna nazwa mikrofonu wyciszanego na przerwie; pusty = wykryj
    intro      = ''                              # plik audio odtwarzany raz na przerwie
    loop       = ''                              # plik audio w pętli na przerwie
}
if (-not (Test-Path $configPath)) {
    [IO.File]::WriteAllText($configPath, ($defaults | ConvertTo-Json) + "`n", (New-Object Text.UTF8Encoding($false)))
    Info "Utworzono launcher.json z ustawieniami domyślnymi: $configPath"
}
$config = Get-Content -Raw -Encoding UTF8 $configPath | ConvertFrom-Json
foreach ($key in $defaults.Keys) {
    if ($null -eq $config.$key) { $config | Add-Member -NotePropertyName $key -NotePropertyValue $defaults[$key] }
}
$server = ([string]$config.server).Trim().TrimEnd('/')
if ($server -notmatch '^https?://') { Fail "Adres serwera w launcher.json musi zaczynać się od http:// albo https:// (jest: '$server')." }

# --- OBS ---
$obs = [string]$config.obsPath
if (-not $obs) {
    $candidates = @(
        (Join-Path $env:ProgramFiles 'obs-studio\bin\64bit\obs64.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'obs-studio\bin\64bit\obs64.exe')
    )
    $obs = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}
if (-not $obs -or -not (Test-Path $obs)) { Fail 'Nie znaleziono obs64.exe. Wpisz jego pełną ścieżkę w launcher.json (obsPath).' }

# --- serwer turnieju (tylko ostrzeżenie: OBS i tak się uruchomi) ---
try {
    $null = Invoke-WebRequest -Uri ($server + '/api/time') -UseBasicParsing -TimeoutSec 6
    Info "Serwer turnieju odpowiada: $server"
} catch {
    Warn "Serwer turnieju ($server) nie odpowiada. OBS się uruchomi, a skrypt połączy się, gdy serwer ruszy."
}

# --- instalacja dodatków ---
if (Get-Process -Name obs64 -ErrorAction SilentlyContinue) {
    Fail 'OBS jest już uruchomiony. Zamknij go i uruchom launcher ponownie (konfiguracja jest zmieniana tylko przy zamkniętym OBS).'
}
$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { Fail 'Nie znaleziono Pythona (polecenie py). Zainstaluj 64-bitowy Python 3.12.' }
$installArgs = @('-3.12', (Join-Path $root 'install.py'), '--tournament-server', $server, '--skip-dependencies')
if ($config.collection) { $installArgs += @('--collection', ([string]$config.collection)) }
if ($config.microphone) { $installArgs += @('--microphone', ([string]$config.microphone)) }
if ($config.intro) { $installArgs += @('--intro', ([string]$config.intro)) }
if ($config.loop) { $installArgs += @('--loop', ([string]$config.loop)) }
if ($DryRun) {
    Info ('[DryRun] py ' + ($installArgs -join ' '))
    Info "[DryRun] OBS: $obs"
    exit 0
}
Info 'Instaluję / aktualizuję dodatki OBS…'
& py @installArgs
if ($LASTEXITCODE -ne 0) { Fail "Instalator zakończył się błędem ($LASTEXITCODE). OBS nie został uruchomiony." }

# --- start OBS ---
if ($NoStart) { Info 'Gotowe (bez uruchamiania OBS).'; exit 0 }
$obsArgs = @('--disable-shutdown-check')
if ($config.collection) { $obsArgs += @('--collection', ([string]$config.collection)) }
Info "Uruchamiam OBS: $obs"
Start-Process -FilePath $obs -WorkingDirectory (Split-Path $obs) -ArgumentList $obsArgs
Info 'Gotowe. Scena „Turniej — Ekran” pojawi się po załadowaniu OBS; skrypt przełączy sceny przy przerwie.'
