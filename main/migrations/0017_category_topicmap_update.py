from django.db import migrations, models
import django.db.models.deletion


def copy_topicmap_category_forward(apps, schema_editor):
    TopicMap = apps.get_model('main', 'TopicMap')
    Category = apps.get_model('main', 'Category')
    for topic_map in TopicMap.objects.all():
        name = getattr(topic_map, 'category_name', None)
        if not name:
            name = 'General'
        category, _ = Category.objects.get_or_create(name=name)
        topic_map.category = category
        topic_map.save(update_fields=['category'])


def copy_topicmap_category_backward(apps, schema_editor):
    TopicMap = apps.get_model('main', 'TopicMap')
    for topic_map in TopicMap.objects.select_related('category'):
        topic_map.category_name = topic_map.category.name if topic_map.category else None
        topic_map.save(update_fields=['category_name'])


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0016_per_driver_routing'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='description',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='category',
            name='company',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='main.company'),
        ),
        migrations.AlterField(
            model_name='category',
            name='name',
            field=models.CharField(max_length=100, unique=True),
        ),
        migrations.AlterUniqueTogether(
            name='topicmap',
            unique_together=set(),
        ),
        migrations.RenameField(
            model_name='topicmap',
            old_name='category',
            new_name='category_name',
        ),
        migrations.AddField(
            model_name='topicmap',
            name='category',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='main.category'),
        ),
        migrations.RunPython(copy_topicmap_category_forward, copy_topicmap_category_backward),
        migrations.AlterField(
            model_name='topicmap',
            name='category',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='main.category'),
        ),
        migrations.RemoveField(
            model_name='topicmap',
            name='category_name',
        ),
        migrations.AlterUniqueTogether(
            name='topicmap',
            unique_together={('teleuser', 'category')},
        ),
    ]
