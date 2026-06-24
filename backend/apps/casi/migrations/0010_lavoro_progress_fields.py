from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("casi", "0009_lavoro_analisi_task_id_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="lavoro",
            name="analisi_progresso",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="lavoro",
            name="approfondimento_progresso",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="lavoro",
            name="ricerca_progresso",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
