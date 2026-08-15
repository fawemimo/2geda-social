from datetime import datetime
from botocore.exceptions import ClientError
import boto3
import os
import requests
from django.template.loader import render_to_string
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

AWS_REGION = os.getenv("AWS_S3_REGION_NAME")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID_SES")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY_SES")


class EmailService:

    def __init__(self, template_name):
        self.template_name = template_name
        self.sender = os.getenv("EMAIL_SENDER")
        self.ses_client = boto3.client(
            "ses",
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        )

    def _send_email(
        self,
        to: list[str],
        obj,
        from_email: str = "2geda Social App",
        other_values=None,
        subject=None,
    ):

        try:
            current_datetime = datetime.now()
            action_date_time = current_datetime.strftime("%a, %b %d, %Y - %I:%M %p")
            site = "https://2geda.net/"

            context = {
                "obj": obj,
                "site": site,
                "other_values": other_values if other_values else "None",
                "action_date_time": action_date_time,
                "MEDIA_URL": settings.MEDIA_URL,
            }

            html_content = render_to_string(
                template_name=self.template_name, context=context
            )

            if isinstance(to, str):
                to = [to]

            response = self.ses_client.send_email(
                Source=f"{from_email} <{self.sender}>",
                Destination={
                    "ToAddresses": to,
                },
                Message={
                    "Subject": {
                        "Data": subject if subject is not None else "Notification",
                        "Charset": "UTF-8",
                    },
                    "Body": {"Html": {"Data": html_content, "Charset": "UTF-8"}},
                },
            )
            logger.info(f"Email sent successfully: {response}")
            return response
        except ClientError as e:
            logger.exception(f"Failed to send email: {e}")

        except requests.RequestException as e:
            logger.exception(f"Failed to send email: {e}")

        except Exception as e:
            logger.exception(f"Failed to send email: {e}")
