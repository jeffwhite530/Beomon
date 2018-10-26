#!/opt/sam/python/2.7.5/gcc447/bin/python
# Description: Beomon compute node agent



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
import glob
import pwd
from optparse import OptionParser
from multiprocessing import cpu_count
from string import ascii_lowercase



new_compute_data = {}
red = "\033[31m"
endcolor = '\033[0m'



# How were we called?
parser = OptionParser("%prog [options]\n" +
    "Beomon compute node agent.  This program will check the health of \n" +
    "the node it is running on and update the Beomon database. "
)

parser.add_option(
    "-d", "--daemonize",
    action="store_true", dest="daemonize", default=False,
    help="Become a background daemon"
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





# Read the config file
config = ConfigParser.ConfigParser()
config.read("/opt/sam/beomon/etc/beomon.conf")

main_config = dict(config.items("main"))





# Connect to the DB
def connect_mongo():
    # Returns the db object

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

        return db

    except:
        fatal_error("Failed to connect to the Beomon database")



# Update the compute collection
def update_compute_collection(my_compute_data):
    db.compute.update(
        {
            "_id" : node
        },
        {
            "$set" : my_compute_data
        },
        upsert = True,
    )



# Determine what the node's monitoring state is
def get_alerting_state():
    node_doc = db.compute.find_one(
        {
            "_id" : node
        },
        {
            "alerting_state" : 1
        }
    )

    # If this is a new node, set the monitoring state to True
    if node_doc is None or "alerting_state" not in node_doc:
        update_compute_collection({"alerting_state" : True})

        return True

    # ... otherwise just report what the current monitoring state is
    return node_doc["alerting_state"]



# Prepare for subprocess timeouts
class Alarm(Exception):
    pass

def alarm_handler(signum, frame):
    raise Alarm

signal.signal(signal.SIGALRM, alarm_handler)



# Prepare syslog
syslog.openlog(os.path.basename(sys.argv[0]), syslog.LOG_NOWAIT, syslog.LOG_DAEMON)





# Are we on a compute node?
hostname = os.uname()[1]

match = re.match("^n\d+", hostname)

if match is None:
    sys.stderr.write("Not a compute node, exiting.\n")
    sys.exit(1)

node = re.sub("^n", "", hostname)

node = int(node)





#
# Health checks
#

# Infiniband
def check_infiniband():
    # Which nodes to skip
    ib_skip_ranges = [(4,11), (40,52), (59,66), (242,242), (283,284), (379,384)]

    if any(lower <= int(node) <= upper for (lower, upper) in ib_skip_ranges):
        sys.stdout.write("Infiniband: n/a\n")

        new_compute_data["infiniband"] = True

    else:
        signal.alarm(30)

        try:
            with open(os.devnull, "w") as devnull:
                ib_info = subprocess.Popen([main_config["ibv_devinfo"]], stdin=None, stdout=subprocess.PIPE, stderr=devnull)
                out = ib_info.communicate()[0]

                signal.alarm(0)

                match = re.search("state:\s+PORT_ACTIVE", out)

                if match:
                    sys.stdout.write("Infiniband: ok\n")

                    new_compute_data["infiniband"] = True

                else:
                    sys.stdout.write(red + "Infiniband: down\n" + endcolor)

                    if alerting_state is True:
                        syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-TICKET: Node " + str(node) + " has Infiniband in state down")

                    new_compute_data["infiniband"] = False

        except Alarm:
            sys.stderr.write(red + "Infiniband: Timeout\n" + endcolor)

            new_compute_data["infiniband"] = "timeout"

        except:
            if alerting_state is True:
                syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-TICKET: Node " + str(node) + " has Infiniband in state sysfail")

            new_compute_data["infiniband"] = False

            fatal_error("Infiniband check failed", None)

    return None





# Tempurature
def check_tempurature():
    try:
        sensor_name = ""
        temp = False

        # Figure out which sensor name to use
        if any(lower <= int(node) <= upper for (lower, upper) in [(0,16), (170,176)]):
            sensor_name = "System Temp"

        elif any(lower <= int(node) <= upper for (lower, upper) in [(177,241)]):
            sensor_name = "Ambient Temp"

        elif any(lower <= int(node) <= upper for (lower, upper) in [(242,242), (283,284)]):
            sensor_name = "CPU0 Temp"

        elif any(lower <= int(node) <= upper for (lower, upper) in [(243,324)]):
            sensor_name = "CPU0_Temp"

        else:
            sys.stdout.write("Tempurature: n/a\n")

            new_compute_data["tempurature"] = True

        #sensor_name = "CPU 1 Temp"

        signal.alarm(30)

        with open(os.devnull, "w") as devnull:
            info = subprocess.Popen([main_config["ipmitool"] + " sensor get '" + sensor_name + "'"], stdin=None, stdout=subprocess.PIPE, stderr=devnull, shell=True)
            out = info.communicate()[0]

            signal.alarm(0)

            for line in out.split(os.linesep):
                line = line.rstrip()

                sensor_match = re.match("^\s+Sensor Reading\s+:\s+(\d+)", line)

                if sensor_match:
                    temp = sensor_match.group(1)

                    sys.stdout.write("Tempurature: " + temp + "C (" + sensor_name + ")\n")

                    new_compute_data["tempurature"] = temp + "C (" + sensor_name + ")"

                    break

                else:
                    continue

            # If we couldn't find a temp...
            if not temp:
                sys.stdout.write("Tempurature: unknown\n")

                new_compute_data["tempurature"] = "unknown"

    except Alarm:
        sys.stderr.write("Tempurature: Timeout")

        new_compute_data["tempurature"] = "timeout"

    except:
        new_compute_data["tempurature"] = False

        fatal_error("Tempurature check failed", None)

    return None





# Filesystems check
def check_filesystems():
    filesystems = {
        "/data/pkg" : "datapkg",
        "/data/sam" : "datasam",
        "/gscratch1" : "gscratch1",
        "/gscratch2" : "gscratch2",
        "/home" : "home0",
        "/home1" : "home1",
        "/home2" : "home2",
        "/pan" : "panasas",
        "/scratch" : "scratch",
        "/mnt/mobydisk" : "mobydisk",
    }

    sys.stdout.write("Filesystems:\n")

    new_compute_data["filesystems"] = {}


    for mount_point in sorted(filesystems.iterkeys()):
        if os.path.ismount(mount_point) is True:
            sys.stdout.write("     " + mount_point + ": ok\n")

            new_compute_data["filesystems"][mount_point] = True

        else:
            sys.stdout.write(red + "     " + mount_point + ": failed\n" + endcolor)
            if alerting_state is True:
                syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-TICKET: Node " + str(node) + " has " + mount_point + " in state failed")

            new_compute_data["filesystems"][mount_point] = False

    return None





#
# General node info
#

# CPU info
def get_cpu_info():
    # Number of cores
    num_cpu_cores = cpu_count()

    new_compute_data["cpu"] = {}

    new_compute_data["cpu"]["cpu_num"] = num_cpu_cores

    # CPU type
    proc_info_file = open("/proc/cpuinfo", "r")

    for line in proc_info_file:
        line = line.rstrip()

        model_match = re.match("^model name\s+:\s+(.*)$", line)

        if model_match:
            cpu_type = re.sub("\s+", " ", model_match.group(1))

            new_compute_data["cpu"]["cpu_type"] = cpu_type

            break

    proc_info_file.close()

    # Hyperthreading info
    # Skip Interlagos nodes
    if any(lower <= int(node) <= upper for (lower, upper) in [(325,378)]):
        sys.stdout.write("Hyperthreading: n/a\n")

        new_compute_data["cpu"]["hyperthreading"] = False

    else:
        proc_info_file = open("/proc/cpuinfo", "r")

        for line in proc_info_file:
            line = line.rstrip()

            if re.search("^siblings", line) is not None:
                num_siblings = line.split()[2]

            elif re.search("^cpu cores", line) is not None:
                num_cores = line.split()[3]

                break

        proc_info_file.close()


        num_siblings = int(num_siblings)
        num_cores = int(num_cores)


        if num_cores == num_siblings:
            new_compute_data["cpu"]["hyperthreading"] = False

        else:
            if alerting_state is True:
                syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-TICKET: Node " + str(node) + " has hyperthreading enabled")

            new_compute_data["cpu"]["hyperthreading"] = True



    sys.stdout.write("CPU:\n")
    sys.stdout.write("     CPU Type: " + cpu_type + "\n")
    sys.stdout.write("     CPU Cores: " + str(num_cpu_cores) + "\n")
    if new_compute_data["cpu"]["hyperthreading"] is False:
        sys.stdout.write("     Hyperthreading: ok (disabled)\n")

    else:
        sys.stdout.write(red + "     Hyperthreading: Error (enabled)\n" + endcolor)

    return None





# RAM amount
def get_ram_amount():
    ram_amount = int()

    signal.alarm(30)

    try:
        with open(os.devnull, "w") as devnull:
            info = subprocess.Popen([main_config["dmidecode"], "--type", "memory"], stdin=None, stdout=subprocess.PIPE, stderr=devnull, shell=False)
            out = info.communicate()[0]

            signal.alarm(0)

            out = out.rstrip()

            for dimm in re.findall("Size:\s+(\d+)", out):
                ram_amount = ram_amount + int(dimm)

    except Alarm:
        sys.stdout.write("Failed to get RAM amount, process timed out.\n")

    except:
        fatal_error("Failed to get RAM amount", None)


    if ram_amount != 0:
        sys.stdout.write("RAM: " + str(ram_amount / 1024) + " GB\n")

        new_compute_data["ram"] = ram_amount / 1024

    return None





# /scratch size
def scratch_size():
    scratch_size = int()

    for drive_letter in ascii_lowercase:
        # Stop if we have no more drives to look at
        if not os.path.isfile("/sys/block/sd" + drive_letter + "/size"):
            break

        with open("/sys/block/sd" + drive_letter + "/size", "r") as drive_size_file_handle:
            drive_size = drive_size_file_handle.read()

            drive_size = (int(drive_size) * 512) / 1000 / 1000 / 1000

            scratch_size = scratch_size + drive_size


    sys.stdout.write("/scratch Size: " + str(scratch_size) + " GB\n")

    new_compute_data["scratch_size"] = scratch_size

    return None





# GPU
def get_gpu_info():
    signal.alarm(30)

    try:
        with open(os.devnull, "w") as devnull:
            info = subprocess.Popen([main_config["devicequery"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=devnull, shell=True)
            out = info.communicate("\n")[0]

            signal.alarm(0)

            new_compute_data["gpu"] = {}

            for line in out.split(os.linesep):
                line = line.rstrip()

                # If we don't have a GPU, say so and stop looking
                if re.search(".*no CUDA-capable device is detected", line) is not None or \
                    re.search(".*CUDA driver version is insufficient for CUDA runtime version", line) is not None:
                    sys.stdout.write("GPU:\n")
                    sys.stdout.write("     Cards: 0\n")

                    new_compute_data["gpu"]["num_cards"] = 0

                    break

                # What type of card do we have?
                gpu_type_match = re.match("^Device 0: \"(.*)\".*", line)
                if gpu_type_match is not None:
                    new_compute_data["gpu"]["gpu_type"] = gpu_type_match.group(1)

                    continue

                # How many cards do we have?
                num_card_match = re.match("^Detected (\d+) CUDA Capable device", line)
                if num_card_match is not None:
                    new_compute_data["gpu"]["num_cards"] = int(num_card_match.group(1))

                    continue

                # How much memory do we have?
                ram_size_match = re.match("^\s+Total amount of global memory:\s+\d+ MBytes \((\d+) bytes\)$", line)
                if ram_size_match is not None:
                    mem_bytes_kb_total = int(ram_size_match.group(1)) * new_compute_data["gpu"]["num_cards"]
                    new_compute_data["gpu"]["ram_size"] = round(float(mem_bytes_kb_total) / 1024.0 / 1024.0 / 1024.0, 2)

                    continue

                # How many GPU cores do we have?
                num_cores_match = re.match(".*:\s+(\d+) CUDA Cores", line)
                if num_cores_match is not None:
                    new_compute_data["gpu"]["num_cores"] = int(num_cores_match.group(1)) * new_compute_data["gpu"]["num_cards"]

                    break


            # Done, print and note our GPU info if we have any
            if new_compute_data["gpu"]["num_cards"] != 0:
                sys.stdout.write("GPU:\n")
                sys.stdout.write("     GPU Type: " + str(new_compute_data["gpu"]["gpu_type"]) + "\n")
                sys.stdout.write("     Cards: " + str(new_compute_data["gpu"]["num_cards"]) + "\n")
                sys.stdout.write("     Total RAM Size: " + str(new_compute_data["gpu"]["ram_size"]) + " GB\n")
                sys.stdout.write("     Total GPU Cores: " + str(new_compute_data["gpu"]["num_cores"]) + "\n")

    except Alarm:
        sys.stdout.write(red + "Failed to check for GPU, process timed out.\n" + endcolor)

    except:
        fatal_error("GPU check failed", None)

    return None





# Serial number
def get_seral_number():
    signal.alarm(30)

    try:
        with open(os.devnull, "w") as devnull:
            info = subprocess.Popen([main_config["dmidecode"], "-s", "system-serial-number"], stdin=None, stdout=subprocess.PIPE, stderr=devnull, shell=False)
            out = info.communicate()[0]

            signal.alarm(0)

            out = out.rstrip()

            if out:
                serial = out

            else:
                serial = "unknown"

            sys.stdout.write("Serial: " + serial + "\n")

            new_compute_data["serial"] = serial

    except Alarm:
        sys.stdout.write(red + "Failed to get serial number, process timed out.\n" + endcolor)

    except:
        fatal_error("Failed to get serial number", None)

    return None





# IP addresses
def get_ip_addresses():
    sys.stdout.write("IPs:\n")

    new_compute_data["ip"] = {}

    if node < 256:
        sys.stdout.write("     GigE: 10.201.1." + str(node) + "\n")
        sys.stdout.write("     BMC: 10.202.1." + str(node) + "\n")
        sys.stdout.write("     IB: 10.203.1." + str(node) + "\n")

        new_compute_data["ip"]["gige"] = "10.201.1." + str(node)
        new_compute_data["ip"]["bmc"] = "10.202.1." + str(node)
        new_compute_data["ip"]["ib"] = "10.203.1." + str(node)

    elif node > 255:
        sys.stdout.write("     GigE: 10.201.2." + str(node - 256) + "\n")
        sys.stdout.write("     BMC: 10.202.2." + str(node - 256) + "\n")
        sys.stdout.write("     IB: 10.203.2." + str(node - 256) + "\n")

        new_compute_data["ip"]["gige"] = "10.201.2." + str(node - 256)
        new_compute_data["ip"]["bmc"] = "10.202.2." + str(node - 256)
        new_compute_data["ip"]["ib"] = "10.203.2." + str(node - 256)

    return None





# Check for missing RAM, CPUs, and GPUs
def check_missing_parts(db):
    old_compute_data = db.compute.find_one(
        {
            "_id" : node
        },
        {
            "cpu.cpu_num" : 1,
            "gpu.num_cards" : 1,
            "ram" : 1
        }
    )


    try:
        if old_compute_data.get("cpu").get("cpu_num") > new_compute_data.get("cpu").get("cpu_num"):
            sys.stderr.write(red + "Current CPU count of " + str(new_compute_data["cpu"]["cpu_num"]) + " does not match previous count of " + str(old_compute_data["cpu"]["cpu_num"]) + endcolor + "\n")
            if alerting_state is True:
                syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-TICKET: Node " + str(node) + " current CPU count of " + str(new_compute_data["cpu"]["cpu_num"]) + " does not match previous count of " + str(old_compute_data["cpu"]["cpu_num"]))

        if old_compute_data.get("gpu").get("num_cards") > new_compute_data.get("gpu").get("num_cards"):
            sys.stderr.write(red + "Current GPU card count of " + str(new_compute_data["gpu"]["num_cards"]) + " does not match previous count of " + str(old_compute_data["gpu"]["num_cards"]) + endcolor + "\n")
            if alerting_state is True:
                syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-TICKET: Node " + str(node) + " current GPU card count of " + str(new_compute_data["gpu"]["num_cards"]) + " does not match previous count of " + str(old_compute_data["gpu"]["num_cards"]))


        if old_compute_data.get("ram") > new_compute_data.get("ram"):
            sys.stderr.write(red + "Current RAM amount of " + str(new_compute_data["ram"]) + " GB does not match previous amount of " + str(old_compute_data["ram"]) + " GB" + endcolor + "\n")
            if alerting_state is True:
                syslog.syslog(syslog.LOG_ERR, "NOC-NETCOOL-TICKET: Node " + str(node) + " current RAM amount of " + str(new_compute_data["ram"]) + " GB does not match previous amount of " + str(old_compute_data["ram"]) + " GB")

    except AttributeError:
        return None

    return None





#
# Daemonizer
#



if options.daemonize == False:
    db = connect_mongo()

    # Get the current alerting state
    alerting_state = get_alerting_state()

    check_infiniband()
    check_filesystems()
    get_cpu_info()
    get_gpu_info()
    get_ip_addresses()
    get_ram_amount()
    scratch_size()
    get_seral_number()
    check_missing_parts(db)

    last_health_check = int(time.time())
    new_compute_data["last_health_check"] = last_health_check

    # Report that we've now checked ourself
    new_compute_data["last_checkin"] = int(time.time())

    # Update the compute collection
    update_compute_collection(new_compute_data)

    # Close syslog, we're done
    syslog.closelog()

else:
    # Set STDOUT and STDIN to /dev/null
    dev_null = open(os.devnull, "w")

    os.dup2(dev_null.fileno(), 0) # STDIN
    os.dup2(dev_null.fileno(), 1) # STDOUT


    # Set STDERR to a log file
    log_file = open("/opt/sam/beomon/log/" + str(node) + ".log", "a")
    os.dup2(log_file.fileno(), 2) # STDERR


    # Check if our PID or lock files already exist
    if os.path.exists("/var/lock/subsys/beomon_compute_agent") and not os.path.exists("/var/run/beomon_compute_agent.pid"):
        sys.stderr.write("PID file not found but subsys locked\n")
        sys.exit(1)

    elif os.path.exists("/var/lock/subsys/beomon_compute_agent") or os.path.exists("/var/run/beomon_compute_agent.pid"):
        sys.stderr.write("Existing PID or lock file found (/var/lock/subsys/beomon_compute_agent or " +
        "/var/run/beomon_compute_agent.pid), already running?  Exiting.\n")
        sys.exit(1)


    # Fork time!
    os.chdir("/")

    pid = os.fork()

    if not pid == 0:
        sys.exit(0)

    os.setsid()


    # Create our lock and PID files
    lockfile_handle = open("/var/lock/subsys/beomon_compute_agent", "w")
    lockfile_handle.close()

    pidfile_handle = open("/var/run/beomon_compute_agent.pid", "w")
    pidfile_handle.write(str(os.getpid()) + "\n")
    pidfile_handle.close()


    # If we get a SIGINT or SIGTERM, clean up after ourselves and exit
    def signal_handler(signal, frame):
        sys.stderr.write("Caught signal, exiting.\n")

        try:
            os.remove("/var/run/beomon_compute_agent.pid")
        except:
            pass

        try:
            os.remove("/var/lock/subsys/beomon_compute_agent")
        except:
            pass

        try:
            syslog.closelog()
        except:
            pass

        try:
            log_file.close()
        except:
            pass

        try:
            db.close()
        except:
            pass

        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


    # Connect to the DB
    db = connect_mongo()


    # Get the current alerting state
    alerting_state = get_alerting_state()


    # Get the initial info
    get_cpu_info()
    get_gpu_info()
    get_ip_addresses()
    get_ram_amount()
    scratch_size()
    get_seral_number()


    # Give IB time to come up
    time.sleep(30)


    # Mark that we need to do health checks at the start of the next loop
    last_health_check = 0


    # Keep checking in every 1 minute, do health checks once every hour
    while True:
        # Only check health every 1 hour
        if (int(time.time()) - last_health_check) > (60 * 60):
            # Get the current alerting state
            alerting_state = get_alerting_state()

            check_infiniband()
            check_filesystems()
            check_missing_parts(db)

            last_health_check = int(time.time())
            new_compute_data["last_health_check"] = last_health_check

        # Report that we've now checked ourself
        new_compute_data["last_checkin"] = int(time.time())

        # Update the compute collection
        update_compute_collection(new_compute_data)

        # Forget what we checked
        new_compute_data = {}

        # Sleep for 1 minute
        time.sleep(60)
