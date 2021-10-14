import email
import json
import os
import re
import requests
import smtplib
import socks
import subprocess
import sys
import time
import urllib.parse

from commit_message_filter import check_commit_message
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from email.message import EmailMessage
from job import Job
from mysql_helper import SQLDatabase
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

def post_check(check_url, type_check, context, msg_short, msg_long):

    if (isinstance(msg_long, bytes)):
        split_char = b'\n'
        msg_long.replace(b'\"', b'')
        msg_long.replace(b';', b'')
    else:
        split_char = '\n'
        msg_long.replace('\"', '')
        msg_long.replace(';', '')

    msg_long_split = msg_long.split(split_char)
    if len(msg_long_split) > 200:
        msg_long_split = msg_long_split[-200:]

    msg_long = split_char.join(msg_long_split)

    headers = {"Authorization" : "Token %s" % patchwork_token}
    payload = {"state" : type_check, "context" : context, "description" : msg_short, "description_long" : msg_long}
    resp = requests.post(check_url, headers=headers, data=payload)
    print(resp)
    print(resp.content)

def submit_job_result(mydb, job, job_result, check_url):

    if job_result["setup_success"] == 0:
        post_check(check_url, "warning", "configure_" + job.name, "Failed to run configure", job_result["setup_log"])
        return

    if job_result["build_success"] == 1:
        post_check(check_url, "success", "make_" + job.name, "Make finished", b'')
    else:
        post_check(check_url, "fail", "make_" + job.name, "Make failed", job_result["build_log"])
        return

    if job_result["unit_test_success"] == 1:
        post_check(check_url, "success", "make_fate_" + job.name, "Make fate finished", b'')
    else:
        post_check(check_url, "fail", "make_fate_" + job.name, "Make fate failed", job_result["unit_test_log"])
        return


def run_job(mydb, commit_hash, job):

    keys = ("setup_success", "setup_log", "build_success", "build_log",
            "unit_test_success", "unit_test_log", "number_of_warnings")

    commit_hash = commit_hash.decode("utf-8")
    job_result = mydb.query(job.name, keys, "WHERE commit_hash = 0x%s" % commit_hash)
    if job_result:
        print("\nFound cashed result: %s\n" % commit_hash)
        print(job_result)
        return job_result

    job_result = { "commit_hash" : commit_hash, "setup_success" : 0, "setup_log" : "",
                   "build_success" : 0, "build_log" : "", "unit_test_success" : 0, "unit_test_log" : "",
                   "number_of_warnings" : 0 }

    fail = 0
    ret = job.setup()
    if ret.returncode != 0:
        job_result["setup_success"] = 0
        job_result["setup_log"] = ret.stderr
        fail = 1
    else:
        job_result["setup_success"] = 1

    if fail == 0:
        ret = job.build()
        if ret.returncode != 0:
            job_result["build_success"] = 0
            job_result["build_log"] = ret.stderr.replace(b'"', b'\'')
            fail = 1
        else:
            job_result["build_success"] = 1

    if fail == 0:
        lines_out = (ret.stderr + ret.stdout).split(b'\n')
        for line in lines_out:
            if re.search(b"warning", line):
                job_result["number_of_warnings"] = job_result["number_of_warnings"] + 1

    if fail == 0:
        ret = job.unit_tests()
        if ret.returncode != 0:
            job_result["unit_test_success"] = 0
            job_result["unit_test_log"] = ret.stderr.replace(b'"', b'\'')
            fail = 1
        else:
            job_result["unit_test_success"] = 1

    print (job_result)
    mydb.insert(job.name, job_result)
    return job_result

def notify_by_email(mydb, patch):

    print ("Sending email notification")

    keys = list()
    keys.append("email_sent")

    series_id = patch["series_id"]
    res = mydb.query("series", keys, "WHERE series_id = %d" % series_id)
    email_sent = res["email_sent"]
    if email_sent:
        return

    msg = ("Hello,\n\n"
           "Thank you for submitting a patch to ffmpeg-devel.\n"
           "An error occurred during an automated build/fate test. Please review the following link for more details:\n"
           "%s\n\n"
           "Thank you,\n"
           "ffmpeg-devel") % patch['mbox'][:-5]

    msg_email = EmailMessage()
    msg_email.set_content(msg)
    msg_email["Subject"] = patch["subject_email"]
    msg_email["From"] = "Patchwork <%s>" % user_email
    msg_email["To"] = patch["author_email"]
    msg_email["Cc"] = cc_email
    msg_email["In-Reply-To"] = patch["msg_id"]
    msg_email["References"] = patch["msg_id"]

    print ("Proxy is %d" % use_proxy)
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

    mydb.update("series", ["series_id"], ["%d " % series_id], ["email_sent"], ["1"])

