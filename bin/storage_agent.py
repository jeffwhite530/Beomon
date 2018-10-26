#!/opt/sam/python/2.7.5/gcc447/bin/python
# Description: Beomon storage agent



import sys
import os
import re
import pymongo
import subprocess
import time
import syslog
import signal
import ConfigParser
import traceback
import datetime
from optparse import OptionParser



red = "\033[31m"
endcolor = '\033[0m' # end color



# How were we called?
parser = OptionParser("%prog [options] [nodes ...]\n" +
    "Beomon storage agent.  This program will check the status of \n" +
    "the local storage server and update the Beomon database.\n"
)

(options, args) = parser.parse_args()





# Print a stack trace, exception, and an error string to STDERR
# then exit with the exit status given (default: 1) or don't exit
# if passed NoneType
def fatal_error(error_string, exit_status=1):
    red = "\033[31m"
    endcolor = "\033[0m"

    exc_type, exc_value, exc_traceback = sys.exc_info()

    traceback.print_exception(exc_type, exc_value, exc_traceback)

    sys.stderr.write("\n" + red + str(error_string) + endcolor + "\n")

    if exit_status is not None:
        sys.exit(int(exit_status))



hostname = os.uname()[1]



# Log our activities
log_file_handle = open("/opt/sam/beomon/log/" + hostname.split(".")[0] + ".log", "a+")

