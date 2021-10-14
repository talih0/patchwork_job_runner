import os
import smtplib
import socks
import subprocess

from email.message import EmailMessage
from proxy_smtplib import ProxySMTP

env = os.environ
use_proxy = int(env["PATCHWORK_USE_PROXY"])
socks_dynamic_port = int(env["PATCHWORK_SOCKS_DYNAMIC_PORT"])
proxy_host = env["PATCHWORK_PROXY_HOST"]
socks_proxy_uname = env["PATCHWORK_SOCKS_PROXY_UNAME"]
socks_proxy_ip = env["PATCHWORK_SOCKS_PROXY_IP"]
socks_proxy_port = int(env["PATCHWORK_SOCKS_PROXY_PORT"])

db_host = env["PATCHWORK_DB_HOST"]
db_user = env["PATCHWORK_DB_USER"]
db_password = env["PATCHWORK_DB_PASSWORD"]

smtp_host = env["PATCHWORK_SMTP_HOST"]
smtp_port = int(env["PATCHWORK_SMTP_PORT"])
user_email = env["PATCHWORK_USER_EMAIL"]
cc_email = env["PATCHWORK_CC_EMAIL"]
password_email = env["PATCHWORK_PASSWORD_EMAIL"]

uid = int(env["PATCHWORK_UID"])
gid = int(env["PATCHWORK_GID"])

patchwork_token = env["PATCHWORK_TOKEN"]
patchwork_host = env["PATCHWORK_HOST"]
project_root_path = env["PATCHWORK_PROJECT_ROOT_PATH"]

def send_email_test():
    msg = ("Hello,\n\n"
           "Thank you for submitting a patch to ffmpeg-devel.\n"
           "An error occurred during an automated build/fate test. Please review the following link for more details:\n"
           "%s\n\n"
           "Thank you,\n"
           "ffmpeg-devel") % "this is a test"

    msg_email = EmailMessage()
    msg_email.set_content(msg)
    msg_email["Subject"] = "hi"
    msg_email["From"] = "Patchwork <%s>" % user_email
    msg_email["To"] = "andriy.gelman@gmail.com"

    if use_proxy == 1:
        print ("Using proxy")
        proxy_setup_cmd = "ssh -f -D %d -p %d %s@%s sleep 10" % (socks_dynamic_port, socks_proxy_port, socks_proxy_uname, socks_proxy_ip)
        ret = subprocess.run(proxy_setup_cmd, shell=True)
        smtp = ProxySMTP(smtp_host, smtp_port, proxy_addr = proxy_host, proxy_port = socks_dynamic_port)
    else:
        smtp = smtplib.SMTP(smtp_host, smtp_port)

    smtp.starttls()
    smtp.login(user_email, password_email)
    smtp.sendmail(msg_email["From"], msg_email["To"], msg_email.as_string())
    smtp.quit()

if __name__ == "__main__":
    send_email_test()
