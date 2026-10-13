"""French prose of the method section, for the French report.

Same blocks, steps, parameters and glossary as the Spanish prose in metodologia.py,
reading the same figures: thresholds from `config` and `alerts`, counts from the series,
hectares from the measured masks. Nothing here is computed; only written.

It is written for the French report, so the country-specific passages are the French
ones (the sea clipping, Hub'Eau, Camargue and Dombes as examples).
"""
from __future__ import annotations

from . import alerts as al
from . import config
from .i18n import d as _d_i18n, n as _n_i18n, p as _p_i18n
from .metodologia import (EJEMPLO_GRANDE, GLOSARIO_COMUN, SITES, _datos)
from .sites import site_text

L = "fr"


def _n(v: float) -> str:
    return _n_i18n(v, L)


def _d(v: float, nd: int = 1) -> str:
    return _d_i18n(v, L, nd)


def _p(x: float) -> str:
    return _p_i18n(x, L)


def _num(v: float) -> str:
    """A parameter value with French decimal comma: 0,22. Integers stay as they are."""
    if float(v).is_integer():
        return _n(v)
    return f"{v}".replace(".", ",")


def _nom(site) -> str:
    return site_text(site, L)[0]


MOTIVO_GRUESO = {
    "ES": "elle demande 4,5 scènes par date et, à 20 m, le calcul prenait quatre fois plus "
          "de temps sans changer le résultat",
    "FR": "il faut quatre scènes par date sur un delta dont les étangs sont bien plus grands "
          "que le pixel : mesurée à la même date aux deux résolutions, la différence est de "
          "huit pour mille",
}
PARPADEO = {
    "ES": "à Tablas de Daimiel, la surface détectée est passée de 80 à 200 puis à 26 ha en dix "
          "jours d'août 2026, avec des images en couleurs naturelles presque identiques",
    "FR": "le Lac du Der est un réservoir de 3 500 ha d'eau libre et fait la même chose : le "
          "1er juin 2021 il mesurait 3 662 ha, le 16 il en mesurait 1 428 et le 26 il revenait "
          "à 3 341, par ciel dégagé les trois fois ; or un réservoir ne perd pas 2 200 ha en "
          "deux semaines pour les retrouver en une",
}
RAMSAR = {
    "ES": "L'Espagne compte 76 sites inscrits ; les six de ce rapport en font partie.",
    "FR": "Les six zones humides de ce rapport se trouvent dans des sites inscrits par la "
          "France.",
}


def _phrases(results: dict | None, pais: str) -> dict:
    """The French sentences built from the raw figures of `_datos`."""
    d = _datos(results, pais)
    m, n_fechas, n_ok = d["mask"], d["n_fechas"], d["n_ok"]
    grande, denom = d["grande_site"], d["denom_site"]
    return {
        "crs": d["crs"],
        "grande": _nom(grande),
        "grande_res": d["grande_res"],
        "grande_motivo": MOTIVO_GRUESO[pais],
        "parpadeo": PARPADEO[pais],
        "recuento": (f"Sur les {_n(n_fechas)} dates téléchargées, seules {_n(n_ok)} — soit "
                     f"{_p(n_ok / n_fechas)} — arrivent dans le rapport. Ce filtre représente"
                     if n_fechas else
                     "Près de la moitié des dates téléchargées sont écartées. Ce filtre représente"),
        "denom_ha": (f"Celui de {_nom(denom)} couvre {_n(m['site_ha'])} ha, dont" if m else
                     f"Celui de {_nom(denom)} comprend"),
        "campo_donde": ("qui n'existe aujourd'hui qu'à Doñana" if pais == "ES" else
                        "qui reste à brancher en France"),
        "denom_inundable": (
            f"À {_nom(denom)}, elle couvre {_n(m['floodable_ha'])} ha, soit "
            f"{_d(m['site_ha'] / m['floodable_ha'])} fois moins que le polygone" if m else
            f"À {_nom(denom)}, la zone inondable est bien plus petite que le polygone"),
    }


