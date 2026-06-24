from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conoscenza", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="grafometa",
            name="progresso",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
