"""Recommend a BUSCO / compleasm lineage (odb10) for a genome.

BUSCO and compleasm both score completeness against a *lineage* dataset
(``bacteria_odb10``, ``fungi_odb10``, ``insecta_odb10`` …).  Picking the right
one matters — too broad wastes the signal, too narrow may not exist for the
organism — but users often don't know the exact odb10 name.  This maps a
species class + a free-text taxon hint (``"fungus"``, ``"insect"``, ``"human"``)
to the most specific sensible lineage, and tells the caller whether bioflow
already catalogues that dataset (``bioflow db fetch``) or it must be pulled with
``busco --download``.
"""
from __future__ import annotations

# Free-text taxon keyword → odb10 lineage.  Ordered most-specific first so a
# longer/narrower match wins (checked by descending keyword length below).
_TAXON_LINEAGE: dict[str, str] = {
    # prokaryotes
    "archaea": "archaea_odb10",
    "bacteria": "bacteria_odb10", "bacterium": "bacteria_odb10",
    "cyanobacteria": "cyanobacteria_odb10",
    "proteobacteria": "proteobacteria_odb10",
    "firmicutes": "firmicutes_odb10", "actinobacteria": "actinobacteria_phylum_odb10",
    # fungi
    "saccharomyces": "saccharomycetes_odb10", "yeast": "saccharomycetes_odb10",
    "ascomycota": "ascomycota_odb10", "ascomycete": "ascomycota_odb10",
    "basidiomycota": "basidiomycota_odb10", "basidiomycete": "basidiomycota_odb10",
    "microsporidia": "microsporidia_odb10",
    "fungi": "fungi_odb10", "fungus": "fungi_odb10", "fungal": "fungi_odb10",
    "mold": "fungi_odb10", "mushroom": "basidiomycota_odb10",
    # plants
    "monocot": "liliopsida_odb10", "liliopsida": "liliopsida_odb10",
    "eudicot": "eudicots_odb10", "dicot": "eudicots_odb10",
    "land plant": "embryophyta_odb10", "embryophyta": "embryophyta_odb10",
    "plant": "viridiplantae_odb10", "viridiplantae": "viridiplantae_odb10",
    "green algae": "chlorophyta_odb10", "algae": "eukaryota_odb10",
    # invertebrates / arthropods
    "drosophila": "diptera_odb10", "fruit fly": "diptera_odb10",
    "mosquito": "diptera_odb10", "fly": "diptera_odb10", "diptera": "diptera_odb10",
    "bee": "hymenoptera_odb10", "wasp": "hymenoptera_odb10",
    "ant": "hymenoptera_odb10", "hymenoptera": "hymenoptera_odb10",
    "moth": "lepidoptera_odb10", "butterfly": "lepidoptera_odb10",
    "lepidoptera": "lepidoptera_odb10",
    "beetle": "endopterygota_odb10", "coleoptera": "endopterygota_odb10",
    "hemiptera": "hemiptera_odb10", "aphid": "hemiptera_odb10",
    "insect": "insecta_odb10", "insecta": "insecta_odb10",
    "arachnid": "arachnida_odb10", "spider": "arachnida_odb10", "mite": "arachnida_odb10",
    "crustacean": "arthropoda_odb10", "arthropod": "arthropoda_odb10",
    "nematode": "nematoda_odb10", "roundworm": "nematoda_odb10",
    "mollusc": "mollusca_odb10", "snail": "mollusca_odb10", "bivalve": "mollusca_odb10",
    # vertebrates
    "primate": "primates_odb10", "human": "primates_odb10", "monkey": "primates_odb10",
    "rodent": "glires_odb10", "mouse": "glires_odb10", "rat": "glires_odb10",
    "mammal": "mammalia_odb10",
    "bird": "aves_odb10", "aves": "aves_odb10",
    "reptile": "sauropsida_odb10", "snake": "sauropsida_odb10", "lizard": "sauropsida_odb10",
    "amphibian": "tetrapoda_odb10", "frog": "tetrapoda_odb10",
    "tetrapod": "tetrapoda_odb10",
    "fish": "actinopterygii_odb10", "teleost": "actinopterygii_odb10",
    "actinopterygii": "actinopterygii_odb10",
    "vertebrate": "vertebrata_odb10",
    # broad fallbacks
    "metazoa": "metazoa_odb10", "animal": "metazoa_odb10",
    "protist": "eukaryota_odb10", "eukaryote": "eukaryota_odb10",
}

# Species class (as used across bioflow's registry) → default lineage.
_SPECIES_DEFAULT: dict[str, str] = {
    "prokaryote": "bacteria_odb10",
    "eukaryote": "eukaryota_odb10",
    "eukaryote_small": "eukaryota_odb10",
    "any": "eukaryota_odb10",
}

# odb10 lineages bioflow already catalogues (bioflow db fetch <key>).
_CATALOGUED: dict[str, str] = {
    "bacteria_odb10": "busco_bacteria",
    "insecta_odb10": "busco_insecta",
    "vertebrata_odb10": "busco_vertebrata",
}


def recommend_lineage(
    species: str | None = None, taxon: str | None = None
) -> dict:
    """Return a lineage recommendation.

    Parameters
    ----------
    species:
        bioflow species class (``prokaryote`` / ``eukaryote`` / …).
    taxon:
        Optional free-text hint (``"baker's yeast"``, ``"insect"``, ``"human"``).
        A more specific taxon wins over the species default.

    Returns a dict with ``lineage`` (odb10 name), ``source`` (how it was chosen),
    ``db_key`` (bioflow DB catalog key, or None), and ``how`` (a one-line hint on
    obtaining the dataset).
    """
    lineage = None
    source = ""
    if taxon:
        t = taxon.lower()
        for kw in sorted(_TAXON_LINEAGE, key=len, reverse=True):
            if kw in t:
                lineage, source = _TAXON_LINEAGE[kw], f"taxon match '{kw}'"
                break
    if lineage is None:
        lineage = _SPECIES_DEFAULT.get((species or "").lower(), "eukaryota_odb10")
        source = f"species default ({species or 'unknown'})"

    db_key = _CATALOGUED.get(lineage)
    how = (f"bioflow db fetch {db_key}" if db_key
           else f"busco --download {lineage}  (auto-downloaded on first run)")
    return {"lineage": lineage, "source": source, "db_key": db_key, "how": how}