def _bloques(results: dict | None = None, pais: str = "FR") -> list[tuple[str, str, str]]:
    """(anchor, title, HTML) of each block, in French."""
    d = _phrases(results, pais)
    return [
        ("que-se-mide", "Ce qui est mesuré, et avec quoi", f"""
<p>Tous les quelques jours, un satellite passe au-dessus de la zone humide et mesure la lumière que
renvoie le sol dans plusieurs couleurs. L'eau a une signature très reconnaissable : elle réfléchit
un peu dans le vert et absorbe presque tout l'infrarouge. En comparant ces deux bandes pixel par
pixel, on sait quelle partie de la zone humide est en eau, et en comptant les pixels on obtient des
hectares.</p>
<p>Chaque date valide donne trois mesures :</p>
<ul>
  <li><b>Eau libre</b> : pixels dont le MNDWI dépasse le seuil du jour <em>et</em> dont le NDVI est
      &lt; {_num(config.NDVI_OPEN_WATER)}. La lame d'eau dégagée, sans plantes émergentes.</li>
  <li><b>Végétation inondée</b> : même seuil d'eau, mais NDVI au-dessus. Roselière, marisque,
      rizière : de l'eau qui ne se voit pas comme un miroir mais qui compte pour l'hydrologie. C'est
      elle qui, à Doñana, est corrélée à la hauteur d'eau mesurée sur le terrain.</li>
  <li><b>Turbidité (NDTI) et chlorophylle (NDCI)</b>, moyennées sur l'eau libre seulement : sur la
      végétation, elles ne voudraient rien dire.</li>
</ul>
<p>Tout est découpé avec le polygone officiel Natura 2000 de la zone humide, reprojeté en
{d['crs']} pour travailler en mètres, et échantillonné à {config.RESOLUTION_M} m de pixel ;
{d['grande']} à {d['grande_res']} m, car {d['grande_motivo']}.</p>"""),

        ("umbral", "Le seuil d'eau est calculé à chaque date", f"""
<p>La recette classique est « il y a de l'eau là où MNDWI &gt; 0 ». Elle n'est pas utilisée ici,
car elle mesurait systématiquement {_p(0.15)} d'eau en moins que la propre classification de
l'ESA. La raison est physique : sur une rive peu profonde et turbide, le fond se voit à travers
l'eau, et l'indice reste sous zéro sans cesser d'être de l'eau. Un seuil fixe ne peut pas non plus
valoir la même chose dans un étang salé à fond clair et dans un marais chargé de matière
organique.</p>
<p>Le seuil est donc calculé <b>à chaque date et pour chaque zone humide</b> par la méthode
d'<b>Otsu</b> sur l'histogramme du jour : on cherche la valeur qui sépare le mieux les deux
populations — eau et non-eau — que contient l'image. Avec trois précautions, car une méthode
automatique peut aussi se tromper :</p>
<ul>
  <li>il faut au moins {_n(config.OTSU_MIN_PIXELS)} pixels valides pour que l'histogramme ait un
      sens ;</li>
  <li>la <b>séparabilité</b> (la part de la variance totale qu'explique la partition) doit atteindre
      {_num(config.OTSU_MIN_SEPARABILITY)} : en dessous, il n'y a pas deux groupes mais un seul, et
      le couper reviendrait à inventer une rive ;</li>
  <li>le seuil doit tomber entre {_num(config.OTSU_THR_MIN)} et {_num(config.OTSU_THR_MAX)} ; en
      dehors de cette plage, ce ne peut pas être une rive.</li>
</ul>
<p>Si l'une des trois conditions échoue, la date utilise le seuil de secours
{_num(config.MNDWI_WATER)} plutôt qu'une valeur absurde.</p>"""),

        ("calidad", "Quelles dates sont écartées, et pourquoi", f"""
<p>{d['recuento']} la moitié du travail : un voile nuageux ou une correction atmosphérique ratée ne
produisent pas une erreur, ils produisent un chiffre plausible et faux, ce qui est bien pire.</p>
<ul>
  <li><b>Nuages</b> : les classes de nuage de la SCL, plus tout pixel dont le bleu dépasse
      {_num(config.BLUE_CLOUD)}. Si plus de {_p(config.MAX_CLOUD_FRAC)} de la zone humide reste
      sous les nuages, la date est écartée.</li>
  <li><b>Couverture</b> : les scènes du jour doivent couvrir au moins {_p(config.MIN_COVERAGE)}
      de la zone humide. Mesurer la moitié d'un étang et la comparer à l'étang entier donnerait une
      fausse baisse brutale.</li>
  <li><b>Brume</b> : si le bleu médian du site dépasse {_num(config.BLUE_HAZE)}, la date est
      écartée. La SCL ne signale pas les brumes légères, qui pouvaient tripler l'eau détectée.</li>
  <li><b>Désaccord avec l'ESA</b> : si la SCL voit beaucoup d'eau et que l'indice en détecte moins
      de {_p(config.SCL_CHECK_RATIO)}, quelque chose ne va pas dans cette scène.</li>
  <li><b>Forme du spectre sur l'eau</b> : sur de l'eau réelle, le proche infrarouge reste sous le
      vert. Si le rapport infrarouge/vert dépasse {_num(config.WATER_NIR_GREEN_MAX)}, ou si le bleu
      s'effondre sous {_num(config.WATER_BLUE_FLOOR)}, c'est la correction atmosphérique qui a
      échoué, pas l'étang.</li>
</ul>
<p>Ce dernier contrôle a innocenté un faux coupable. Le satellite le plus récent, Sentinel-2C,
semblait avoir un biais propre ; en réalité le problème venait de corrections atmosphériques
ratées, qui touchent les trois satellites et sont seulement bien plus fréquentes sur lui. En
détecter la cause a permis de continuer à l'utiliser au lieu de l'exclure.</p>"""),

        ("denominador", "À quoi la surface mesurée est comparée", f"""
<p>Dire « la zone humide est à 16 % de sa surface » appelle une question : 16 % de quoi ? Le
polygone Natura 2000 est une limite <em>administrative</em>. {d['denom_ha']} des terrains qui ne
sont jamais inondés : mesurer la lame d'eau par rapport à ce total ne dit rien
d'hydrologique.</p>
<p>Le dénominateur de ce rapport est donc la <b>zone inondable</b> : la partie qui a été en eau au
moins une fois en neuf ans, mesurée en cumulant les dates valides des mois humides.
{d['denom_inundable']}. La méthode se valide elle-même : pour la Mar Menor, une lagune côtière
espagnole, elle donne 99 % de zone inondable et 96 % d'eau permanente, exactement ce que l'on
doit obtenir pour une lagune.</p>"""),

        ("mar", "Pourquoi la mer est découpée", """
<p>Le polygone Natura 2000 d'une zone humide littorale ne s'arrête pas au rivage : celui de la
Camargue avance de plusieurs kilomètres dans la Méditerranée. La première mesure sans découpage a
donné 56 542 ha « d'eau », dont les deux tiers étaient de la pleine mer. Cette erreur ne se dilue
pas : elle apparaît identique à toutes les dates, si bien qu'un étang en train de s'assécher
ressemblerait à une zone humide parfaitement stable.</p>
<p>La bande marine est retirée avec le trait de côte d'OpenStreetMap, qui contient aussi de quoi
savoir de quel côté se trouve la mer, car ses tracés sont orientés avec la terre à gauche. On coupe
le polygone le long de la côte et on sonde les deux côtés de chaque tronçon : la pièce qui cumule
les sondes du côté marin est la mer. Comparer les deux côtés n'est pas un luxe : avec un seul,
cinq tronçons mal orientés suffisaient pour prendre pour de la mer les 77 000 ha du delta entier.
En Camargue, on retire ainsi 36 169 ha.</p>
<p>Le satellite ne tranche pas, même si la mer est en eau à toutes les dates : un étang permanent
ou le lit d'un fleuve le sont aussi, et les séparer par contiguïté échoue justement là où cela
compte, dans les étangs littoraux qu'un canal d'un pixel de large relie à la mer.</p>
<p>Pour la même raison, il n'y a pas ici de zones humides à marée. Dans la baie du
Mont-Saint-Michel, la baie de Somme, le golfe du Morbihan ou le bassin d'Arcachon, la surface en
eau à l'heure du passage du satellite dépend de la marée, qui à cette heure-là parcourt tout son
cycle en quinze jours. Les mesurer exige une prédiction de marée ; d'ici là, une alerte
d'assèchement n'y dirait rien.</p>""")
        if pais == "FR" else ("", "", ""),

        ("alertas", "Comment se décide une alerte", f"""
<p>Aucune alerte ne compare à une valeur absolue ni à une autre zone humide. Toutes comparent chaque
zone humide <b>à elle-même, à la même époque de l'année</b> : on prend la fenêtre de
±{al.SEASON_WINDOW_DAYS} jours autour de la date dans <em>les années précédentes</em>, et il faut au
moins {al.MIN_HISTORY} observations pour qu'une référence existe. La « valeur actuelle » est la
médiane des observations valides des {al.CURRENT_DAYS} derniers jours, et non la dernière, qui
pourrait tomber un mauvais jour.</p>
<ul>
  <li><b>Assèchement</b> (grave) : la surface actuelle sous le 10e centile de ce que donne cette
      zone humide à ces dates. Ne s'applique pas aux lagunes en eau permanente.</li>
  <li><b>Baisse brutale</b> : une chute sous {_p(al.DROP_RATIO)} de la médiane des
      {al.RECENT_DAYS} jours précédents <em>et en plus</em> pire que
      {_p(1 - al.DROP_SEASON_PERCENTILE)} des baisses enregistrées à la même époque les années
      précédentes. Sans cette seconde condition, la règle signalait que les étangs s'assèchent en
      été, ce qu'ils font depuis toujours : à Gallocanta, en Espagne, elle se déclenchait sur 100
      de ses 494 dates.</li>
  <li><b>Eutrophisation</b> : le <b>pic</b> de NDCI de la fenêtre actuelle au-dessus du
      {100 * al.BLOOM_PERCENTILE:.0f}e centile des pics de cette époque les années précédentes,
      plus une marge de {_num(al.BLOOM_MARGIN)}. Le pic et non la médiane, car une efflorescence
      algale dure quelques jours et une médiane sur trois semaines l'efface.</li>
  <li><b>Turbidité</b> : NDTI actuel au-dessus du 90e centile de l'époque.</li>
</ul>
<p>Le seuil d'efflorescence algale de la littérature (NDCI &gt; {_num(config.NDCI_BLOOM)}, environ
40 mg/m³ de chlorophylle a) ne sert pas à déclencher sur ces étangs : il a été calibré sur des eaux
continentales profondes, et dans des lagunes peu profondes, salées et à fond clair l'indice est
gonflé en permanence — Gallocanta le dépasse à chacune de ses 494 dates. Il sert ici seulement à
<em>graduer</em> la gravité : une alerte qui dépasse aussi ce seuil est élevée ; sinon, moyenne.</p>"""),

        ("campo", "La confrontation avec des mesures de terrain", """
<p>Le satellite dit quelle surface est inondée, pas pourquoi. En France cette donnée existe et elle
est ouverte, ce qui est plus qu'on n'en peut dire de l'Espagne : <b>Hub'Eau</b> publie le niveau des
nappes et le débit des rivières sans clé ni inscription, et la Camargue compte 38 piézomètres,
certains suivis depuis 1983. Ce n'est pas encore branché sur ce rapport : c'est la prochaine étape,
et c'est précisément la pièce qui, côté espagnol, n'existe qu'à Doñana.</p>"""),

        ("limites", "Ce que ce rapport ne peut pas dire", f"""
<ul>
  <li><b>NDTI et NDCI sont des indicateurs non calibrés</b> : il n'y a derrière ni unités de
      turbidité ni milligrammes de chlorophylle, et leurs seuils de littérature ne sont pas
      transposables à des étangs peu profonds et salés. Ils servent à comparer une zone humide à
      elle-même, pas à donner des valeurs absolues.</li>
  <li><b>L'eau libre et la végétation inondée s'échangent</b> : {d['parpadeo']}. Ces hectares ne
      disparaissent pas, ils changent de classe : l'eau sous la végétation, ou avec des algues en
      surface, reste au bord du seuil et passe dans la végétation inondée, qui est la ligne en
      pointillés du graphique. Quand l'une baisse pendant que l'autre monte, rien ne s'est passé
      dans la zone humide. C'est pour cela que les alertes utilisent la médiane des dernières
      observations et non la dernière, et que les hectares d'une date isolée ne sont une mesure
      fiable de rien.</li>
  <li><b>Neuf ans, c'est peu</b> : la référence commence en juillet 2017, avec l'archive
      Sentinel-2 L2A. Une année exceptionnelle peut sembler normale s'il n'y en a que huit pour la
      comparer.</li>
  <li><b>Attention aux années incomplètes</b> : 2017 commence en juillet et l'année en cours
      s'arrête aujourd'hui, donc leurs moyennes annuelles ne couvrent pas la même période que les
      autres. En les comparant telles quelles, une fausse tendance à l'eutrophisation est apparue
      dans la Mar Menor, qui n'était que l'automne pas encore arrivé. Les alertes évitent ce piège
      parce qu'elles comparent toujours à la même époque de l'année.</li>
  <li><b>Il ne distingue pas la cause</b> : un assèchement peut venir d'un manque de pluie, d'une
      nappe qui a baissé ou d'une vanne ouverte. Le satellite ne le sait pas ; c'est le rôle de la
      confrontation avec les mesures de terrain, {d['campo_donde']}.</li>
  <li><b>Une alerte est un avertissement, pas un diagnostic</b> : elle dit que quelque chose
      s'écarte de ce que cette zone humide fait d'habitude à ces dates, et qu'il vaut la peine que
      quelqu'un aille voir.</li>
</ul>"""),
    ]


