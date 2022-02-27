import email
import json
import re
import requests
import smtplib
import socks
import subprocess
import sys
import time
import urllib.parse
import yaml

from commit_message_filter import check_commit_message
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from email.message import EmailMessage
from job import Job
from mysql_helper import SQLDatabase
from proxy_smtplib import ProxySMTP

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

def notify_by_email(mydb, patch, config_smtp):

    print ("Sending email notification")

    keys = list()
    keys.append("email_sent")

    series_id = patch["series_id"]
    email_sent = False
    if mydb is not None:
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
    msg_email["Subject"] = "Re: " + patch["subject_email"]
    msg_email["From"] = "Patchwork <%s>" % config_smtp["user"]
    msg_email["To"] = patch["author_email"]
    msg_email["Cc"] = config_smtp["cc_email"]
    msg_email["In-Reply-To"] = patch["msg_id"]
    msg_email["References"] = patch["msg_id"]

    config_proxy = config_smtp["proxy"]
    print ("Proxy is %d" % config_proxy["enabled"])
    if config_proxy["enabled"]:
        print ("Using proxy")
        ret = subprocess.run(config_proxy["cmd"], shell=True)
        smtp = ProxySMTP(config_smtp["host"], config_smtp["port"], proxy_addr = config_proxy["proxy_addr"], proxy_port = config_proxy["proxy_port"])
    else:
        smtp = smtplib.SMTP(config_smtp["host"], config_smtp["port"])

    smtp.starttls()
    smtp.login(config_smtp["user"], config_smtp["password"])
    smtp.sendmail(msg_email["From"], msg_email["To"], msg_email.as_string())
    smtp.quit()

    if mydb is not None:
        mydb.update("series", ["series_id"], ["%d " % series_id], ["email_sent"], ["1"])

def regex_version_and_commit(subject):
    subject_clean_re = re.compile('\[[^]]*\]\s+(\[[^]]*\])')
    version_re = re.compile('[vV](\d+)')
    commit_entry_re = re.compile('(\d+)/(\d+)')

    subject_clean_match = subject_clean_re.match(subject)
    if subject_clean_match == None:
        return 1, 1, 1

    label = subject_clean_re.match(subject).group(1)
    version_match = version_re.search(label)

    if version_match == None:
        version_num = 1
    else:
        version_num = int(version_match.group(1))

    commit_entry_match = commit_entry_re.search(label)
    if commit_entry_match == None:
        commit_entry_num = 1
        commit_entry_den = 1
    else:
        commit_entry_num = int(commit_entry_match.group(1))
        commit_entry_den = int(commit_entry_match.group(2))

    return version_num, commit_entry_num, commit_entry_den

