"""Corpus di riferimento per il RAG (§83).

Un documento di corpus (giurisprudenza/normativa) viene spezzato in frammenti,
ciascuno con il proprio embedding (pgvector), per la ricerca semantica a supporto
dell'analisi. È locale: niente lascia la piattaforma.
"""
from django.conf import settings
from django.db import models
from pgvector.django import VectorField


class DocumentoCorpus(models.Model):
    class Stato(models.TextChoices):
        IN_ATTESA = "in_attesa", "In attesa"
        IN_CORSO = "in_corso", "Indicizzazione in corso"
        COMPLETATO = "completato", "Completato"
        ERRORE = "errore", "Errore"

    titolo = models.CharField(max_length=255)
    fonte = models.CharField(max_length=512, blank=True)
    categoria = models.CharField(max_length=120, blank=True)
    testo = models.TextField()
    stato = models.CharField(
        max_length=16, choices=Stato.choices, default=Stato.IN_ATTESA
    )
    errore = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.titolo


class FrammentoCorpus(models.Model):
    documento = models.ForeignKey(
        DocumentoCorpus, on_delete=models.CASCADE, related_name="frammenti"
    )
    ordine = models.PositiveIntegerField(default=0)
    testo = models.TextField()
    embedding = VectorField(dimensions=settings.EMBEDDING_DIM, null=True, blank=True)

    class Meta:
        ordering = ["documento_id", "ordine"]

    def __str__(self) -> str:
        return f"{self.documento_id}#{self.ordine}"