# The common glossary entries, in French, in the same order as GLOSARIO_COMUN.
GLOSARIO_COMUN_FR: list[tuple[str, str, str]] = [
    ("Sentinel-2", "—",
     "Paire de satellites de l'Agence spatiale européenne, plus un troisième depuis 2024, qui "
     "photographient toute l'Europe tous les 5 jours avec des pixels de 10 à 20 m. Ils sont "
     "gratuits et publics, et tout ce que contient ce rapport en vient."),
    ("L2A", "Level-2A",
     "Le niveau de traitement de l'image : réflectance <em>de surface</em>, l'atmosphère déjà "
     "retirée. Le niveau précédent, L1C, mesure ce que voit le satellite ; le L2A cherche à mesurer "
     "ce qu'il y a au sol. Cette correction échoue parfois, ce qui donne du travail (voir plus "
     "bas)."),
    ("bande", "—",
     "Chacune des couleurs que le satellite mesure séparément, y compris celles que l'œil ne voit "
     "pas. Six sont utilisées ici : bleu (B02), vert (B03), rouge (B04), limite du rouge (B05), "
     "proche infrarouge (B08) et infrarouge à ondes courtes (B11)."),
    ("NIR / SWIR", "Near Infrared / Short-Wave Infrared",
     "Proche infrarouge et infrarouge à ondes courtes. Ils comptent parce que l'eau les absorbe "
     "presque entièrement : sur une image infrarouge, un étang est une tache noire, et c'est là "
     "l'astuce pour le mesurer."),
    ("indice normalisé", "—",
     "Tous les indices qui suivent se calculent de la même façon, (A − B)/(A + B) avec deux "
     "bandes, et valent donc toujours entre −1 et +1. Diviser par la somme annule une bonne part "
     "de l'effet de la lumière : le même site donne une valeur proche en été et en hiver, ou avec "
     "le soleil plus bas."),
    ("MNDWI", "Modified Normalized Difference Water Index",
     "(vert − SWIR)/(vert + SWIR). C'est le détecteur d'eau : il monte là où il y a une lame d'eau "
     "et baisse sur le sol et la végétation. C'est de lui que sort la surface inondée."),
    ("NDWI", "Normalized Difference Water Index",
     "(vert − NIR)/(vert + NIR). Le grand frère du précédent, utilisé ici seulement comme "
     "contrôle : si les deux divergent beaucoup, la date est suspecte."),
    ("NDVI", "Normalized Difference Vegetation Index",
     "(NIR − rouge)/(NIR + rouge). Mesure la quantité de végétation vivante. Il sert à séparer "
     "l'eau libre de la roselière, du marisque ou de la rizière, qui sont aussi inondés mais "
     "paraissent verts vus d'en haut."),
    ("NDTI", "Normalized Difference Turbidity Index",
     "(rouge − vert)/(rouge + vert). Indicateur de turbidité : l'eau chargée de sédiments en "
     "suspension réfléchit davantage dans le rouge. Il ne donne pas d'unités ; il indique si cette "
     "date est plus trouble que d'habitude."),
    ("NDCI", "Normalized Difference Chlorophyll Index",
     "(limite du rouge − rouge)/(limite du rouge + rouge). Indicateur de chlorophylle, c'est-à-dire "
     "de la quantité d'algues dans l'eau. C'est l'indice qui sert à surveiller "
     "l'eutrophisation."),
    ("SCL", "Scene Classification Layer",
     "Une carte que l'ESA publie avec l'image et qui étiquette chaque pixel : nuage, ombre, eau, "
     "végétation, sol… Elle sert à écarter les dates nuageuses et, en plus, de second avis "
     "indépendant sur l'emplacement de l'eau."),
    ("Otsu", "—",
     "Méthode de 1979 (Nobuyuki Otsu) pour choisir le seuil qui partage le mieux un histogramme en "
     "deux groupes. Ici, elle décide, à chaque date et pour chaque zone humide, à partir de quelle "
     "valeur de MNDWI un pixel compte comme eau."),
    ("STAC / COG", "SpatioTemporal Asset Catalog / Cloud-Optimized GeoTIFF",
     "Le catalogue où l'on cherche les images et le format dans lequel elles sont stockées. Le COG "
     "permet de ne télécharger que la découpe de la zone humide au lieu de la scène entière, qui "
     "pèse des centaines de mégaoctets."),
]
# A term added to the Spanish glossary and forgotten here would silently drop out of
# the French report.
assert len(GLOSARIO_COMUN_FR) == len(GLOSARIO_COMUN), "French glossary out of step"

