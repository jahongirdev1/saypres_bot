from django.contrib import admin
from .models import *

admin.site.site_header = "Sayram Express LLC"
admin.site.site_title = "Sayram Express LLC Admin Page"

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name',)

@admin.register(TeleUser)
class TeleUserAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'nickname', 'truck_number', 'company',  'telegram_id')


@admin.register(TimeOff)
class TimeOffAdmin(admin.ModelAdmin):
    list_display = ('teleuser', 'date_from', 'date_till', 'reason',  'pause_insurance', 'created_at')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'responsible_chat', 'responsible_topic_id', 'id')

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('question', 'category', 'id')

@admin.register(UserQuestion)
class UserQuestionAdmin(admin.ModelAdmin):
    list_display = ('username', 'created_at', 'category', 'responsible_id', 'user_id')

@admin.register(BotConfig)
class BotConfigAdmin(admin.ModelAdmin):
    list_display = ["id", "manager_chat_id"]