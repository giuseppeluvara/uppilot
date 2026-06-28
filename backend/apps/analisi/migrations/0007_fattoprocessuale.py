from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("analisi", "0006_richiesta_fonti_tracciate"),
    ]

    operations = [
        migrations.CreateModel(
            name="FattoProcessuale",
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
                ("testo", models.TextField()),
                (
                    "stato_prova",
                    models.CharField(
                        choices=[
                            ("da_verificare", "Da verificare"),
                            ("provato", "Provato"),
                            ("non_provato", "Non provato"),
                            ("controverso", "Controverso"),
                            ("insufficiente", "Insufficiente"),
                            ("da_decidere", "Da decidere"),
                        ],
                        default="da_verificare",
                        max_length=24,
                    ),
                ),
                (
                    "funzione_prevalente",
                    models.CharField(
                        choices=[
                            ("supporta", "Supporta"),
                            ("contraddice", "Contraddice"),
                            ("integra", "Integra"),
                            ("neutra", "Neutra"),
                            ("insufficiente", "Insufficiente"),
                            ("contesto", "Solo contesto"),
                        ],
                        default="supporta",
                        max_length=24,
                    ),
                ),
                ("note_operatore", models.TextField(blank=True)),
                ("quesito_umano", models.TextField(blank=True)),
                ("ordine", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "richiesta",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fatti_processuali",
                        to="analisi.richiesta",
                    ),
                ),
            ],
            options={
                "ordering": ["richiesta__ordine", "ordine", "id"],
            },
        ),
    ]