GLOSARIO_MEDIDA_FR: list[tuple[str, str, str]] = [
    ("ha", "hectare",
     "10 000 m², une parcelle de 100 × 100 m. À 20 m de pixel, chaque pixel fait 0,04 ha ; à "
     "40 m, 0,16 ha."),
    ("centile", "—",
     "Le 10e centile d'une série est la valeur sous laquelle ne tombent que 10 % des "
     "observations. Presque toutes les alertes de ce rapport sont définies ainsi : non par un seuil "
     "absolu, mais en se demandant si la valeur d'aujourd'hui figure parmi les plus basses de ce "
     "que cette zone humide donne d'habitude à ces dates."),
]


def _glosario(pais: str = "FR") -> list[tuple[str, str, str]]:
    """The glossary of the French report, in French."""
    ejemplo = next(s.natura_codes[0] for s in SITES.values() if s.country == pais)
    crs = config.CRS_BY_COUNTRY[pais]
    del_pais = [
        ("Natura 2000", "—",
         "Le réseau européen d'espaces protégés. Ses polygones officiels sont le contour qui sert "
         f"à découper chaque zone humide ; chaque site a un code comme {ejemplo}."),
        ("Ramsar", "—",
         "Convention internationale de 1971 sur les zones humides d'importance internationale. "
         + RAMSAR[pais]),
        (f"{config.CRS_NAMES[crs]} / {crs}", "—",
         "Le système de coordonnées dans lequel on travaille : des mètres, pas des degrés. C'est ce "
         "qui permet de parler d'hectares avec rigueur, car chaque pixel mesure la même chose sur "
         "toute l'image."),
    ]
    return GLOSARIO_COMUN_FR + del_pais + GLOSARIO_MEDIDA_FR


