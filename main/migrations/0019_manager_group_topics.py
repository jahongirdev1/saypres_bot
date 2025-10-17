# Generated manually because Django is unavailable in the execution environment.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0018_alter_messagelog_id_alter_topicmap_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="ManagerTopic",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category_name", models.CharField(max_length=100)),
                ("topic_name", models.CharField(blank=True, max_length=128)),
                ("thread_id", models.BigIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "category",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="manager_topics",
                        to="main.category",
                    ),
                ),
            ],
            options={
                "unique_together": {("category_name", "thread_id")},
            },
        ),
        migrations.CreateModel(
            name="ManagerGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("group_id", models.BigIntegerField(unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.AddField(
            model_name="managergroup",
            name="topics",
            field=models.ManyToManyField(blank=True, related_name="manager_groups", to="main.managertopic"),
        ),
    ]
