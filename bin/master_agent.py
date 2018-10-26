#!/opt/sam/python/2.7.5/gcc447/bin/python
# Description: Beomon master agent



import sys
import os
import re
import pymongo
import subprocess
import time
import syslog
import paramiko
import signal
import ConfigParser
import datetime
import traceback
import fcntl
import struct
import socket
from optparse import OptionParser



red = "\033[31m"
endcolor = '\033[0m' # end color
nodes = ""
num_master_state = {
    "down" : 0,
    "boot" : 0,
    "error" : 0,
    "orphan" : 0,
    "up" : 0,
    "partnered" : 0,
    "torque_offline" : 0
}



# How were we called?
parser = OptionParser("%prog [options] [nodes ...]\n" +
    "Beomon master agent.  This program will check the status of \n" +
    "the compute nodes given as an arg and update the Beomon database.\n" +
    "The [nodes ...] parameter accepts bpstat's node syntax (e.g. 0-6,8-9) or \n" +
    "if no nodes are given all nodes of the master are checked"
)

(options, args) = parser.parse_args()





# Preint a stack trace, exception, and an error string to STDERR
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





try:
    nodes_to_check_cli = sys.argv[1]

except IndexError:
    nodes_to_check_cli = None



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
# Check our own health
#

new_master_data = {}


# Get the list of current processes
processes = []
for pid in [pid for pid in os.listdir('/proc') if pid.isdigit()]:
    try:
        with open("/proc/" + pid + "/cmdline", "r") as procfile:
            process = procfile.read()

            if process == "":
                continue

            # Remove the unprintable character at the end of the string
            process = list(process)
            process.pop()
            process = "".join(process)

            processes.append(process)

    except IOError: # The process could have gone away, that's fine
        pass


# Are the processes we want alive?
for proc_name in ["beoserv", "bpmaster", "recvstats", "kickbackdaemon"]:
    if "/usr/sbin/" + proc_name in processes:
        new_master_data["processes." + proc_name] = True

    else:
        sys.stdout.write(red + "Process " + proc_name + " not found!\n" + endcolor)

        new_master_data["processes." + proc_name] = False


del processes





#
# Determine what nodes we need to check and who our partner is
#

# Get our local IP - Source: https://stackoverflow.com/questions/11735821/python-get-localhost-ip
def get_interface_ip(ifname):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x8915, struct.pack('256s',
                            ifname[:15]))[20:24])

my_ip = socket.gethostbyname(socket.gethostname())

if my_ip.startswith("127."):
    interfaces = [
        "eth0",
        "eth1",
        "eth2",
        "wlan0",
        "wlan1",
        "wifi0",
        "ath0",
        "ath1",
        "ppp0",
        ]
    for ifname in interfaces:
        try:
            my_ip = get_interface_ip(ifname)
            break
        except IOError:
            pass


# Detemine what nodes this master is responsible for
nodes_to_check = ""
for line in open("/etc/beowulf/config", "r"):
    line = line.rstrip()

    if re.search("^masterorder.*" + my_ip, line) is None:
        continue

    nodes_found = line.split()[1]

    # Add the nodes to the list of nodes to check
    if nodes_to_check == "":
        nodes_to_check = nodes_found

    else:
        nodes_to_check += "," + nodes_found

    # Determine our partner's IP
    primary_ip = line.split()[2]
    secondary_ip = line.split()[3]

    if primary_ip == my_ip:
        partner = secondary_ip

    else:
        partner = primary_ip


# If we were told what nodes to check, only check those (ignoring what we found in Scyld's config)
if nodes_to_check_cli is not None:
    nodes_to_check = nodes_to_check_cli





#
# Get the output of beostat and check each node
#
try:
    bpstat_proc = subprocess.Popen([main_config["bpstat"], "-l", nodes_to_check], stdout=subprocess.PIPE, shell=False)

    status = bpstat_proc.wait()

    if status != 0:
        raise Exception("Non-zero exit status: " + str(status) + "\n")

    bpstat_out = bpstat_proc.communicate()[0]

except:
    fatal_error("Call to bpstat failed")