def _pasos(results: dict | None, pais: str) -> str:
    """Numbered steps from the source to the figure, with the parameters in force."""
    d = _phrases(results, pais)
    mar = (" Pour les zones humides littorales, la bande marine est d'abord retirée avec le trait "
           "de côte d'OpenStreetMap." if pais == "FR" else "")
    pasos = [
        f"<b>Image.</b> Tous les quelques jours, les images Sentinel-2 L2A sont téléchargées depuis "
        f"le catalogue public Earth Search, découpées au polygone Natura 2000 de chaque zone humide "
        f"et passées en mètres ({d['crs']}) avec un pixel de {config.RESOLUTION_M} m ; "
        f"{d['grande']} à {d['grande_res']} m.{mar}",
        f"<b>Dates valides.</b> La date est écartée si plus de {_p(config.MAX_CLOUD_FRAC)} de la "
        f"zone humide est sous les nuages, si les scènes en couvrent moins de "
        f"{_p(config.MIN_COVERAGE)}, s'il y a de la brume ou si le spectre de l'eau trahit une "
        f"correction atmosphérique ratée.",
        f"<b>Eau.</b> Un pixel est de l'eau si son MNDWI dépasse le seuil calculé ce jour-là par la "
        f"méthode d'Otsu (ou {_num(config.MNDWI_WATER)} si l'histogramme ne le permet pas). C'est "
        f"de l'eau libre si en plus son NDVI est inférieur à {_num(config.NDVI_OPEN_WATER)}, et de "
        f"la végétation inondée sinon. En comptant les pixels, on obtient les hectares.",
        "<b>Turbidité et chlorophylle.</b> NDTI et NDCI sont moyennés sur l'eau libre seulement.",
        f"<b>Valeur actuelle.</b> La médiane des dates valides des {al.CURRENT_DAYS} derniers "
        f"jours, s'il y en a au moins {al.CURRENT_MIN_OBS} ; sinon, la dernière.",
        f"<b>Comparaison historique.</b> On compare aux dates des années précédentes situées à "
        f"±{al.SEASON_WINDOW_DAYS} jours du même jour de l'année, depuis juillet 2017, avec au "
        f"moins {al.MIN_HISTORY} observations de référence.",
        f"<b>Alerte.</b> Assèchement si la surface passe sous le 10e centile de l'époque ; baisse "
        f"brutale si elle tombe sous {_p(al.DROP_RATIO)} de la médiane des {al.RECENT_DAYS} jours "
        f"précédents et si, en outre, la chute est plus forte que "
        f"{_p(1 - al.DROP_SEASON_PERCENTILE)} des chutes de l'époque ; eutrophisation si le pic de NDCI dépasse le "
        f"{100 * al.BLOOM_PERCENTILE:.0f}e centile des pics de l'époque plus "
        f"{_num(al.BLOOM_MARGIN)} ; turbidité si le NDTI dépasse son 90e centile.",
    ]
    return '<ol class="pasos">' + "".join(f"<li>{x}</li>" for x in pasos) + "</ol>"