def log_self(message):
    log_file_handle.write(datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S") + " : " + message + "\n")
    log_file_handle.flush()



log_self("- - - Run starting - - -")



# Prepare for subprocess timeouts
class Alarm(Exception):
    pass

def alarm_handler(signum, frame):
    raise Alarm

signal.signal(signal.SIGALRM, alarm_handler)



# Prepare syslog
syslog.openlog(os.path.basename(sys.argv[0]), syslog.LOG_NOWAIT, syslog.LOG_DAEMON)



# Read the config file
config = ConfigParser.ConfigParser()
config.read("/opt/sam/beomon/etc/beomon.conf")

main_config = dict(config.items("main"))
storage_config = dict(config.items(hostname.split(".")[0]))



# Get the DB password
dbpasshandle = open("/opt/sam/beomon/beomonpass.txt", "r")
dbpass = dbpasshandle.read().rstrip()
dbpasshandle.close()



# Open a DB connection
try:
    mongo_client = pymongo.MongoClient(main_config["mongo_host"])

    db = mongo_client.beomon

    db.authenticate("beomon", dbpass)

    del(dbpass)

except:
    fatal_error("Failed to connect to the Beomon database")





#
# Check our health and performance
#

old_storage_data = db.storage.find_one(
    {
        "_id" : hostname.split(".")[0]
    }
)

if old_storage_data is None:
    old_storage_data = {}

new_storage_data = {}



#
# Note our basic information
#

new_storage_data["active_node"] = config.getboolean(hostname.split(".")[0], "active_node")
new_storage_data["data_device"] = storage_config["data_device"]
new_storage_data["data_mount"] = storage_config["data_mount"]
new_storage_data["client_mount"] = storage_config["client_mount"]
new_storage_data["description"] = storage_config["description"].strip('"')





#
# Is our device mounted?
#

if os.path.ismount(storage_config["data_mount"]):
    new_storage_data["data_device_mounted"] = True

else:
    new_storage_data["data_device_mounted"] = False

    # Update the storage collection
    db.storage.update(
        {
            "_id" : hostname.split(".")[0]
        },
        {
            "$set" : new_storage_data
        },
        upsert = True,
    )

    fatal_error("Data device " + storage_config["data_device"] + " is not mounted at " + storage_config["data_mount"])





#
# Verify the filesystem is still writable
#

sys.stdout.write("Filesystem write test: ")
sys.stdout.flush()

# Spawn a watchdog process that will time out and throw an alert if we hang too long/forever
watchdog_pid = os.fork()

if watchdog_pid == 0: # Child
    os.setsid()

    # Set an alarm for 5 minutes
    signal.alarm(60 * 5)

    slept_for = 0

    while True:
        try:
            time.sleep(1)

            slept_for += 1

            if slept_for % 5 == 0:
                log_self("Filesystem-write-test watchdog agent has waited " + str(slept_for) + " seconds so far")

        except Alarm:
            if config.getboolean(hostname.split(".")[0], "active_node") is True:
                syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-ALERT: Beomon storage agent watchdog process detected hang during filesystem write test of PRIMARY/ACTIVE node.  Filesystem " + storage_config["data_mount"] + " (client mount: " + storage_config["client_mount"] + ") unwritable?  Do manual write test, see KB.")

                fatal_error("Beomon storage agent watchdog process detected a hang during filesystem write test of PRIMARY/ACTIVE node.  Filesystem " + storage_config["data_mount"] + " (client mount: " + storage_config["client_mount"] + ") unwritable?  Do manual filesystem write test, see KB.", None)

            else:
                syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-TICKET: Beomon storage agent watchdog process detected hang during filesystem write test of SECONDARY/INACTIVE node.  Filesystem " + storage_config["data_mount"] + " (client mount: " + storage_config["client_mount"] + ") unwritable?  Do manual write test, see KB.")

                fatal_error("Beomon storage agent watchdog process detected a hang during filesystem write test of SECONDARY/INACTIVE node.  Filesystem " + storage_config["data_mount"] + " (client mount: " + storage_config["client_mount"] + ") unwritable?  Do manual filesystem write test, see KB.", None)

            new_storage_data["write_test"] = False

            # Update the storage collection
            db.storage.update(
                {
                    "_id" : hostname.split(".")[0]
                },
                {
                    "$set" : new_storage_data
                },
                upsert = True,
            )

            sys.exit(0)


else: # Parent
    write_test_file = storage_config["data_mount"] + "/beomon_storage_agent-write_test_file." + str(os.getpid())

    try:
        # Open the test file and write a byte to it then close it
        write_test_handle = open(write_test_file, "w")
        write_test_handle.write("1")
        write_test_handle.close()

        # Re-open the test file and ensure our last write worked
        write_test_handle = open(write_test_file, "r")
        write_test_data = write_test_handle.read()
        write_test_handle.close()

        os.remove(write_test_file)

        # Does the read data match what we wrote?
        if write_test_data == "1":
            log_self("Filesystem write test: success")
            print "ok"

            new_storage_data["write_test"] = True

        else:
            if config.getboolean(hostname.split(".")[0], "active_node") is True:
                syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-ALERT: Beomon storage agent write test failed of PRIMARY/ACTIVE node (read data does not match written data).  Filesystem " + storage_config["data_mount"] + " (client mount: " + storage_config["client_mount"] + ") corrupted?  Do manual write test, see KB.")

                fatal_error("Beomon storage agent write test failed of PRIMARY/ACTIVE node (read data does not match written data).  Filesystem " + storage_config["data_mount"] + " (client mount: " + storage_config["client_mount"] + ") corrupted?  Do manual write test, see KB.", None)

            else:
                syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-TICKET: Beomon storage agent write test failed of PRIMARY/ACTIVE node (read data does not match written data).  Filesystem " + storage_config["data_mount"] + " (client mount: " + storage_config["client_mount"] + ") corrupted?  Do manual write test, see KB.")

                fatal_error("Beomon storage agent write test failed of PRIMARY/ACTIVE node (read data does not match written data).  Filesystem " + storage_config["data_mount"] + " (client mount: " + storage_config["client_mount"] + ") corrupted?  Do manual write test, see KB.", None)

            new_storage_data["write_test"] = False

    except IOError:
        if config.getboolean(hostname.split(".")[0], "active_node") is True:
            syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-ALERT: Beomon storage agent write test failed of PRIMARY/ACTIVE node (IOError exception thrown).  Filesystem " + storage_config["data_mount"] + " (client mount: " + storage_config["client_mount"] + ") corrupted?  Do manual write test, see KB.")

            fatal_error("Beomon storage agent write test failed of PRIMARY/ACTIVE node (IOError exception thrown).  Filesystem " + storage_config["data_mount"] + " (client mount: " + storage_config["client_mount"] + ") corrupted?  Do manual write test, see KB.", None)

        else:
            syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-TICKET: Beomon storage agent write test failed of PRIMARY/ACTIVE node (IOError exception thrown).  Filesystem " + storage_config["data_mount"] + " (client mount: " + storage_config["client_mount"] + ") corrupted?  Do manual write test, see KB.")

            fatal_error("Beomon storage agent write test failed of PRIMARY/ACTIVE node (IOError exception thrown).  Filesystem " + storage_config["data_mount"] + " (client mount: " + storage_config["client_mount"] + ") corrupted?  Do manual write test, see KB.", None)

        new_storage_data["write_test"] = False

    finally:
        # Get rid of our watchdog process
        os.kill(watchdog_pid, 15) # SIGTERM





# Report that we've now checked ourself
new_storage_data["last_check"] = int(time.time())



# Update the storage collection
db.storage.update(
    {
        "_id" : hostname.split(".")[0]
    },
    {
        "$set" : new_storage_data
    },
    upsert = True,
)



log_self("- - - Run completed - - -")



# Close the DB and logs, we're done with them
syslog.closelog()
log_file_handle.close()
mongo_client.close()
