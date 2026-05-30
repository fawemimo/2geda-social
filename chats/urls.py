from django.urls import path

from chats import views

app_name = "chats"

urlpatterns = [
    path("conversations/", views.ConversationListView.as_view(), name="conversations"),
    path("conversations/create/", views.ConversationCreateView.as_view(), name="conversation-create"),
    path("conversations/<uuid:conversation_id>/messages/", views.ConversationMessagesView.as_view(), name="conversation-messages"),
]

