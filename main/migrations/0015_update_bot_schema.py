from django.db import migrations, models
import django.db.models.deletion


def assign_company_to_categories(apps, schema_editor):
    Category = apps.get_model('main', 'Category')
    Company = apps.get_model('main', 'Company')
    company = Company.objects.first()
    if not company:
        company = Company.objects.create(name='Default Company')
    Category.objects.filter(company__isnull=True).update(company=company)


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0014_remove_userquestion_date_remove_userquestion_group_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='company',
            name='name',
            field=models.CharField(max_length=200),
        ),
        migrations.RemoveField(
            model_name='company',
            name='chat_id',
        ),
        migrations.AddField(
            model_name='company',
            name='driver_group_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='company',
            name='manager_group_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.RemoveField(
            model_name='teleuser',
            name='accounting_topic_id',
        ),
        migrations.RemoveField(
            model_name='teleuser',
            name='operations_topic_id',
        ),
        migrations.RemoveField(
            model_name='teleuser',
            name='safety_topic_id',
        ),
        migrations.RemoveField(
            model_name='category',
            name='responsible_chat',
        ),
        migrations.AddField(
            model_name='category',
            name='company',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='main.company'),
        ),
        migrations.CreateModel(
            name='MessageLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('from_group_id', models.BigIntegerField()),
                ('to_group_id', models.BigIntegerField()),
                ('topic_id', models.BigIntegerField(blank=True, null=True)),
                ('content_text', models.TextField(blank=True, null=True)),
                ('content_photo', models.TextField(blank=True, null=True)),
                ('content_voice', models.TextField(blank=True, null=True)),
                ('sent_at', models.DateTimeField(auto_now_add=True)),
                ('category', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='main.category')),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='main.company')),
                ('teleuser', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='main.teleuser')),
            ],
        ),
        migrations.RunPython(assign_company_to_categories, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='category',
            name='company',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='main.company'),
        ),
    ]
