from django.urls import path

from chats import views

app_name = "chats"

urlpatterns = [
    path("conversations/", views.ConversationListView.as_view(), name="conversations"),
    path("conversations/create/", views.ConversationCreateView.as_view(), name="conversation-create"),
    path("conversations/<uuid:conversation_id>/messages/", views.ConversationMessagesView.as_view(), name="conversation-messages"),
    path("groups/create/", views.GroupCreateView.as_view(), name="group-create"),
    path("groups/<uuid:conversation_id>/members/", views.GroupManageMembersView.as_view(), name="group-members"),
    path("groups/<uuid:conversation_id>/lock/", views.GroupLockToggleView.as_view(), name="group-lock"),
    path("groups/<uuid:conversation_id>/join/", views.GroupJoinRequestView.as_view(), name="group-join"),
    path("groups/<uuid:conversation_id>/join-requests/", views.GroupJoinRequestListView.as_view(), name="group-join-requests"),
    path("groups/<uuid:conversation_id>/join-requests/<uuid:request_id>/process/", views.GroupJoinRequestProcessView.as_view(), name="group-join-request-process"),
    path("groups/<uuid:conversation_id>/promote/", views.GroupPromoteAdminView.as_view(), name="group-promote"),
    path("messages/<uuid:message_id>/delete/", views.MessageDeleteView.as_view(), name="message-delete"),
    path("search/messages/", views.ChatSearchMessagesView.as_view(), name="search-messages"),
    path("search/conversations/", views.ChatSearchConversationsView.as_view(), name="search-conversations"),
    path("search/users/", views.ChatSearchUsersView.as_view(), name="search-users"),
    path("search/media/", views.ChatSearchMediaView.as_view(), name="search-media"),
    path("presence/", views.UserPresenceView.as_view(), name="presence"),
]
