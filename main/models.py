from django.db import models
from django.utils import timezone


class Company(models.Model):
    name = models.CharField(max_length=200)
    manager_group_id = models.BigIntegerField(null=True, blank=True)
    driver_group_id = models.BigIntegerField(null=True, blank=True)

    def __str__(self):
        return self.name


class TeleUser(models.Model):
    telegram_id = models.BigIntegerField(unique=True, help_text="ID пользователя из Telegram")
    first_name = models.CharField(max_length=100, blank=True, null=True)
    nickname = models.CharField(max_length=100, blank=True, null=True)
    truck_number = models.CharField(max_length=100, blank=True, null=True)
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.SET_NULL)

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


class CompanyBoundQuerySet(models.QuerySet):
    def for_company(self, company: Company):
        return self.filter(company=company)


class Category(models.Model):
    name = models.CharField(max_length=200, unique=True)
    responsible_topic_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Укажите ID топика (message_thread_id) в форуме"
    )
    company = models.ForeignKey(Company, on_delete=models.CASCADE)

    objects = CompanyBoundQuerySet.as_manager()

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


class MessageLog(models.Model):
    teleuser = models.ForeignKey(TeleUser, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    from_group_id = models.BigIntegerField()
    to_group_id = models.BigIntegerField()
    topic_id = models.BigIntegerField(null=True, blank=True)
    content_text = models.TextField(blank=True, null=True)
    content_photo = models.TextField(blank=True, null=True)
    content_voice = models.TextField(blank=True, null=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"MessageLog #{self.pk} from {self.teleuser}"