def _parametros(pais: str) -> str:
    """table.params with every threshold, read from `config` and `alerts`."""
    gruesos = [_nom(SITES[s]) for s in config.RESOLUTION_BY_SITE if SITES[s].country == pais]
    filas = [
        ("Pixel de travail", f"{config.RESOLUTION_M} m",
         f"{', '.join(gruesos)} à {config.RESOLUTION_BY_SITE[EJEMPLO_GRANDE[pais]]} m."
         if gruesos else ""),
        ("Nuages sur la zone humide", f"≤ {_p(config.MAX_CLOUD_FRAC)}",
         "Au-delà, la date est écartée."),
        ("Couverture des scènes", f"≥ {_p(config.MIN_COVERAGE)}",
         "En deçà, la date est écartée."),
        ("Bleu de nuage", f"&gt; {_num(config.BLUE_CLOUD)}",
         "Réflectance bleue à partir de laquelle un pixel est un nuage."),
        ("Bleu de brume", f"&gt; {_num(config.BLUE_HAZE)}",
         "Bleu médian de la zone humide ; la date est écartée."),
        ("Infrarouge / vert sur l'eau", f"&gt; {_num(config.WATER_NIR_GREEN_MAX)}",
         "Correction atmosphérique ratée ; la date est écartée."),
        ("Otsu : pixels valides", f"≥ {_num(config.OTSU_MIN_PIXELS)}",
         "Pour pouvoir calculer le seuil du jour."),
        ("Otsu : séparabilité", f"≥ {_num(config.OTSU_MIN_SEPARABILITY)}",
         "Sinon, il n'y a pas deux groupes à séparer."),
        ("Otsu : plage du seuil", f"{_num(config.OTSU_THR_MIN)} à {_num(config.OTSU_THR_MAX)}",
         "En dehors, on utilise le seuil de secours."),
        ("Seuil de secours du MNDWI", _num(config.MNDWI_WATER),
         "Quand l'une des trois conditions échoue."),
        ("NDVI de l'eau libre", f"&lt; {_num(config.NDVI_OPEN_WATER)}",
         "Au-dessus, végétation inondée."),
        ("Valeur actuelle", f"{al.CURRENT_DAYS} jours", "Médiane des dates valides."),
        ("Fenêtre saisonnière", f"±{al.SEASON_WINDOW_DAYS} jours", "Les années précédentes."),
        ("Référence minimale", f"{al.MIN_HISTORY} obs.", "Sans elles, pas d'alerte relative."),
        ("Assèchement", "10e centile", "De la surface en eau à cette époque."),
        ("Baisse brutale", f"&lt; {_p(al.DROP_RATIO)}",
         f"De la médiane des {al.RECENT_DAYS} jours précédents, et pire que "
         f"{_p(1 - al.DROP_SEASON_PERCENTILE)} des baisses de l'époque."),
        ("Eutrophisation",
         f"{100 * al.BLOOM_PERCENTILE:.0f}e centile + {_num(al.BLOOM_MARGIN)}",
         f"Du pic de NDCI ; élevée si elle dépasse aussi {_num(config.NDCI_BLOOM)}."),
        ("Turbidité", "90e centile", "Du NDTI à cette époque."),
    ]
    return ('<table class="params"><thead><tr><th>Paramètre</th><th class="num">Valeur</th>'
            "<th>Usage</th></tr></thead><tbody>"
            + "".join(f'<tr><td>{a}</td><td class="num">{b}</td><td>{c}</td></tr>'
                      for a, b, c in filas)
            + "</tbody></table>")


