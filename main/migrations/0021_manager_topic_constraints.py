from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0020_manager_topic_group_fk"),
    ]

    operations = [
        migrations.AlterField(
            model_name="managergroup",
            name="group_id",
            field=models.BigIntegerField(db_index=True, unique=True),
        ),
        migrations.AlterField(
            model_name="managertopic",
            name="topic_name",
            field=models.CharField(max_length=100),
        ),
        migrations.AlterField(
            model_name="managertopic",
            name="thread_id",
            field=models.BigIntegerField(db_index=True),
        ),
        migrations.AlterUniqueTogether(
            name="managertopic",
            unique_together={("group", "category_name")},
        ),
        migrations.AddIndex(
            model_name="managertopic",
            index=models.Index(fields=["group", "category_name"], name="main_mgrtopic_group_cat_idx"),
        ),
        migrations.AddIndex(
            model_name="managertopic",
            index=models.Index(fields=["group", "topic_name"], name="main_mgrtopic_group_topic_idx"),
        ),
    ]
