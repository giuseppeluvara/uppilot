"""Grafo della conoscenza giuridica (ispirato a llm_wiki, implementazione nativa).

Nodi = concetti/istituti, riferimenti normativi e casi (fascicoli anonimizzati);
archi = relazioni suggerite tra essi. È un ausilio alla NAVIGAZIONE e alla raccolta
giurisprudenziale, non una fonte di conclusioni (§1). Costruito dal LLM locale sul
SOLO testo pseudonimizzato del corpus e dell'analisi.
"""
from django.db import models


class Nodo(models.Model):
    class Tipo(models.TextChoices):
        CONCETTO = "concetto", "Concetto/istituto"
        RIFERIMENTO = "riferimento", "Riferimento normativo"
        CASO = "caso", "Fascicolo/caso"

    tipo = models.CharField(max_length=16, choices=Tipo.choices, default=Tipo.CONCETTO)
    etichetta = models.CharField(max_length=255)
    # Chiave normalizzata: stessi concetti da documenti diversi → un solo nodo (merge).
    chiave = models.CharField(max_length=255, unique=True)
    sintesi = models.TextField(blank=True)
    documento = models.ForeignKey(
        "corpus.DocumentoCorpus",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="nodi",
    )
    lavoro = models.ForeignKey(
        "casi.Lavoro",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="nodi_grafo",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["etichetta"]

    def __str__(self) -> str:
        return self.etichetta


class Arco(models.Model):
    class Tipo(models.TextChoices):
        CITA = "cita", "Cita"
        CORRELATO = "correlato", "Correlato"
        IN_CONTRASTO = "in_contrasto", "In contrasto"
        APPLICA = "applica", "Applica"

    da = models.ForeignKey(Nodo, on_delete=models.CASCADE, related_name="archi_uscenti")
    a = models.ForeignKey(Nodo, on_delete=models.CASCADE, related_name="archi_entranti")
    tipo = models.CharField(max_length=16, choices=Tipo.choices, default=Tipo.CORRELATO)
    peso = models.FloatField(default=1.0)

    class Meta:
        unique_together = ("da", "a", "tipo")

    def __str__(self) -> str:
        return f"{self.da_id} -{self.tipo}-> {self.a_id}"


class GrafoMeta(models.Model):
    """Stato singleton della costruzione del grafo (per il polling lato UI)."""

    in_corso = models.BooleanField(default=False)
    task_id = models.CharField(max_length=255, blank=True)
    progresso = models.JSONField(default=dict, blank=True)
    changelog = models.JSONField(default=list, blank=True)
    aggiornato_at = models.DateTimeField(auto_now=True)

    @classmethod
    def singleton(cls) -> "GrafoMeta":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