# Loop through bpstat's output for each node
for line in bpstat_out.split(os.linesep):
    # Skip the header
    match_header = re.match("^Node", line)
    match_end = re.match("^$", line)
    if match_header is not None or match_end is not None:
        continue


    # Get the node number and state
    (node, status) = line.split()[0:3:2]
    node = int(node)


    # Get the node's details we care about
    node_db_info = db.compute.find_one(
        {
            "_id" : node
        },
        {
            "last_checkin" : 1,
            "master_state" : 1,
            "master_state_time" : 1,
            "alerting_state" : 1,
            "_id" : 0,
        }
    )

    # Catch things that didn't exist in the document
    if node_db_info is None:
        node_db_info = {}

        node_db_info["last_checkin"] = None
        node_db_info["master_state"] = "unknown"
        node_db_info["master_state_time"] = None
        node_db_info["alerting_state"] = True

    else:
        try:
            garbage = node_db_info["last_checkin"]

        except KeyError:
            node_db_info["last_checkin"] = None

        try:
            garbage = node_db_info["master_state"]

        except KeyError:
            node_db_info["master_state"] = "unknown"

        try:
            garbage = node_db_info["master_state_time"]

        except KeyError:
            node_db_info["master_state_time"] = None



    sys.stdout.write("Node: " + str(node) + "\n")



    master_state = ""
    new_compute_data = {}



    # Note the rack location
    if node in range(0, 4):
        new_compute_data["rack"] = "C-1-2"

    elif node in range(4, 14):
        new_compute_data["rack"] = "C-1-4"

    elif node in range(14, 53):
        new_compute_data["rack"] = "C-1-3"

    elif node in range(53, 59):
        new_compute_data["rack"] = "C-1-4"

    elif node in range(59, 113):
        new_compute_data["rack"] = "C-1-20"

    elif node in range(113, 173):
        new_compute_data["rack"] = "C-1-19"

    elif node in range(173, 177):
        new_compute_data["rack"] = "C-1-20"

    elif node in range(177, 211):
        new_compute_data["rack"] = "C-1-18"

    elif node in range(211, 242):
        new_compute_data["rack"] = "C-1-17"

    elif node == 242:
        new_compute_data["rack"] = "C-1-2"

    elif node in range(243, 284):
        new_compute_data["rack"] = "C-1-21"

    elif node in range(284, 325):
        new_compute_data["rack"] = "C-1-22"

    elif node in range(325, 351):
        new_compute_data["rack"] = "C-1-23"

    elif node in range(351, 379):
        new_compute_data["rack"] = "C-1-24"

    elif node in range(379, 386):
        new_compute_data["rack"] = "C-1-2"

    elif node in range(386, 409):
        new_compute_data["rack"] = "C-1-6"

    else:
        new_compute_data["rack"] = "unknown"



    if status == "up":
        master_state = "up"

        if node_db_info["alerting_state"] is True:
            num_master_state["up"] += 1

        if node_db_info["master_state"] == "up":
            sys.stdout.write("Master state: up - known\n")
            log_self("Node " + str(node) + " has master state 'up'")

        else:
            sys.stdout.write("Master state: up - new\n")
            log_self("Node " + str(node) + " has master state 'up'")

            # Add an entry to the journal for this node
            db.compute.update(
                { "_id" : node },
                { "$push" : { "journal" : { "time" : time.time(), "entry" : "Master state change: " + node_db_info["master_state"] + " --> " + master_state } } }
            )

            try:
                ssh = paramiko.SSHClient()

                ssh.load_system_host_keys()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                ssh.connect(main_config["clusman_host"])
                channel = ssh.get_transport().open_session()

                stdin = channel.makefile("wb", 1024)
                stdout = channel.makefile("rb", 1024)
                stderr = channel.makefile_stderr("rb", 1024)

                channel.exec_command(main_config["pbsnodes"] + " -c n" + str(node) + "; exit $?")

                # Check for errors
                err = stderr.read()
                stderr.close()

                if err:
                    sys.stderr.write("Err: " + err)

                status = channel.recv_exit_status()

                if status != 0:
                    raise Exception("Non-zero exit status: " + str(status))

                stdin.close()
                stdout.close()

                # Done!
                channel.close()
                ssh.close()

            except Exception, err:
                sys.stderr.write(red + "Failed to online node with `pbsnodes` on " + main_config["clusman_host"] + ": " + str(err) + "\n" + endcolor)

            new_compute_data["master_state"] = "up"

            new_compute_data["master_state_time"] = int(time.time())


    elif status == "down": # Really could be orphan or partnered instead of down
        if node_db_info["last_checkin"] is None:
            node_db_info["last_checkin"] = 0


        # If our partner thinks the node is up, boot or error consider the node "partnered"

        # Connect to our partner and see what they think about this node
        found_partner_status = False

        try:
            ssh = paramiko.SSHClient()

            ssh.load_system_host_keys()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            ssh.connect(partner)
            channel = ssh.get_transport().open_session()

            stdin = channel.makefile("wb", 1024)
            stdout = channel.makefile("rb", 1024)
            stderr = channel.makefile_stderr("rb", 1024)

            channel.exec_command(main_config["bpstat"] + " " + str(node) + "; exit $?")

            err = stderr.read()
            stderr.close()

            # Check the status
            if err:
                sys.stderr.write("Err: " + err)

            status = channel.recv_exit_status()

            if status != 0:
                raise Exception("Non-zero exit status: " + str(status))

            stdin.close()

            for line in stdout.read().split(os.linesep):
                line = line.rstrip()

                match = re.match("^\d", line)

                if not match:
                    continue

                partner_status = line.split()[1]

                if partner_status != "down":
                    found_partner_status = True

                else:
                    found_partner_status = False

            stdout.close()

            # Done!
            channel.close()
            ssh.close()

        except Exception, err:
            sys.stderr.write(red + "Failed to find partner's status: " + str(err) + endcolor + "\n")

            found_partner_status = False


        if found_partner_status == True:
            master_state = "partnered"

            if node_db_info["alerting_state"] is True:
                num_master_state["partnered"] += 1

            sys.stdout.write("Master state: partnered\n")
            log_self("Node " + str(node) + " has master state 'partnered'")


        # If the node checked in within the last 10 minutes, consider the node an orphan
        elif node_db_info["last_checkin"] > (int(time.time()) - (60 * 10)):
            master_state = "orphan"

            if node_db_info["alerting_state"] is True:
                num_master_state["orphan"] += 1

            if node_db_info["master_state"] == "orphan":
                sys.stdout.write(red + "Master state: orphan - known\n" + endcolor)
                log_self("Node " + str(node) + " has master state 'orphan'")

                if node_db_info["alerting_state"] is True:
                    # If the node has been an orphan more than 5 days, throw an alert
                    if (int(time.time()) - node_db_info["master_state_time"]) >= (60 * 60 * 24 * 5):
                        syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-TICKET: Node " + str(node) + " is not up, state: orphan (beyond 5 day limit)")


            else:
                sys.stdout.write(red + "Master state: orphan - new\n" + endcolor)
                log_self("Node " + str(node) + " has master state 'orphan'")

                # Add an entry to the journal for this node
                db.compute.update(
                    { "_id" : node },
                    { "$push" : { "journal" : { "time" : time.time(), "entry" : "Master state change: " + node_db_info["master_state"] + " --> " + master_state } } }
                )

                try:
                    ssh = paramiko.SSHClient()

                    ssh.load_system_host_keys()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                    ssh.connect(main_config["clusman_host"])
                    channel = ssh.get_transport().open_session()

                    stdin = channel.makefile("wb", 1024)
                    stdout = channel.makefile("rb", 1024)
                    stderr = channel.makefile_stderr("rb", 1024)

                    channel.exec_command(main_config["pbsnodes"] + " -o n" + str(node) + "; exit $?")

                    # Check for errors
                    err = stderr.read()
                    stderr.close()

                    if err:
                        sys.stderr.write("Err: " + err)

                    status = channel.recv_exit_status()

                    if status != 0:
                        raise Exception("Non-zero exit status: " + str(status))

                    stdin.close()
                    stdout.close()

                    # Done!
                    channel.close()
                    ssh.close()

                except Exception, err:
                    sys.stderr.write(red + "Failed to offline node with `pbsnodes` on " + main_config["clusman_host"] + ": " + str(err) + endcolor + "\n")

                new_compute_data["master_state"] = "orphan"
                new_compute_data["master_state_time"] = int(time.time())


        # The node has not checked in within the last 10 minutes OR has been "down" as far
        # as the head node knows for less than 7 minutes, consider it down
        else:
            master_state = "down"

            if node_db_info["alerting_state"] is True:
                num_master_state["down"] += 1

            if node_db_info["master_state"] == "down":
                sys.stdout.write(red + "Master state: down - known\n" + endcolor)
                log_self("Node " + str(node) + " has master state 'down'")

                ## TODO: Add IPMI's 'chassis power cycle'

                if node_db_info["alerting_state"] is True:
                    # If the node has been down for more than 30 minutes, throw an alert
                    if (int(time.time()) - node_db_info["master_state_time"]) >= (60 * 30):
                        syslog.syslog(syslog.LOG_ERR, "Node " + str(node) + " is not up, state: down, rack: " + new_compute_data["rack"])


            else:
                sys.stdout.write(red + "Master state: down - new\n" + endcolor)

                syslog.syslog(syslog.LOG_WARNING, "Node " + str(node) + " is not up, state: down")
                log_self("Node " + str(node) + " has master state 'down'")

                # Add an entry to the journal for this node
                db.compute.update(
                    { "_id" : node },
                    { "$push" : { "journal" : { "time" : time.time(), "entry" : "Master state change: " + node_db_info["master_state"] + " --> " + master_state } } }
                )

                new_compute_data["master_state"] = "down"
                new_compute_data["master_state_time"] = int(time.time())


    elif status == "boot":
        master_state = "boot"

        if node_db_info["alerting_state"] is True:
            num_master_state["boot"] += 1

        if node_db_info["master_state"] == "boot":
            sys.stdout.write("Master state: boot - known\n")
            log_self("Node " + str(node) + " has master state 'boot'")

            if node_db_info["alerting_state"] is True:
                # If the node has been in boot master state for more than 2 hours, log an alert
                if int(time.time()) - node_db_info["master_state_time"] >= (60 * 60 * 2):
                    syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-TICKET: Node " + str(node) + " is not up, state: boot")

        else:
            sys.stdout.write("Master state: boot - new\n")
            log_self("Node " + str(node) + " has master state 'boot'")

            # Add an entry to the journal for this node
            db.compute.update(
                { "_id" : node },
                { "$push" : { "journal" : { "time" : time.time(), "entry" : "Master state change: " + node_db_info["master_state"] + " --> " + master_state } } }
            )

            new_compute_data["master_state"] = "boot"
            new_compute_data["master_state_time"] = int(time.time())


    elif status == "error":
        master_state = "error"

        if node_db_info["alerting_state"] is True:
            num_master_state["error"] += 1

        if node_db_info["master_state"] == "error":
            sys.stdout.write(red + "Master state: error - known\n" + endcolor)
            log_self("Node " + str(node) + " has master state 'error'")

        else:
            sys.stdout.write(red + "Master state: error - new\n" + endcolor)
            log_self("Node " + str(node) + " has master state 'error'")

            # Add an entry to the journal for this node
            db.compute.update(
                { "_id" : node },
                { "$push" : { "journal" : { "time" : time.time(), "entry" : "Master state change: " + node_db_info["master_state"] + " --> " + master_state } } }
            )

            new_compute_data["master_state"] = "error"
            new_compute_data["master_state_time"] = int(time.time())

        if node_db_info["alerting_state"] is True:
            syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-TICKET: Node " + str(node) + " is not up, state: error")



    #
    # Check the Torque state
    #
    if master_state == "up":
        try:
            ssh = paramiko.SSHClient()

            ssh.load_system_host_keys()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            ssh.connect(main_config["clusman_host"])
            channel = ssh.get_transport().open_session()

            stdin = channel.makefile("wb", 1024)
            stdout = channel.makefile("rb", 1024)
            stderr = channel.makefile_stderr("rb", 1024)

            channel.exec_command(main_config["pbsnodes"] + " -q n" + str(node) + "; exit $?")

            # Check for errors
            err = stderr.read()
            stderr.close()

            if err:
                sys.stderr.write(err)

            status = channel.recv_exit_status()

            if status != 0:
                raise Exception("Non-zero exit status: " + str(status))

            stdin.close()

            for line in stdout.read().split(os.linesep):
                line = line.rstrip()

                match = re.match("^\s+state", line)

                if not match:
                    continue

                torque_state = line.split()[2]

                if torque_state == "offline":
                    sys.stdout.write(red + "Torque state: Offline" + endcolor + "\n")

                    if node_db_info["alerting_state"] is True:
                        num_master_state["torque_offline"] += 1

                    new_compute_data["torque_state"] = False

                elif torque_state == "down":
                    sys.stdout.write(red + "Torque state: Down" + endcolor + "\n")

                    new_compute_data["torque_state"] = False

                else:
                    sys.stdout.write("Torque state: OK\n")

                    new_compute_data["torque_state"] = True

            stdout.close()

            # Done!
            channel.close()
            ssh.close()

        except Exception, err:
            sys.stderr.write("Failed to check Torque state node with `pbsnodes` on " + main_config["clusman_host"] + ": " + str(err) + "\n")

            syslog.syslog(syslog.LOG_WARNING, "Failed to check Torque state node with `pbsnodes` on " + main_config["clusman_host"] + " for node: " + str(node))

            new_compute_data["torque_state"] = False



    #
    # Verify that the node is still checking in if it is up
    #
    if master_state == "up":
        if node_db_info["last_checkin"] is None:
            sys.stderr.write(red + "Node " + str(node) + " last check in time is NULL" + endcolor + "\n")

        else:
            checkin_seconds_diff = int(time.time()) - node_db_info["last_checkin"]

            if checkin_seconds_diff >= 60 * 30:
                sys.stderr.write(red + "Node " + str(node) + " last check in time is stale (last checked in " + str(checkin_seconds_diff) + " seconds ago)" + endcolor + "\n")

                syslog.syslog(syslog.LOG_WARNING, "Node " + str(node) + " last check in time is stale (last checked in " + str(checkin_seconds_diff) + " seconds ago)")



    # Update the compute collection
    db.compute.update(
        {
            "_id" : node
        },
        {
            "$set" : new_compute_data
        },
        upsert = True,
    )



    sys.stdout.write("\n")



