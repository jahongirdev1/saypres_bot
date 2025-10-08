from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0015_update_bot_schema'),
    ]

    operations = [
        migrations.AddField(
            model_name='teleuser',
            name='driver_group_id',
            field=models.BigIntegerField(blank=True, help_text='Group where driver participates', null=True),
        ),
        migrations.AddField(
            model_name='teleuser',
            name='manager_group_id',
            field=models.BigIntegerField(blank=True, help_text='Group where only managers participate', null=True),
        ),
        migrations.CreateModel(
            name='TopicMap',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category', models.CharField(max_length=100)),
                ('topic_id', models.BigIntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('teleuser', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='main.teleuser')),
            ],
            options={
                'unique_together': {('teleuser', 'category')},
            },
        ),
        migrations.AddField(
            model_name='messagelog',
            name='category_name',
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
        migrations.AddField(
            model_name='messagelog',
            name='driver_group_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='messagelog',
            name='manager_group_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='messagelog',
            name='category',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='main.category'),
        ),
        migrations.AlterField(
            model_name='messagelog',
            name='company',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='main.company'),
        ),
        migrations.AlterField(
            model_name='messagelog',
            name='from_group_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='messagelog',
            name='to_group_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