def fetch_and_process_patches(mydb, jobs_list):

    patch_list = list()

    headers = {"Authorization" : "Token %s" % patchwork_token, "Host": patchwork_host}

    utc_time = datetime.utcnow()
    utc_time = utc_time - relativedelta(hours=2)
    str_time = utc_time.strftime("%Y-%m-%dT%H:%M:%S")
    str_time = urllib.parse.quote(str_time)
    url_request = "/api/events/?category=patch-completed&since=" + str_time
    url = "https://" + patchwork_host + url_request

    resp = requests.get(url, headers = headers)
    print (resp)
    reply_list = json.loads(resp.content)

    for reply in reply_list:
        patch_url   = reply["payload"]["patch"]["url"]
        series_id   = reply["payload"]["series"]["id"]

        event_id    = reply["id"]
        msg_id      = reply["payload"]["patch"]["msgid"]
        mbox        = reply["payload"]["patch"]["mbox"]

        resp_patch  = requests.get(patch_url)
        reply_patch = json.loads(resp_patch.content)

        author_email  = reply_patch["submitter"]["email"]
        subject_email = reply_patch["headers"]["Subject"]
        subject_email = subject_email.replace("\n", "")

        check_url     = reply_patch["checks"]
        print ("Author email: %s" % author_email)
        print ("Subject email: %s" % subject_email)
        print ("Series id: %s" % series_id)
        print ("Check url: %s" % check_url)
        print ("Patch url: %s" % patch_url)
        print ("Mbox: %s" % mbox)
        print ("User link: %s" % mbox[:-5])

        keys = list()
        keys.append("msg_id")
        res = mydb.query("patch", keys, "WHERE msg_id = \"%s\"" % msg_id)
        if res:
            continue
        mydb.insert("patch", {"msg_id" : "%s" % msg_id, "subject_email" : subject_email})

        patch_list.append({"msg_id" : msg_id, "series_id" : series_id, "event_id" : event_id,
            "msg_id" : msg_id, "mbox" : mbox, "author_email" : author_email,
            "subject_email" : subject_email, "check_url" : check_url })


        keys = list()
        keys.append("series_id")
        res = mydb.query("series", keys, "WHERE series_id = %d" % series_id)
        if not res:
            mydb.insert("series", {"series_id" : "%d" % series_id, "email_sent" : 0})

    git_cmd_template = "git --git-dir=%s/.git --work-tree=%s " % (project_root_path, project_root_path)

    print ("Number of patches in list: %d" % len(patch_list))

    for job in jobs_list:

        for patch in patch_list:

            git_cmd = git_cmd_template + "am --abort"
            subprocess.run(git_cmd, shell=True)

            git_cmd = git_cmd_template + "fetch origin"
            subprocess.run(git_cmd, shell=True)

            git_cmd = git_cmd_template + "checkout master"
            subprocess.run(git_cmd, shell=True)

            git_cmd = git_cmd_template + "reset --hard origin/master"
            subprocess.run(git_cmd, shell=True)

            max_retries = 10
            retries = 0
            while 1:
                ret = subprocess.run("curl %s/?series=%d > %s/mbox_file" % (patch["mbox"], patch["series_id"], project_root_path), shell=True)
                if ret.returncode == 0 or retries == max_retries:
                    break
                retries = retries + 1
                time.sleep(1*60)

            if retries == max_retries:
                print ("Failed to fetch patch %s" % patch["mbox"])
                continue

            git_cmd = git_cmd_template + "am --keep-cr -3 --committer-date-is-author-date --exclude=Changelog mbox_file"
            ret = subprocess.run(git_cmd, capture_output=True, shell=True)

            if ret.returncode != 0:
                if re.search(b"Patch is empty", ret.stdout):
                    git_cmd = git_cmd_template + "am --keep-cr --skip"
                    ret = subprocess.run(git_cmd, capture_output=True, shell=True)
                    if ret.returncode != 0:
                        post_check(patch["check_url"], "warning", "configure" + job.name, "Failed to apply patch", "")
                        continue
                else:
                    post_check(patch["check_url"], "warning", "configure" + job.name, "Failed to apply patch", ret.stderr)
                    continue

            # check commit message
            git_cmd = git_cmd_template + " log --format=%B -n 1 master"
            ret = subprocess.run(git_cmd, capture_output=True, shell=True)
            commit_msg = ret.stdout.decode("utf-8")
            warn = check_commit_message(commit_msg)
            if warn:
                print (warn)
                post_check(patch["check_url"], "warning", "commit_msg_" + job.name, warn, "")
                notify_by_email(mydb, patch)

            git_cmd = git_cmd_template + " rev-parse master"
            ret = subprocess.run(git_cmd, capture_output=True, shell=True)
            current_hash = ret.stdout
            current_hash = current_hash[0:40]
            print ("Current hash %s" % current_hash)
            job_result = run_job(mydb, current_hash, job)
            submit_job_result(mydb, job, job_result, patch["check_url"])

            #  get the hash of HEAD~
            git_cmd = git_cmd_template + " rev-parse master~"
            ret = subprocess.run(git_cmd, capture_output=True, shell=True)
            prev_hash = ret.stdout
            prev_hash = prev_hash[0:40]

            git_cmd = git_cmd_template + "reset --hard master~"
            subprocess.run(git_cmd, shell=True)
            job_result_prev = run_job(mydb, prev_hash, job)

            if job_result["number_of_warnings"] > job_result_prev["number_of_warnings"]:
                post_check(patch["check_url"], "warning", "make" + job.name, "New warnings during build", "")

            if job_result["setup_success"] == 0 and job_result_prev["setup_success"] == 1:
                notify_by_email(mydb, patch)

            if job_result['build_success'] == 0 and job_result_prev['build_success'] == 1:
                notify_by_email(mydb, patch)

            if job_result['unit_test_success'] == 0 and job_result_prev['unit_test_success'] == 1:
                notify_by_email(mydb, patch)

    return patch_list

