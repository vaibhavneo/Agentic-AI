from __future__ import annotations
import os
import logging
from models.alerts import Alert, AlertChannel

logger = logging.getLogger(__name__)


def dispatch_alert(alert: Alert, channel: AlertChannel = AlertChannel.CONSOLE) -> bool:
    """Dispatch a single alert. Returns True on success."""
    if channel == AlertChannel.WEBHOOK and os.getenv("ALERT_WEBHOOK_URL"):
        return _webhook_alert(alert)
    return _log_alert(alert)


def dispatch_alerts(alerts: list[Alert]) -> list[Alert]:
    """Dispatch all alerts, return successfully sent ones."""
    channel = AlertChannel.WEBHOOK if os.getenv("ALERT_WEBHOOK_URL") else AlertChannel.CONSOLE
    return [a for a in alerts if dispatch_alert(a, channel)]


def _log_alert(alert: Alert) -> bool:
    level_map = {"INFO": logging.INFO, "WARNING": logging.WARNING, "CRITICAL": logging.CRITICAL}
    msg = "\n" + alert.display()
    logger.log(level_map.get(alert.severity, logging.INFO), msg)
    return True


def _webhook_alert(alert: Alert) -> bool:
    url = os.getenv("ALERT_WEBHOOK_URL", "")
    try:
        import httpx
        resp = httpx.post(url, json=alert.model_dump(mode="json"), timeout=5)
        if not resp.is_success:
            return _log_alert(alert)
        return True
    except Exception as e:
        logger.error("Webhook failed: %s", e)
        return _log_alert(alert)
