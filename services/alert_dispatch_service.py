import hashlib
import hmac
import json
import smtplib
from email.message import EmailMessage

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from models.alert_subscription import AlertDelivery, AlertSubscription
from models.anomaly import Anomaly


def build_alert_payload(anomaly: Anomaly) -> dict:
    return {
        "id": anomaly.id,
        "contract_id": anomaly.contract_id,
        "anomaly_type": anomaly.anomaly_type,
        "severity": anomaly.severity,
        "reason": anomaly.reason,
        "status": anomaly.status,
        "reviewed_at": anomaly.reviewed_at.isoformat() if anomaly.reviewed_at else None,
        "evidence_url": anomaly.review_evidence_url,
    }


def _send_webhook(subscription: AlertSubscription, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if subscription.secret:
        headers["X-Monitor-Signature"] = "sha256=" + hmac.new(
            subscription.secret.encode("utf-8"), body, hashlib.sha256,
        ).hexdigest()
    response = httpx.post(subscription.destination, content=body, headers=headers, timeout=15)
    response.raise_for_status()


def _send_email(subscription: AlertSubscription, payload: dict) -> None:
    settings = get_settings()
    if not settings.smtp_host or not settings.alert_from_email:
        raise RuntimeError("SMTP_HOST and ALERT_FROM_EMAIL are required")
    message = EmailMessage()
    message["Subject"] = f"Alerta confirmada: {payload['anomaly_type']}"
    message["From"] = settings.alert_from_email
    message["To"] = subscription.destination
    message.set_content(json.dumps(payload, ensure_ascii=False, indent=2))
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


def dispatch_confirmed_alerts(db: Session) -> dict:
    subscriptions = db.query(AlertSubscription).filter(AlertSubscription.active.is_(True)).all()
    anomalies = db.query(Anomaly).filter(Anomaly.status == "confirmed").all()
    sent = failed = skipped = 0
    for subscription in subscriptions:
        for anomaly in anomalies:
            if subscription.anomaly_type and subscription.anomaly_type != anomaly.anomaly_type:
                continue
            exists = db.query(AlertDelivery).filter(
                AlertDelivery.subscription_id == subscription.id,
                AlertDelivery.anomaly_id == anomaly.id,
            ).first()
            if exists:
                skipped += 1
                continue
            delivery = AlertDelivery(
                subscription_id=subscription.id,
                anomaly_id=anomaly.id,
                status="pending",
            )
            db.add(delivery)
            try:
                payload = build_alert_payload(anomaly)
                if subscription.channel == "webhook":
                    _send_webhook(subscription, payload)
                elif subscription.channel == "email":
                    _send_email(subscription, payload)
                else:
                    raise ValueError(f"Unsupported channel: {subscription.channel}")
                delivery.status = "sent"
                sent += 1
            except Exception as error:
                delivery.status = "failed"
                delivery.error_message = str(error)[:2000]
                failed += 1
            db.commit()
    return {"sent": sent, "failed": failed, "skipped": skipped}
