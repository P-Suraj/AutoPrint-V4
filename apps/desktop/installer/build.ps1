# Builds the AutoPrint installer:  powershell -ExecutionPolicy Bypass -File apps\desktop\installer\build.ps1
# Output: dist\AutoPrintSetup-<version>.exe and dist\AutoPrintSetup-<version>.exe.sha256.txt, plus a copy named
# dist\AutoPrintSetup.exe: the fixed name the shop dashboard asks GitHub Releases for in its download link.
# Needs: .NET 8 SDK, Inno Setup 6 (ISCC.exe), and the portable SumatraPDF 3.6.1 at apps\desktop\src\AutoPrint.Desktop\tools\SumatraPDF.exe
param([string]$Version = "4.0.5")
$ErrorActionPreference = "Stop"
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) { $env:PATH += ";$env:ProgramFiles\dotnet" }
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$proj = Join-Path $root "apps\desktop\src\AutoPrint.Desktop"
$stage = Join-Path $root "dist\stage"
$dist = Join-Path $root "dist"
$sumatra = Join-Path $proj "tools\SumatraPDF.exe"
$iscc = @("$env:ProgramFiles\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found. Install it: winget install JRSoftware.InnoSetup" }
if (-not (Test-Path $sumatra)) { throw "Missing $sumatra (portable SumatraPDF 3.6.1, 64-bit)" }

# Sumatra must be the genuine portable program: V3 shipped the installer under this name. The app also checks this before every print.
$expected = "719f689b34f47be8ca105ce8484948474dafde0e106bab599e4a89326070c3d0"
$actual = (Get-FileHash $sumatra -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $expected) { throw "SumatraPDF.exe hash mismatch ($actual). Not the portable 3.6.1 build." }

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force $stage | Out-Null
# Self-contained so the shop PC needs no .NET install. Not single-file, not trimmed, not packed (antivirus distrusts those).
dotnet publish $proj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=false -p:PublishTrimmed=false -p:Version=$Version -o $stage
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed" }
if (-not (Test-Path (Join-Path $stage "tools\SumatraPDF.exe"))) { throw "SumatraPDF.exe was not copied into the publish folder" }

# licence notices shipped with the program (SumatraPDF is GPL-3.0; it is a separate program, source: https://github.com/sumatrapdfreader/sumatrapdf)
$lic = Join-Path $dist "licenses"
New-Item -ItemType Directory -Force $lic | Out-Null
@"
AutoPrint (c) 2026 Suraj Pandavula.

This package includes SumatraPDF 3.6.1, a separate program licensed under the GNU General Public License v3.
SumatraPDF is (c) Krzysztof Kowalczyk and contributors. Source code and licence: https://github.com/sumatrapdfreader/sumatrapdf
AutoPrint runs SumatraPDF as a separate process to send documents to the printer. SumatraPDF is in the "tools" folder.
"@ | Set-Content (Join-Path $lic "THIRD-PARTY-NOTICES.txt") -Encoding UTF8

& $iscc "/DAppVersion=$Version" "/DSourceDir=$stage" "/DOutDir=$dist" "/DLicenseDir=$lic" "/DIconFile=$(Join-Path $proj 'app.ico')" (Join-Path $PSScriptRoot "AutoPrint.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

$exe = Join-Path $dist "AutoPrintSetup-$Version.exe"
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
"$hash  AutoPrintSetup-$Version.exe" | Set-Content "$exe.sha256.txt" -Encoding ASCII
Copy-Item $exe (Join-Path $dist "AutoPrintSetup.exe") -Force
"{0}  ({1:N1} MB)`nSHA-256: {2}" -f $exe, ((Get-Item $exe).Length / 1MB), $hash
