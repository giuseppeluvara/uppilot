from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("analisi", "0007_fattoprocessuale"),
    ]

    operations = [
        migrations.AddField(
            model_name="fattoprocessuale",
            name="note_contraddittorio",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="fattoprocessuale",
            name="stato_contraddittorio",
            field=models.CharField(
                choices=[
                    ("pacifico", "Pacifico"),
                    ("contestato", "Contestato"),
                    ("non_contestato", "Non contestato"),
                    ("controprovato", "Controprovato"),
                    ("silente", "Controparte silente"),
                    ("da_decidere", "Da decidere"),
                ],
                default="da_decidere",
                max_length=24,
            ),
        ),
        migrations.CreateModel(
            name="EventoDecisionale",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "tipo",
                    models.CharField(
                        choices=[
                            ("matrice_aggiornata", "Matrice aggiornata"),
                            ("motivazione_aggiornata", "Motivazione aggiornata"),
                            ("bozza_aggiornata", "Bozza aggiornata"),
                            ("audit_esportato", "Audit esportato"),
                            ("red_team_eseguito", "Red team eseguito"),
                        ],
                        max_length=32,
                    ),
                ),
                ("campo", models.CharField(blank=True, max_length=255)),
                ("descrizione", models.TextField(blank=True)),
                ("valore_precedente", models.JSONField(blank=True, default=dict)),
                ("valore_nuovo", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "fatto",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="eventi_decisionali",
                        to="analisi.fattoprocessuale",
                    ),
                ),
                (
                    "lavoro",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="eventi_decisionali",
                        to="casi.lavoro",
                    ),
                ),
                (
                    "richiesta",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="eventi_decisionali",
                        to="analisi.richiesta",
                    ),
                ),
                (
                    "utente",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="eventi_decisionali",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]
