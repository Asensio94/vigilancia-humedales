# Publica el informe mas reciente en GitHub Pages.
#
# La rama gh-pages es huerfana y guarda un solo commit, que se reemplaza en cada
# publicacion: cada informe pesa unos 2 MB porque lleva las graficas incrustadas en
# base64, y acumularlos en el historial haria crecer el repositorio sin necesidad.
# De ahi el --amend y el push forzado, que aqui son deliberados y no un accidente.
param([string]$Informe)

$ErrorActionPreference = "Stop"
$raiz = $PSScriptRoot
if (-not $Informe) {
    $Informe = (Get-ChildItem "$raiz\output\informe_*.html" | Sort-Object Name -Descending)[0].FullName
}
$fecha = [regex]::Match((Split-Path $Informe -Leaf), '\d{4}-\d{2}-\d{2}').Value
$alertas = "$raiz\output\alertas_$fecha.json"
$arbol = "$env:TEMP\vigilancia-humedales-gh-pages"

if (Test-Path $arbol) { git -C $raiz worktree remove --force $arbol }
git -C $raiz worktree add $arbol gh-pages
Copy-Item $Informe "$arbol\index.html" -Force
if (Test-Path $alertas) { Copy-Item $alertas "$arbol\alertas.json" -Force }
git -C $arbol add index.html alertas.json
git -C $arbol commit --amend -m "Informe del $fecha"
git -C $arbol push --force origin gh-pages
git -C $raiz worktree remove --force $arbol

Write-Host "Publicado: https://asensio94.github.io/vigilancia-humedales/"