VALIDACION = {
    "ES": "<p>La surface inondée que mesure le satellite à Doñana (eau libre plus végétation "
          "inondée) a été comparée à la hauteur d'eau mesurée sur le terrain dans le marais par "
          "l'ICTS-Doñana : la corrélation est de 0,94 (Pearson ; 0,78 de Spearman) sur les 168 "
          "dates de 2022 à 2026 où les deux mesures existent, et la surface augmente à chaque "
          "palier de hauteur d'eau.</p>",
    "FR": "<p><b>En attente.</b> Il n'y a pas encore de confrontation avec des mesures de "
          "terrain : Hub'Eau publie le niveau des nappes et le débit des rivières sans clé, mais "
          "ce n'est pas encore branché. La seule vérification faite est un ordre de grandeur : la "
          "mer retirée, la Camargue mesure 20 538 ha d'eau le 2 septembre 2026, soit ce "
          "qu'additionnent le Vaccarès, les étangs inférieurs et les salins de Giraud.</p>",
}

PROSA_FR = {
    "bloques": _bloques,
    "glosario": _glosario,
    "pasos": _pasos,
    "parametros": _parametros,
    "validacion": VALIDACION,
    "titulos": {"seccion": "Méthode de calcul", "parametros": "Paramètres",
                "validacion": "Validation", "detalle": "En détail :",
                "glosario": "Glossaire des sigles"},
}
