from django.db import models
from django.utils import timezone

# Create your models here.
class Company(models.Model):
    name = models.CharField(max_length=200, unique=True, blank=True)
    chat_id = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.name


class TeleUser(models.Model):
    telegram_id = models.BigIntegerField(unique=True, help_text="ID пользователя из Telegram")
    first_name = models.CharField(max_length=100, blank=True, null=True)
    nickname = models.CharField(max_length=100, blank=True, null=True)
    truck_number = models.CharField(max_length=100, blank=True, null=True)
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.SET_NULL)

    # Поля для хранения topic_id для каждой категории
    accounting_topic_id = models.IntegerField(
        blank=True,
        null=True,
        help_text="ID топика для Accounting"
    )
    safety_topic_id = models.IntegerField(
        blank=True,
        null=True,
        help_text="ID топика для Safety"
    )
    operations_topic_id = models.IntegerField(
        blank=True,
        null=True,
        help_text="ID топика для Operations"
    )

    def __str__(self):
        return f"{self.first_name} ({self.nickname})"


class TimeOff(models.Model):
    teleuser = models.ForeignKey(TeleUser, on_delete=models.CASCADE)
    date_from = models.DateField()
    date_till = models.DateField()
    reason = models.TextField()
    pause_insurance = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"TimeOff {self.id} for {self.teleuser}"


class Category(models.Model):
    name = models.CharField(max_length=200, unique=True)
    responsible_chat = models.IntegerField(
        blank=True,
        null=True,
        help_text="Укажите numeric chat_id или чата/группы для уведомлений"
    )
    responsible_topic_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Укажите ID топика (message_thread_id) в форуме"
    )

    def __str__(self):
        return self.name

class Question(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='questions')
    question = models.TextField()
    answer = models.TextField()

    def __str__(self):
        return f"{self.question[:50]}..."





class UserQuestion(models.Model):
    user_id = models.CharField(max_length=50, blank=True, null=True)
    username = models.CharField(max_length=100, blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, blank=True, null=True)
    content_text = models.TextField(blank=True, null=True)  # Текст
    content_photo = models.CharField(max_length=100, blank=True, null=True)  # file_id фото
    content_voice = models.CharField(max_length=100, blank=True, null=True)  # file_id голоса
    responsible_id = models.CharField(max_length=100, blank=True, null=True)
    mention_id = models.CharField(max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Question from {self.user_id} in {self.category}"


class BotConfig(models.Model):
    manager_chat_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Укажите ID чата/группы для уведомлений"
    )

    def __str__(self):
        return f"BotConfig #{self.pk}"