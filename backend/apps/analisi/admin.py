from django.contrib import admin

from .models import Bozza, Richiesta, SpuntoRicerca


@admin.register(SpuntoRicerca)
class SpuntoRicercaAdmin(admin.ModelAdmin):
    list_display = ("lavoro", "argomento", "origine", "created_at")
    list_filter = ("origine",)


@admin.register(Richiesta)
class RichiestaAdmin(admin.ModelAdmin):
    list_display = ("lavoro", "ordine", "parte_richiedente", "stato")
    list_filter = ("stato", "parte_richiedente")


@admin.register(Bozza)
class BozzaAdmin(admin.ModelAdmin):
    list_display = ("lavoro", "versione", "updated_at")
