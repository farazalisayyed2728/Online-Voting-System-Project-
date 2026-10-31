from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail, send_mass_mail

from .models import Notification, VoterProfile


@shared_task
def send_email_verification(user_id, verification_url):
    user = get_user_model().objects.get(pk=user_id)
    if not user.email:
        return
    send_mail(
        "Verify your VoteSphere account",
        f"Verify your email address within 24 hours: {verification_url}",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )


@shared_task
def send_ballot_receipt(email, election_title, receipt):
    if not email:
        return
    send_mail(
        f"Your ballot was received: {election_title}",
        (
            f"Your participation in {election_title} was recorded. "
            f"Anonymous receipt: {receipt}. Your candidate selection is not included."
        ),
        settings.DEFAULT_FROM_EMAIL,
        [email],
        fail_silently=False,
    )


@shared_task
def deliver_notification(notification_id):
    notification = Notification.objects.get(pk=notification_id)
    if notification.recipient_id:
        recipients = [notification.recipient.email] if notification.recipient.email else []
    else:
        recipients = list(
            VoterProfile.objects.filter(
                role=VoterProfile.Role.VOTER,
                approval_status=VoterProfile.ApprovalStatus.APPROVED,
                email_verified=True,
                user__is_active=True,
            )
            .exclude(user__email="")
            .values_list("user__email", flat=True)
            .distinct()
        )
    if recipients:
        send_mass_mail(
            tuple(
                (
                    notification.title,
                    notification.message,
                    settings.DEFAULT_FROM_EMAIL,
                    [recipient],
                )
                for recipient in recipients
            ),
            fail_silently=False,
        )
