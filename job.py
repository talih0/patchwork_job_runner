import subprocess
import sys

class Job:
    def __init__(self, name, config):
        self.name = name
        self.config = config

        # user options
        self.run_docker_template = 'docker run --rm --net none -u %d:%d -v %s:/ffmpeg %s /bin/bash -c ' % (config['uid'], config['gid'], config['wd'], config['docker_image'])

    def setup(self):
        run_cmd = self.run_docker_template + '\"%s\"' % self.config['setup_command']
        ret = subprocess.run(run_cmd, capture_output=True, shell=True)
        if ret.returncode != 0:
            return ret
        print ("finished setup")

        run_cmd = self.run_docker_template + '\"make clean\"'
        ret = subprocess.run(run_cmd, capture_output=True, shell=True)

        if ret.returncode != 0:
            return ret

        run_cmd = self.run_docker_template + '\"make testclean\"'
        ret = subprocess.run(run_cmd, capture_output=True, shell=True)
        if ret.returncode != 0:
            return ret

        print ("finished make testclean")

        run_cmd = 'rsync -vrltLW --timeout=60 --contimeout=60 rsync://fate-suite.ffmpeg.org/fate-suite/ %s/fate-suite' % self.config['wd']
        ret = subprocess.run(run_cmd, capture_output=True, shell=True)
        print ("finished rsync")
        return ret

    def build(self):
        run_cmd = self.run_docker_template + '\"make %s\"' % self.config['build_flags']
        ret = subprocess.run(run_cmd, capture_output=True, shell=True)
        print ("finished build with ret %d" % ret.returncode)
        return ret

    def unit_tests(self):
        run_cmd = self.run_docker_template + '\"make fate %s\"' % self.config['fate_flags']
        ret = subprocess.run(run_cmd, capture_output=True, shell=True)
        print ("finished unit test with ret %d" % ret.returncode)
        return ret
