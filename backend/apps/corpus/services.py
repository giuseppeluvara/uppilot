"""Servizi RAG: indicizzazione e ricerca semantica (§83)."""
from __future__ import annotations

from pgvector.django import CosineDistance

from ai.interfaces import EmbeddingBackend

from .models import DocumentoCorpus, FrammentoCorpus

_MAX_CHUNK = 800


def chunk(testo: str) -> list[str]:
    """Spezza il testo in frammenti gestibili (per paragrafi, con cap di lunghezza)."""
    frammenti: list[str] = []
    for blocco in testo.split("\n\n"):
        b = blocco.strip()
        while len(b) > _MAX_CHUNK:
            frammenti.append(b[:_MAX_CHUNK])
            b = b[_MAX_CHUNK:]
        if b:
            frammenti.append(b)
    return frammenti or [testo.strip()[:_MAX_CHUNK]]


def indicizza(documento: DocumentoCorpus, emb: EmbeddingBackend) -> int:
    """Calcola e salva gli embedding dei frammenti del documento."""
    documento.frammenti.all().delete()
    pezzi = chunk(documento.testo)
    vettori = emb.embed_many(pezzi)
    FrammentoCorpus.objects.bulk_create(
        FrammentoCorpus(documento=documento, ordine=i, testo=p, embedding=v)
        for i, (p, v) in enumerate(zip(pezzi, vettori))
    )
    return len(pezzi)


def cerca(query: str, emb: EmbeddingBackend, k: int = 5) -> list[FrammentoCorpus]:
    """Ricerca semantica: ritorna i k frammenti più vicini (distanza coseno)."""
    vettore = emb.embed(query)
    return list(
        FrammentoCorpus.objects.exclude(embedding=None)
        .annotate(distanza=CosineDistance("embedding", vettore))
        .order_by("distanza")
        .select_related("documento")[:k]
    )
