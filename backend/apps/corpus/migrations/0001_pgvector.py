from django.db import migrations
from pgvector.django import VectorExtension


class Migration(migrations.Migration):
    """Abilita l'estensione pgvector (presente nell'immagine pgvector/pgvector)."""

    initial = True
    dependencies = []
    operations = [VectorExtension()]
