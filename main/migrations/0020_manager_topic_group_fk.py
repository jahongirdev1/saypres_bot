# Generated manually because Django is unavailable in the execution environment.
from django.db import migrations, models
import django.db.models.deletion


def migrate_group_relations(apps, schema_editor):
    ManagerTopic = apps.get_model("main", "ManagerTopic")

    for topic in ManagerTopic.objects.all():
        group = topic.manager_groups.order_by("id").first()
        if group is None:
            continue
        topic.group_id = group.id
        topic.save(update_fields=["group"])


def reverse_migrate_group_relations(apps, schema_editor):
    ManagerTopic = apps.get_model("main", "ManagerTopic")
    ManagerGroup = apps.get_model("main", "ManagerGroup")

    for topic in ManagerTopic.objects.all():
        if topic.group_id:
            try:
                group = ManagerGroup.objects.get(pk=topic.group_id)
            except ManagerGroup.DoesNotExist:
                group = None
            else:
                group.topics.add(topic)
        topic.group = None
        topic.save(update_fields=["group"])


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0019_manager_group_topics"),
    ]

    operations = [
        migrations.AddField(
            model_name="managertopic",
            name="group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="topics",
                to="main.managergroup",
            ),
        ),
        migrations.RunPython(
            migrate_group_relations,
            reverse_code=reverse_migrate_group_relations,
        ),
        migrations.AlterField(
            model_name="managertopic",
            name="group",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="topics",
                to="main.managergroup",
            ),
        ),
        migrations.RemoveField(
            model_name="managergroup",
            name="topics",
        ),
        migrations.AlterUniqueTogether(
            name="managertopic",
            unique_together={
                ("group", "category_name"),
                ("group", "thread_id"),
            },
        ),
    ]
