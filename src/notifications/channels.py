"""Local channels and inert future channel placeholders."""
from __future__ import annotations


class NotificationChannel:
    channel_name = "base"
    def validate_configuration(self): return True
    def send(self, notification): raise NotImplementedError


class DashboardNotificationChannel(NotificationChannel):
    channel_name = "dashboard"
    def send(self, notification): return {"status": "NOT_APPLICABLE", "message": "already persisted"}


class ConsoleNotificationChannel(NotificationChannel):
    channel_name = "console"
    def send(self, notification):
        print(f"[{notification.severity.value}] {notification.title}: {notification.message}")
        return {"status": "DELIVERED"}


class _UnsupportedChannel(NotificationChannel):
    required_configuration = ()
    def validate_configuration(self): return False
    def send(self, notification): return {"status": "UNSUPPORTED", "message": "not configured in V1"}


class EmailNotificationChannel(_UnsupportedChannel):
    channel_name = "email"; required_configuration = ("SMTP_HOST",)
class TelegramNotificationChannel(_UnsupportedChannel):
    channel_name = "telegram"; required_configuration = ("TELEGRAM_TOKEN",)
class MacOSNotificationChannel(_UnsupportedChannel):
    channel_name = "macos"; required_configuration = ("LOCAL_NOTIFICATION_PERMISSION",)
