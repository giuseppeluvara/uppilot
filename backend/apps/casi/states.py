"""State machine del Lavoro (§45).

bozza_in_corso -> analizzato -> bozza_generata -> in_revisione -> completato

Le transizioni sono validate nel service layer per evitare salti di stato non
previsti. La revisione del magistrato è fuori scope (avviene fuori piattaforma).
"""
from django.db import models


class StatoLavoro(models.TextChoices):
    BOZZA_IN_CORSO = "bozza_in_corso", "Bozza in corso"
    ANALIZZATO = "analizzato", "Analizzato"
    BOZZA_GENERATA = "bozza_generata", "Bozza generata"
    IN_REVISIONE = "in_revisione", "In revisione (interna all'utente)"
    COMPLETATO = "completato", "Completato"


# Transizioni ammesse: stato_corrente -> insieme degli stati raggiungibili
TRANSIZIONI = {
    StatoLavoro.BOZZA_IN_CORSO: {StatoLavoro.ANALIZZATO},
    StatoLavoro.ANALIZZATO: {StatoLavoro.BOZZA_GENERATA, StatoLavoro.BOZZA_IN_CORSO},
    StatoLavoro.BOZZA_GENERATA: {StatoLavoro.IN_REVISIONE, StatoLavoro.ANALIZZATO},
    StatoLavoro.IN_REVISIONE: {StatoLavoro.COMPLETATO, StatoLavoro.BOZZA_GENERATA},
    StatoLavoro.COMPLETATO: set(),
}


class TransizioneNonValida(ValueError):
    """Sollevata quando si tenta una transizione di stato non ammessa."""


def puo_transizionare(da: str, a: str) -> bool:
    return StatoLavoro(a) in TRANSIZIONI.get(StatoLavoro(da), set())
