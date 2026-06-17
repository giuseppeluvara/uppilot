from django.contrib import admin

from .models import DocumentoCorpus, FrammentoCorpus


@admin.register(DocumentoCorpus)
class DocumentoCorpusAdmin(admin.ModelAdmin):
    list_display = ("titolo", "fonte", "stato", "created_at")
    list_filter = ("stato",)
    search_fields = ("titolo", "fonte")


@admin.register(FrammentoCorpus)
class FrammentoCorpusAdmin(admin.ModelAdmin):
    list_display = ("documento", "ordine")
