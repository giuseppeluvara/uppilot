from django.contrib import admin

from .models import Documento, Lavoro, SezioneDocumenti


class SezioneInline(admin.TabularInline):
    model = SezioneDocumenti
    extra = 0


@admin.register(Lavoro)
class LavoroAdmin(admin.ModelAdmin):
    list_display = ("titolo", "utente", "stato", "updated_at")
    list_filter = ("stato",)
    search_fields = ("titolo",)
    inlines = [SezioneInline]


@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = (
        "file",
        "sezione",
        "stato_estrazione",
        "metodo_estrazione",
        "flag_bassa_confidenza",
        "stato_accettazione",
    )
    list_filter = (
        "stato_estrazione",
        "stato_accettazione",
        "metodo_estrazione",
        "flag_bassa_confidenza",
    )
    readonly_fields = ("testo_estratto", "passaggi_incerti", "errore_estrazione")
