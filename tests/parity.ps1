# Runs dialog.ps1 over every fixture and writes <name>.dialog / <name>.options / <name>.fp and the
# English <name>.en.dialog / <name>.en.options next to it, byte-for-byte in the same shape as
# dialog.awk prints them (UTF-8, no BOM, "\n" endings).
param([string]$dir)
. "$dir\dialog.ps1"
$utf8 = New-Object System.Text.UTF8Encoding $false
function Save([string]$name, [object[]]$lines) {
  [IO.File]::WriteAllText("$dir\out\$name", (($lines | ForEach-Object { "$_`n" }) -join ''), $utf8)
}
foreach ($f in Get-ChildItem "$dir\fixtures\*.txt") {
  $screen = [IO.File]::ReadAllLines($f.FullName, [Text.Encoding]::UTF8)
  $DialogLang = ''
  $d = @(Format-Dialog $screen)
  Save "$($f.BaseName).dialog" $d
  Save "$($f.BaseName).options" @(Get-DialogOptions $screen)
  Save "$($f.BaseName).fp" @(Get-Fingerprint $d)
  $DialogLang = 'en'
  Save "$($f.BaseName).en.dialog" @(Format-Dialog $screen)
  Save "$($f.BaseName).en.options" @(Get-DialogOptions $screen)
}
"done"
