from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conoscenza", "0002_grafometa_progresso"),
    ]

    operations = [
        migrations.AddField(
            model_name="grafometa",
            name="task_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="grafometa",
            name="changelog",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
