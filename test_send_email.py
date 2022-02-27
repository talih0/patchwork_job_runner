import smtplib
import socks
import subprocess
import sys
import yaml

from email.message import EmailMessage
from patchwork_runner import notify_by_email
from proxy_smtplib import ProxySMTP

if __name__ == "__main__":

    if len(sys.argv) != 2:
        print("Usage:\n $ python3 patchwork_runner.py config.yaml")
        sys.exit(1)

    with  open(sys.argv[1], 'r') as file:
        config = yaml.safe_load(file)

    sample_patch = {
            "series_id" : 1234,
            "msg_id" : "",
            "mbox" : "https://example.com/mbox/",
            "author_email" : "andriy.gelman@gmail.com",
            "subject_email" : "patchwork: this is a test email",
            }
    notify_by_email(None, sample_patch, config["patchwork"]["smtp"])