if __name__ == "__main__":

    # local database for storing cached job results
    mydb = SQLDatabase(db_host, db_user, db_password)

    jobs_list = list()

    # setup configuration
    config_x86 = dict()
    config_x86["wd"]            = project_root_path
    config_x86["docker_image"]  = "ffmpeg_build:latest"
    config_x86["setup_command"] = "source run_configure"
    config_x86["build_flags"]   = "-j44"
    config_x86["fate_flags"]    = "-k -j44"
    config_x86["uid"]           = uid
    config_x86["gid"]           = gid
    jobs_list.append(Job("x86", config_x86))

    config_ppc = dict()
    config_ppc["wd"]            = project_root_path
    config_ppc["docker_image"]  = "ffmpeg_build_ppc:latest"
    config_ppc["setup_command"] = "source run_configure_ppc"
    config_ppc["build_flags"]   = "-j44"
    config_ppc["fate_flags"]    = "-k -j44"
    config_ppc["uid"]           = uid
    config_ppc["gid"]           = gid
    jobs_list.append(Job("ppc", config_ppc))

    # when the db is first setup there are no tables. so init them
    for job in jobs_list:
        mydb.create_missing_table(job.name, ("(id INT AUTO_INCREMENT PRIMARY KEY, commit_hash BINARY(20), "
                                             "setup_success BIT(1), setup_log TEXT, build_success BIT(1), build_log TEXT,"
                                             "unit_test_success BIT(1), unit_test_log TEXT, number_of_warnings INT)"))

    # this table is used to track if we have sent an email to user for a specific
    # series. We don't want to send an email for each commit that's failed, but
    # only once per series
    mydb.create_missing_table("series", "(id INT AUTO_INCREMENT PRIMARY KEY, series_id INT, email_sent BIT(1))")

    # this tables stores the patches we have already processed locally
    # it is used for checking we don't run the same job twice
    mydb.create_missing_table("patch", "(id INT AUTO_INCREMENT PRIMARY KEY, msg_id VARCHAR(256), subject_email VARCHAR(256))")

    while 1:
        patch_list = fetch_and_process_patches(mydb, jobs_list)
        if not patch_list:
            print ("No patches, sleeping for 5 minutes")
            time.sleep(60*5)

    mydb.mydb.close()
