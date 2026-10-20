# Runs dialog.ps1 over every fixture and writes <name>.dialog / <name>.options next to it,
# byte-for-byte in the same shape as dialog.awk prints them (UTF-8, no BOM, "\n" endings).
param([string]$dir)
. "$dir\dialog.ps1"
$utf8 = New-Object System.Text.UTF8Encoding $false
foreach ($f in Get-ChildItem "$dir\fixtures\*.txt") {
  $screen = [IO.File]::ReadAllLines($f.FullName, [Text.Encoding]::UTF8)
  $d = @(Format-Dialog $screen)
  $o = @(Get-DialogOptions $screen)
  [IO.File]::WriteAllText("$dir\out\$($f.BaseName).dialog", (($d | ForEach-Object { "$_`n" }) -join ''), $utf8)
  [IO.File]::WriteAllText("$dir\out\$($f.BaseName).options", (($o | ForEach-Object { "$_`n" }) -join ''), $utf8)
  [IO.File]::WriteAllText("$dir\out\$($f.BaseName).fp", "$(Get-Fingerprint $d)`n", $utf8)
}
"done"
