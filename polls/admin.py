from django.contrib import admin

from polls.models import Poll, PollOption, PollView, Vote


class PollOptionInline(admin.TabularInline):
    model = PollOption
    extra = 2


@admin.register(Poll)
class PollAdmin(admin.ModelAdmin):
    list_display = ["question", "author", "poll_type", "status", "total_votes", "total_views", "created_at"]
    list_filter = ["status", "poll_type"]
    search_fields = ["question", "author__username", "author__email"]
    inlines = [PollOptionInline]
    readonly_fields = ["total_votes", "total_views", "options_count", "created_at", "updated_at"]


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ["poll", "option", "voter", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["voter__username", "voter__email"]


@admin.register(PollView)
class PollViewAdmin(admin.ModelAdmin):
    list_display = ["poll", "viewer", "ip_address", "created_at"]
    list_filter = ["created_at"]
