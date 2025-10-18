from django.db import models
from django.utils import timezone


def norm(s: str) -> str:
    """Return a normalized key for case-insensitive name comparisons."""

    return (s or "").strip().casefold()


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
    driver_group_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Group where driver participates"
    )
    manager_group_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Group where only managers participate"
    )

    def __str__(self):
        name = self.first_name or "Driver"
        nickname_part = f" ({self.nickname})" if self.nickname else ""
        return f"{name}{nickname_part} ({self.telegram_id})"


class TopicMap(models.Model):
    teleuser = models.ForeignKey(TeleUser, on_delete=models.CASCADE)
    category = models.ForeignKey('Category', on_delete=models.CASCADE)
    topic_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('teleuser', 'category')


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
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    responsible_topic_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Укажите ID топика (message_thread_id) в форуме"
    )
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)

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
    company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    category_name = models.CharField(max_length=200, blank=True, null=True)
    from_group_id = models.BigIntegerField(null=True, blank=True)
    to_group_id = models.BigIntegerField(null=True, blank=True)
    driver_group_id = models.BigIntegerField(null=True, blank=True)
    manager_group_id = models.BigIntegerField(null=True, blank=True)
    topic_id = models.BigIntegerField(null=True, blank=True)
    content_text = models.TextField(blank=True, null=True)
    content_photo = models.TextField(blank=True, null=True)
    content_voice = models.TextField(blank=True, null=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"MessageLog #{self.pk} from {self.teleuser}"


class ManagerGroup(models.Model):
    group_id = models.BigIntegerField(unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Manager group"
        verbose_name_plural = "Manager groups"

    def __str__(self):
        return f"ManagerGroup {self.group_id}"


class ManagerTopic(models.Model):
    group = models.ForeignKey(
        ManagerGroup,
        on_delete=models.CASCADE,
        related_name="topics",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="manager_topics",
    )
    category_name = models.CharField(max_length=100)
    topic_name = models.CharField(max_length=100)
    thread_id = models.BigIntegerField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("group", "category_name")
        indexes = [
            models.Index(fields=["group", "category_name"]),
            models.Index(fields=["group", "topic_name"]),
        ]
        verbose_name = "Manager topic"
        verbose_name_plural = "Manager topics"

    def __str__(self):
        topic = self.topic_name or self.category_name
        return f"{topic} [{self.group.group_id}]"

    @staticmethod
    def _normalize_display_name(value: str) -> str:
        return (value or "").strip()

    def save(self, *args, **kwargs):
        self.category_name = self._normalize_display_name(self.category_name)
        topic_name = self.topic_name or self.category_name
        self.topic_name = self._normalize_display_name(topic_name)
        if self.thread_id is not None:
            self.thread_id = int(self.thread_id)
        super().save(*args, **kwargs)

    @property
    def category_name_norm(self) -> str:
        return norm(self.category_name)

