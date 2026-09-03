# Publica los informes mas recientes en GitHub Pages.
#
# La rama gh-pages es huerfana y guarda un solo commit, que se reemplaza en cada
# publicacion: cada informe pesa unos 2,5 MB porque lleva las graficas y las imagenes
# incrustadas en base64, y acumularlos en el historial haria crecer el repositorio sin
# necesidad. De ahi el --amend y el push forzado, que aqui son deliberados y no un
# accidente.
#
# Hay una pagina por pais. Espana se queda en index.html porque es la URL que ya estaba
# publicada y la que hay enlazada fuera; Francia va en france.html.
param([string]$Fecha)

$ErrorActionPreference = "Stop"
$raiz = $PSScriptRoot
if (-not $Fecha) {
    $ultimo = (Get-ChildItem "$raiz\output\informe_*_*.html" | Sort-Object Name -Descending)[0].Name
    $Fecha = [regex]::Match($ultimo, '\d{4}-\d{2}-\d{2}').Value
}
$arbol = "$env:TEMP\vigilancia-humedales-gh-pages"

if (Test-Path $arbol) { git -C $raiz worktree remove --force $arbol }
git -C $raiz worktree add $arbol gh-pages

# (fichero de salida, fichero publicado). Se copia lo que exista: si solo se ha
# regenerado un pais, el otro se queda con la version que ya estaba publicada.
$paginas = @(
    @("informe_ES_$Fecha.html", "index.html"),
    @("informe_FR_$Fecha.html", "france.html"),
    @("alertas_$Fecha.json",    "alertas.json"),
    @("alertas_ES_$Fecha.json", "alertas_es.json"),
    @("alertas_FR_$Fecha.json", "alertas_fr.json")
)
foreach ($par in $paginas) {
    $origen = "$raiz\output\$($par[0])"
    if (Test-Path $origen) {
        Copy-Item $origen "$arbol\$($par[1])" -Force
        git -C $arbol add $par[1]
    } else {
        Write-Host "Sin $($par[0]); se deja la version publicada de $($par[1])."
    }
}
git -C $arbol commit --amend -m "Informe del $Fecha"
git -C $arbol push --force origin gh-pages
git -C $raiz worktree remove --force $arbol

Write-Host "Publicado:"
Write-Host "  Espana:  https://asensio94.github.io/vigilancia-humedales/"
Write-Host "  Francia: https://asensio94.github.io/vigilancia-humedales/france.html"