# Check if we have too many nodes not up

if num_master_state["down"] >= 10:
    sys.stdout.write(red + "WARNING: " + str(num_master_state["down"]) + " nodes with master state 'down'!" + endcolor + "\n")

    syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-ALERT: 10 or more nodes with master state 'down'")

elif num_master_state["down"] > 0:
    sys.stdout.write(str(num_master_state["down"]) + " nodes with master state 'down'\n")


if num_master_state["orphan"] >= 10:
    sys.stdout.write(red + "WARNING: " + str(num_master_state["orphan"]) + " nodes with master state 'orphan'!" + endcolor + "\n")

    syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-ALERT: 10 or more nodes with master state 'orphan'")

elif num_master_state["orphan"] > 0:
    sys.stdout.write(str(num_master_state["orphan"]) + " nodes with master state 'orphan'\n")


if num_master_state["error"] >= 10:
    sys.stdout.write(red + "WARNING: " + str(num_master_state["error"]) + " nodes with master state 'error'!" + endcolor + "\n")

    syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-ALERT: 10 or more nodes with master state 'error'")

elif num_master_state["error"] > 0:
    sys.stdout.write(str(num_master_state["error"]) + " nodes with master state 'error'\n")


if num_master_state["torque_offline"] >= 10:
    sys.stdout.write(red + "WARNING: " + str(num_master_state["torque_offline"]) + " nodes with Torque state 'offline'!" + endcolor + "\n")

    syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-ALERT: 10 or more nodes with Torque state 'offline'")

elif num_master_state["torque_offline"] > 0:
    sys.stdout.write(str(num_master_state["torque_offline"]) + " nodes with Torque state 'offline'\n")


sys.stdout.write(str(num_master_state["partnered"]) + " nodes with master state 'partnered'\n")

sys.stdout.write(str(num_master_state["up"]) + " nodes with master state 'up'\n")



# Add the number of nodes in each master state to our doc
if nodes_to_check_cli is None:
    new_master_data["num_master_state"] = num_master_state



# Report that we've now checked ourself
new_master_data["last_checkin"] = int(time.time())



# Update the master collection
db.head.update(
    {
        "_id" : hostname.split(".")[0]
    },
    {
        "$set" : new_master_data
    },
    upsert = True,
)

del(new_master_data)



log_self("- - - Run completed - - -")



# Close the DB and logs, we're done with them
syslog.closelog()
log_file_handle.close()
mongo_client.close()
