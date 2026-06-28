from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analisi", "0005_richiesta_tipo_confidence_flags"),
    ]

    operations = [
        migrations.AddField(
            model_name="richiesta",
            name="fonti_tracciate",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
