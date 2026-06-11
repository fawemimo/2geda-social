from django.urls import path

from notifications import views

app_name = "notifications"

urlpatterns = [
    # Inbox
    path("", views.NotificationInboxView.as_view(), name="inbox"),
    path("unread-count/", views.UnreadCountView.as_view(), name="unread-count"),
    path("unread-count-by-category/", views.UnreadCountByCategoryView.as_view(), name="unread-count-by-category"),
    # Read / Unread
    path("<uuid:pk>/read/", views.MarkReadView.as_view(), name="mark-read"),
    path("<uuid:pk>/unread/", views.MarkUnreadView.as_view(), name="mark-unread"),
    path("mark-all-read/", views.MarkAllReadView.as_view(), name="mark-all-read"),
    # Delete
    path("<uuid:pk>/", views.DeleteNotificationView.as_view(), name="delete"),
    path("delete-all/", views.DeleteAllNotificationsView.as_view(), name="delete-all"),
    # Preferences
    path("preferences/", views.PreferenceListView.as_view(), name="preferences"),
    path("preferences/update/", views.PreferenceUpdateView.as_view(), name="preference-update"),
    path("preferences/bulk-update/", views.PreferenceBulkUpdateView.as_view(), name="preference-bulk-update"),
    # Mutes
    path("mutes/", views.MuteListView.as_view(), name="mutes"),
    path("mutes/actor/", views.MuteActorView.as_view(), name="mute-actor"),
    path("mutes/source/", views.MuteSourceView.as_view(), name="mute-source"),
    path("mutes/<uuid:pk>/unmute/", views.UnmuteView.as_view(), name="unmute"),
    # Device tokens
    path("devices/register/", views.RegisterDeviceView.as_view(), name="device-register"),
    path("devices/unregister/", views.UnregisterDeviceView.as_view(), name="device-unregister"),
]