def fetch_and_process_patches(mydb, jobs_list, time_interval, config_pw):

    patch_list = list()

    headers = {"Authorization" : "Token %s" % config_pw["token"], "Host": config_pw["token"]}

    utc_time = datetime.utcnow()
    utc_time = utc_time - relativedelta(minutes = time_interval)
    str_time = utc_time.strftime("%Y-%m-%dT%H:%M:%S")
    str_time = urllib.parse.quote(str_time)
    url_request = "/api/events/?category=patch-completed&since=" + str_time
    url = "https://" + config_pw["host"] + url_request

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
        subject_email = subject_email.replace('\"', '')

        subject_email = subject_email[:256]
        msg_id = msg_id[:256]

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

        for job in jobs_list:
            res = mydb.query(job.name + "_patch", keys, "WHERE msg_id = \"%s\"" % msg_id)
            if res:
                continue
            mydb.insert(job.name + "_patch", {"msg_id" : msg_id, "subject_email" : subject_email})

            patch_list.append({ "job": job, "msg_id" : msg_id, "series_id" : series_id, "event_id" : event_id,
                "msg_id" : msg_id, "mbox" : mbox, "author_email" : author_email,
                "subject_email" : subject_email, "check_url" : check_url })


        keys = list()
        keys.append("series_id")
        res = mydb.query("series", keys, "WHERE series_id = %d" % series_id)
        if not res:
            mydb.insert("series", {"series_id" : "%d" % series_id, "email_sent" : 0})


    print ("Number of patches in list: %d" % len(patch_list))

    for patch in patch_list:

        job = patch["job"]
        git_cmd_template = "git --git-dir=%s/.git --work-tree=%s " % (job.config["wd"], job.config["wd"])
        _, commit_num, commit_den = regex_version_and_commit(patch["subject_email"])
        if job.config["run_full_series"] == False and commit_num != commit_den:
            continue

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
            ret = subprocess.run("curl %s/?series=%d > %s/mbox_file" % (patch["mbox"], patch["series_id"], job.config["wd"]), shell=True)
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
                    post_check(patch["check_url"], "warning", "configure_" + job.name, "Failed to apply patch", "")
                    continue
            else:
                post_check(patch["check_url"], "warning", "configure_" + job.name, "Failed to apply patch", ret.stderr)
                continue

        # check commit message
        git_cmd = git_cmd_template + " log --format=%B -n 1 master"
        ret = subprocess.run(git_cmd, capture_output=True, shell=True)
        commit_msg = ret.stdout.decode("utf-8")
        warn = check_commit_message(commit_msg)
        if warn:
            print (warn)
            post_check(patch["check_url"], "warning", "commit_msg_" + job.name, warn, "")
            notify_by_email(mydb, patch, config_pw["smtp"])

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
            post_check(patch["check_url"], "warning", "make_" + job.name, "New warnings during build", "")

        if job_result["setup_success"] == 0 and job_result_prev["setup_success"] == 1:
            notify_by_email(mydb, patch, config_pw["smtp"])

        if job_result['build_success'] == 0 and job_result_prev['build_success'] == 1:
            notify_by_email(mydb, patch, config_pw["smtp"])

        if job_result['unit_test_success'] == 0 and job_result_prev['unit_test_success'] == 1:
            notify_by_email(mydb, patch, config_pw["smtp"])

    return patch_list

if __name__ == "__main__":

    if len(sys.argv) != 2:
        print("Usage:\n $ python3 patchwork_runner.py config.yaml")
        sys.exit(1)

    with  open(sys.argv[1], 'r') as file:
        config = yaml.safe_load(file)

    # local database for storing cached job results
    mydb = SQLDatabase(config["db"])

    jobs_list = list()

    for name, config_runner in config["runner"].items():
        jobs_list.append(Job(name, config_runner))

    # when the db is first setup there are no tables. so init them
    for job in jobs_list:
        mydb.create_missing_table(job.name, ("(id INT AUTO_INCREMENT PRIMARY KEY, commit_hash BINARY(20), "
                                             "setup_success BIT(1), setup_log LONGTEXT, build_success BIT(1), build_log LONGTEXT,"
                                             "unit_test_success BIT(1), unit_test_log LONGTEXT, number_of_warnings INT)"))

        # this tables stores the patches we have already processed locally
        # it is used for checking we don't run the same job twice
        mydb.create_missing_table(job.name + "_patch", "(id INT AUTO_INCREMENT PRIMARY KEY, msg_id VARCHAR(256), subject_email VARCHAR(256))")

    # this table is used to track if we have sent an email to user for a specific
    # series. We don't want to send an email for each commit that's failed, but
    # only once per series
    mydb.create_missing_table("series", "(id INT AUTO_INCREMENT PRIMARY KEY, series_id INT, email_sent BIT(1))")

    # in minutes
    start_time = 0
    end_time = 0
    while 1:
        time_interval = (end_time - start_time) / 60 + 10
        start_time = time.time()
        patch_list = fetch_and_process_patches(mydb, jobs_list, time_interval, config["patchwork"])
        if not patch_list:
            print ("No patches, sleeping for 5 minutes")
            time.sleep(60*5)
        end_time = time.time()
    mydb.mydb.close()
