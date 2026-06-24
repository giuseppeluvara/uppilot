from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("analisi", "0004_bozza_pqm_richiesta_motivazione"),
    ]

    operations = [
        migrations.AddField(
            model_name="richiesta",
            name="tipo",
            field=models.CharField(
                choices=[
                    ("domanda", "Domanda"),
                    ("difesa_eccezione", "Difesa/eccezione"),
                    ("riconvenzionale", "Domanda riconvenzionale"),
                    ("istruttoria", "Istanza istruttoria"),
                    ("altro", "Altro"),
                ],
                default="domanda",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="richiesta",
            name="confidence",
            field=models.FloatField(default=0.65),
        ),
        migrations.AddField(
            model_name="richiesta",
            name="flags",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="spuntoricerca",
            name="stato_fonte",
            field=models.CharField(
                choices=[
                    ("ok", "Fonte disponibile"),
                    ("insufficiente", "Ricerca insufficiente"),
                ],
                default="ok",
                max_length=16,
            ),
        ),
    ]
