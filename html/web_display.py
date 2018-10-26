#!/opt/sam/python/2.7.5/gcc447/bin/python
# Description: Beomon Web interface



import sys
sys.path.append("/opt/sam/beomon/bin")
import os
import re
import pymongo
import time
import locale
import signal
import subprocess
import ConfigParser
import traceback
import syslog
import bottle
from bottle import Bottle
from bottle import run
from bottle import template
from bottle import route
from bottle import post
from bottle import get
from bottle import request
from bottle import error
from optparse import OptionParser



# How were we called?
parser = OptionParser("%prog [options]\n" +
    "Beomon status viewer.  This is a Web server which will display the status of the cluster."
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



# Prepare syslog
syslog.openlog(os.path.basename(sys.argv[0]), syslog.LOG_NOWAIT, syslog.LOG_DAEMON)



# Read the config file
config = ConfigParser.ConfigParser()
config.read("/opt/sam/beomon/etc/beomon.conf")

main_config = dict(config.items("main"))





# Get the DB password
dbpasshandle = open("/opt/sam/beomon/beomonpass.txt", "r")
dbpass = dbpasshandle.read().rstrip("\n")
dbpasshandle.close()



# Open a DB connection
try:
    mongo_client = pymongo.MongoClient(main_config["mongo_host"])

    db = mongo_client.beomon

    db.authenticate("beomon", dbpass)

    del(dbpass)

except:
    fatal_error("Failed to connect to the Beomon database")





bottle.TEMPLATE_PATH.insert(0, "/opt/sam/beomon/html/views")





# Toggle the alerting state of a compute node
@post("/toggle_alerting_state/")
@post("/toggle_alerting_state")
def toggle_alerting_state():
    if request.POST["alerting_state"] == "True":
        new_alerting_state = False

    else:
        new_alerting_state = True

    db.compute.update(
        {
            "_id" : int(request.POST["id"])
        },
        {
            "$set" : {"alerting_state" : new_alerting_state}
        },
        upsert = True,
    )

    return "OK"





# Individual detail page for a compute node
@route("/node/<node>/")
@route("/node/<node>")
def show_node_page(node):
    # Did we get a proper node number?
    try:
        node = int(node)

    except ValueError:
        return "No such node: " + str(node)


    node_doc = db.compute.find_one(
        {
            "_id" : node
        },
    )

    # Does the node exist?
    if node_doc is None:
        return "No such node: " + str(node)


    # Make things pretty...
    try:
        if node_doc["gpu"]["num_cards"] != 0:
            node_doc["gpu"]["num_cores"] = locale.format("%0.0f", node_doc["gpu"]["num_cores"], grouping=True)

        node_doc["last_checkin"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(node_doc["last_checkin"]))
        node_doc["last_health_check"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(node_doc["last_health_check"]))

        node_doc["master_state_time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(node_doc["master_state_time"]))

    except KeyError as err:
        return "Details missing (" + str(err) + ") for node " + str(node)



    # Make a pretty timestamp in the journal entries
    try:
        for entry in node_doc["journal"]:
            entry["time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry["time"]))

    except KeyError:
        node_doc["journal"] = []


    return bottle.template("node", node_doc=node_doc)





# Add a journal entry to a compute node
@post("/node/<node>/journal/")
@post("/node/<node>/journal")
def show_node_page(node):
    # Did we get a proper node number?
    try:
        node = int(node)

    except ValueError:
        return "No such node: " + str(node)

    entry = request.forms.get("entry")

    # Replace newlines and line feeds with HTML's <br>
    entry = entry.replace("\r\n", "<br>")

    db.compute.update(
        { "_id" : node },
        { "$push" : { "journal" : { "time" : time.time(), "entry" : entry } } }
    )



    return bottle.template("node_journal_success", node=node)





# Individual detail page for a head node
@route("/head/<head>/")
@route("/head/<head>")
def show_head_page(head):
    node_doc = db.head.find_one(
        {
            "_id" : head
        }
    )

    # Does the node exist?
    if node_doc is None:
        return "No such node"


    try:
        # Switch the processes to text rather than bool
        for process, value in node_doc["processes"].items():
            if value is True:
                node_doc["processes"][process] = "ok"

            else:
                node_doc["processes"][process] = "down"


        # Make things pretty...
        node_doc["last_checkin"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(node_doc["last_checkin"]))

    except KeyError:
        return "Details missing (" + err + ") for " + str(node)


    # Output a "pretty" string of node numbers (e.g. 0-4,20-24)
    def pretty_node_range(nodes):
        node_highest = sorted(nodes)[-1]
        new_node_chunk = True
        node_chunks = ""

        for num in xrange(0, 9999):
            # If we're already above the highest node number, stop
            if num > node_highest:
                break


            # Is the number one of the nodes?
            if num in nodes:
                if new_node_chunk == True:
                    new_node_chunk = False

                    if node_chunks == "":
                        node_chunks += str(num)

                    else:
                        node_chunks += "," + str(num)

                # Are we at the end of a chunk?
                elif num + 1 not in nodes:
                    node_chunks += "-" + str(num)

            # No?  Mark that the next node we find is the beginning of another chunk
            else:
                new_node_chunk = True

        return node_chunks


    # Switch the node lists into pretty strings
    node_doc["primary_of"] = pretty_node_range(node_doc["primary_of"])
    node_doc["secondary_of"] = pretty_node_range(node_doc["secondary_of"])



    #
    # Get any mismatched files
    #

    head0a_doc = db.head.find_one(
        {
            "_id" : "head0a"
        },
        {
            "file_hashes" : 1,
            "_id" : 0
        }
    )

    bad_files = []
    if head0a_doc is not None:
        for each_file in head0a_doc["file_hashes"]:
            try:
                if not head0a_doc["file_hashes"][each_file] == node_doc["file_hashes"][each_file]:
                    file_name_with_dots = re.sub(r"\[DOT\]", ".", each_file)

                    bad_files.append(file_name_with_dots)

            except KeyError:
                pass





    # Make a pretty timestamp in the journal entries
    try:
        for entry in node_doc["journal"]:
            entry["time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry["time"]))

    except KeyError:
        node_doc["journal"] = []



    return bottle.template("head", node_doc=node_doc, bad_files=bad_files)





# Add a journal entry to a head node
@post("/head/<head>/journal/")
@post("/head/<head>/journal")
def show_head_page(head):
    entry = request.forms.get("entry")

    # Replace newlines and line feeds with HTML's <br>
    entry = entry.replace("\r\n", "<br>")

    db.head.update(
        { "_id" : head },
        { "$push" : { "journal" : { "time" : time.time(), "entry" : entry } } }
    )



    return bottle.template("head_journal_success", head=head)





# Individual detail page for a storage node
@route("/storage/<storage>/")
@route("/storage/<storage>")
def show_storage_page(storage):
    node_doc = db.storage.find_one(
        {
            "_id" : storage
        }
    )

    # Does the node exist?
    if node_doc is None:
        return "No such node"


    try:
        # Make things pretty...
        node_doc["last_checkin"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(node_doc["last_checkin"]))

    except KeyError:
        return "Details missing (" + err + ") for " + str(node)



    # Make a pretty timestamp in the journal entries
    try:
        for entry in node_doc["journal"]:
            entry["time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry["time"]))

    except KeyError:
        node_doc["journal"] = []



    return bottle.template("storage", node_doc=node_doc)





# Add a journal entry to a storage node
@post("/storage/<storage>/journal/")
@post("/storage/<storage>/journal")
def show_storage_page(storage):
    entry = request.forms.get("entry")

    # Replace newlines and line feeds with HTML's <br>
    entry = entry.replace("\r\n", "<br>")

    db.storage.update(
        { "_id" : storage },
        { "$push" : { "journal" : { "time" : time.time(), "entry" : entry } } }
    )



    return bottle.template("storage_journal_success", storage=storage)





@route("/")
def index():
    index_page = []

    locale.setlocale(locale.LC_ALL, 'en_US')

    # Main header
    index_page.append("""
    <html>
    <head>
        <title>Frank Cluster Status</title>
        <link href="/static/style.css" media="all" rel="stylesheet" type="text/css">
        <script src="/static/jquery.min.js" type="text/javascript"></script>

        <script type="text/javascript">

        function toggle_alerting_state(id) {

            if ($("#"+id).attr("alerting_state") !== "unknown") {

                $.ajax({
                    type: 'POST',
                    url: 'beomon/toggle_alerting_state',
                    dataType: 'json',
                    async: true,
                    data: {
                            id: id,
                            alerting_state: $("#"+id).attr("alerting_state"),
                        }
                    })
            }

            if ($("#"+id).attr("alerting_state") === "True") {
                $("#"+id).text("no")
                $("#"+id).attr("alerting_state", "False")
                $("#"+id).attr("style", "background:red")

            } else if ($("#"+id).attr("alerting_state") === "False")  {
                $("#"+id).text("yes")
                $("#"+id).attr("alerting_state", "True")
                $("#"+id).attr("style", "")

            }
        }

        </script>
    </head>
    <body>

    <div id="header" style="text-align:center; margin-left:auto; margin-right:auto;">
        <h2>Beomon</h2>
        <p>Node master state (up, down, boot ...) is updated every 5 minutes.</p>
    </div>
    """)


    #
    # Summary tables
    #

    index_page.append("""
    <!-- Outer div to contain the summary tables -->
    <div id="summary_outer" style="text-align:center; margin-left:auto; margin-right:auto;display:block;width:500px;">
    """)


    #
    # Summary table: Compute summary
    #
    index_page.append("""
        <!-- Inner div containing the compute summary -->
        <div id="compute_summary" style="display:inline;float:left; width:45%;">
            <table>
                <thead>
                    <th colspan="2">Compute Summary</th>
                </thead>
                <tbody>
    """)

    index_page.append("""
    <tr>
        <td>Nodes Total</td>
        <td>""" + str(db.compute.count()) + """</td>
    </tr>
    """)


    index_page.append("""
    <tr>
        <td>Nodes Up</td>
        <td>""" + str(db.compute.find({ "master_state" : "up" }).count()) + """</td>
    </tr>
    """)


    index_page.append("    <tr><td>Nodes Down</td>\n")
    num_node_docs_down = db.compute.find({ "master_state" : "down" }).count()
    if num_node_docs_down == 0:
        index_page.append("        <td>0</td>\n    </tr>")
    else:
        index_page.append("        <td><span style='color:red'>" + str(num_node_docs_down) + "</td>\n    </tr>\n")


    index_page.append("    <tr><td>Nodes Error</td>\n")
    num_node_docs_error = db.compute.find({ "master_state" : "error" }).count()
    if num_node_docs_error == 0:
        index_page.append("        <td>0</td>\n    </tr>\n")
    else:
        index_page.append("        <td><span style='color:red'>" + str(num_node_docs_error) + "</td>\n    </tr>\n")


    index_page.append("    <tr>\n        <td>Nodes Booting</td>\n")
    num_node_docs_boot = db.compute.find({ "master_state" : "boot" }).count()
    if num_node_docs_boot == 0:
        index_page.append("        <td>0</td>\n    </tr>\n")

    else:
        index_page.append("        <td><span style='color:red'>" + str(num_node_docs_boot) + "</td>\n    </tr>\n")


    index_page.append("    <tr>\n        <td>Nodes Orphaned</td>\n")
    num_node_docs_orphan = db.compute.find({ "master_state" : "orphan" }).count()
    if num_node_docs_orphan == 0:
        index_page.append("        <td>0</td>\n    </tr>\n")

    else:
        index_page.append("        <td><span style='color:red'>" + str(num_node_docs_orphan) + "</td>\n    </tr>\n")


    cpu_total = 0
    for node_doc in db.compute.find({}, { "cpu" : 1}):
        try:
            cpu_total += node_doc["cpu"]["cpu_num"]

        except KeyError:
            pass

    index_page.append("    <tr>\n        <td>Total CPU Cores</td>\n")
    index_page.append("        <td>" + locale.format("%d", cpu_total, grouping=True) + "</td>\n    </tr>\n")


    gpu_cores_total = 0
    for node_doc in db.compute.find({}, { "gpu" : 1 }):
        try:
            gpu_cores_total += node_doc["gpu"]["num_cores"]

        except KeyError:
            pass

    index_page.append("    <tr>\n        <td>Total GPU Cores</td>\n")
    index_page.append("        <td>" + locale.format("%0.0f", gpu_cores_total, grouping=True) + "</td>\n    </tr>\n")


    ram_total = 0
    for node_doc in db.compute.find({}, { "ram" : 1 }):
        try:
            ram_total += node_doc["ram"]

        except KeyError:
            pass

    index_page.append("    <tr>\n        <td>Total System RAM</td>\n")
    index_page.append("        <td>" + locale.format("%0.2f", ram_total / float(1024), grouping=True) + " TB</td>\n    </tr>\n")


    gpu_ram_total = 0
    for node_doc in db.compute.find({}, { "gpu" : 1 }):
        try:
            gpu_ram_total += node_doc["gpu"]["ram_size"]

        except KeyError:
            pass

    index_page.append("    <tr>\n        <td>Total GPU RAM</td>\n")
    index_page.append("        <td>" + locale.format("%0.2f", gpu_ram_total, grouping=True) + " GB</td>\n    </tr>\n")


    scratch_total = 0
    for node_doc in db.compute.find().sort("_id", 1):
        try:
            scratch_total += node_doc["scratch_size"]

        except KeyError:
            pass

    index_page.append("    <tr>\n        <td>Total /scratch</td>\n")
    index_page.append("        <td>" + locale.format("%0.2f", scratch_total / float(1024), grouping=True) + " TB</td>\n    </tr>\n")


    # End of compute summary table
    index_page.append("""
                </tbody>
            </table>
        </div> <!-- compute_summary -->
    """)


    # Add space between the compute summary and storage summary tables
    index_page.append("""
        <div id="summary_spacer" style="display:block;float:center; width:5%;">
        </div>
    """)



    #
    # Summary table: Storage summary
    #

    storage_totals = {
        "size" : 0,
        "used" : 0,
        "free" : 0,
    }


    index_page.append("""
        <!-- Inner div containing the storage summary -->
        <div id="storage_summary" style="display:inline;float:right; width:50%;">
            <table>
                <thead>
                    <tr>
                        <th colspan="3">Storage Summary</th>
                    </tr>
                    <tr>
                        <th>Mount</th>
                        <th>Size</th>
                        <th>% Used</th>
                </thead>
                <tbody>
    """)


    for line in open("/etc/mtab", "r"):
        line = line.rstrip()

        if line.split()[2] in ["nfs", "lustre", "panfs"]: # "fuse" removed because SLASH2 gives back wrong information to os.statvfs(), good job PSC, A+ work there...
            mount_point = line.split()[1]

        else:
            continue

        # There are two mounts from s-misc0, skip one of them
        if mount_point == "/data/pkg":
            continue

        if os.path.ismount(mount_point):
            statvfs = os.statvfs(mount_point)

            storage_totals["size"] += statvfs.f_frsize * statvfs.f_blocks
            storage_totals["used"] += (statvfs.f_frsize * statvfs.f_blocks) - (statvfs.f_frsize * statvfs.f_bfree)
            storage_totals["free"] += statvfs.f_frsize * statvfs.f_bfree

            index_page.append("    <tr>\n        <td>" + mount_point + "</td>\n")
            index_page.append("        <td>" + str(round((statvfs.f_frsize * statvfs.f_blocks) / 1024.0 / 1024 / 1024 / 1024, 2)) + " TB</td>\n")
            index_page.append("        <td style=\"text-align:center;\">" + str(100 * ((statvfs.f_frsize * statvfs.f_blocks) - (statvfs.f_frsize * statvfs.f_bfree)) / (statvfs.f_frsize * statvfs.f_blocks)) + "%</td>\n    </tr>\n")

        else:
            index_page.append("    <tr>\n        <td>" + mount_point + "</td>\n")
            index_page.append("        <td style=\"font-weight:bold;color:red;\">Unknown</td>\n")
            index_page.append("        <td style=\"font-weight:bold;color:red;\">Unknown</td>\n    </tr>\n")

    index_page.append("<tr><td style=\"text-align:center\">Total:</td>\n")
    index_page.append("<td>" + str(round(storage_totals["size"] / 1024 / 1024 / 1024 / 1024, 2)) + " TB</td>\n")
    index_page.append("<td style=\"text-align:center;\">" + str(100 * storage_totals["used"] / storage_totals["size"]) + "%</td></tr>")



    # End of storage summary table
    index_page.append("""
                </tbody>
            </table>
        </div> <!-- storage_summary -->
    """)


    # End of summary tables
    index_page.append("""
    </div> <!-- summary_outer -->
    """)



    #
    # Start of detail tables
    #
    index_page.append("""
    <!-- Outer div to contain the summary tables -->
    <div id="detail_outer" style="text-align:center; margin-left:auto; margin-right:auto;display:block;width:750px;clear:both;padding-top:25px;">
    """)



    #
    # Master node detail table
    #
    index_page.append("""
    <!-- Inner div containing the master node detail table -->
    <div id="master_detail" style="text-align:center; margin-left:auto; margin-right:auto; display:block;">
    <table id="master" style="text-align:center;">
        <thead>
            <tr>
                <th colspan="7">Master Node Details</th>
            </tr>
            <tr>
                <th scope="col">Node</th>
                <th scope="col">Processes</th>
                <th scope="col">Nodes<br>Up</th>
                <th scope="col">Nodes<br>Down</th>
                <th scope="col">Nodes<br>Error</th>
                <th scope="col">Nodes<br>Booting</th>
                <th scope="col">Nodes<br>Orphaned</th>
            </tr>
        </thead>
        <tbody>
    """)


    # Loop through each node in the DB
    for node_doc in db.head.find().sort("_id", 1):
        #
        # Node
        #

        index_page.append("<tr>\n<td><a href=\"/beomon/head/" + node_doc["_id"] +"\">" + node_doc["_id"] + "</a></td>\n")


        #
        # Processes
        #

        if "processes" not in node_doc:
            index_page.append("<td style=\"font-weight:bold;color:red;\">unknown</td>\n")

        else:
            processes_ok = True

            for process in node_doc["processes"]:
                if process is not True:
                    processes_ok == False

            if processes_ok is True:
                index_page.append("<td>ok</td>\n")

            else:
                index_page.append("<td style=\"font-weight:bold;color:red;\">down</td>\n")



        #
        # Nodes master state counts
        #

        index_page.append("<td>" + str(node_doc["num_master_state"]["up"]) + "</td>\n")
        index_page.append("<td>" + str(node_doc["num_master_state"]["down"]) + "</td>\n")
        index_page.append("<td>" + str(node_doc["num_master_state"]["error"]) + "</td>\n")
        index_page.append("<td>" + str(node_doc["num_master_state"]["boot"]) + "</td>\n")
        index_page.append("<td>" + str(node_doc["num_master_state"]["orphan"]) + "</td>\n")



    # End of master detail table
    index_page.append("""
        </tbody>
    </table>
    </div> <!-- master_detail -->
    """)





    #
    # Storage node detail table
    #
    index_page.append("""
    <!-- Inner div containing the storage node detail table -->
    <div id="storage_detail" style="text-align:center; margin-left:auto; margin-right:auto; display:block;padding-top:25px;">
    <table id="storage" style="text-align:center;">
        <thead>
            <tr>
                <th colspan="3">Storage Node Details</th>
            </tr>
            <tr>
                <th scope="col">Node</th>
                <th scope="col">Active<br>Node</th>
                <th scope="col">Filesystem<br>Writable</th>
            </tr>
        </thead>
        <tbody>
    """)


    # Loop through each node in the DB
    for node_doc in db.storage.find().sort("_id", 1):
        #
        # Node
        #

        index_page.append("<tr>\n<td><a href=\"/beomon/storage/" + node_doc["_id"] +"\">" + node_doc["_id"] + "</a></td>\n")


        #
        # Active node?
        #
        if node_doc["active_node"] is True:
            index_page.append("<td>Yes</td>\n")

        else:
            index_page.append("<td>No</td>\n")


        #
        # Data device mounted?
        #

        if node_doc["data_device_mounted"] is False:
            index_page.append("<td style='font-weight:bold;color:red;'>Data device " + node_doc["data_device"] + " is not mounted at " + node_doc["data_mount"] + "</td>\n")

            continue

        #
        # Filesystem Writable
        #

        if "write_test" not in node_doc:
            index_page.append("<td style=\"font-weight:bold;color:red;\">unknown</td>\n")

        else:
            if node_doc["write_test"] is True:
                index_page.append("<td>ok</td>\n")

            else:
                index_page.append("<td style=\"font-weight:bold;color:red;\">down</td>\n")



    # End of storage detail table
    index_page.append("""
        </tbody>
    </table>
    </div> <!-- storage_detail -->
    """)





    #
    # Compute node detail table
    #

    # Compute node detail table header
    index_page.append("""
    <!-- Inner div containing the compute detail table -->
    <div id="compute_detail" style="text-align:center; margin-left:auto; margin-right:auto; display:block;padding-top:25px;">
    <table id="nodes" style="text-align:center;">
        <thead>
            <tr>
                <th colspan="6">Compute Node Details</th>
            </tr>
            <tr>
                <th scope="col">Alerting<br>Enabled</th>
                <th scope="col">Node ID</th>
                <th scope="col">Master<br>State</th>
                <th scope="col">Torque<br>State</th>
                <th scope="col">Infiniband<br>State</th>
                <th scope="col">Filesystems<br>Mounted</th>
            </tr>
        </thead>
        <tbody>
    """)





    # Loop through each node in the DB
    for node_doc in db.compute.find().sort("_id", 1):
        # Make the row have a red background if the node is down or in error state
        if "master_state" in node_doc and (node_doc["master_state"] == "down" or node_doc["master_state"] == "error"):
            index_page.append("<tr style=\"background-color:red\">\n")

        else:
            index_page.append("<tr>\n")



        #
        # Alerting state
        #

        try:
            if node_doc["alerting_state"] is True:
                index_page.append("<td> <button id=\"" + str(node_doc["_id"]) + "\" alerting_state=\"" + str(node_doc["alerting_state"]) + "\" onclick=\"toggle_alerting_state(this.id)\">yes</button></td>\n")

            else:
                index_page.append("<td> <button id=\"" + str(node_doc["_id"]) + "\" alerting_state=\"" + str(node_doc["alerting_state"]) + "\" onclick=\"toggle_alerting_state(this.id)\">no</button></td>\n")

        except KeyError:
                index_page.append("<td> <button id=\"" + str(node_doc["_id"]) + "\" alerting_state=\"unknown\" onclick=\"toggle_alerting_state(this.id)\">unknown</button></td>\n")





        #
        # Node number
        #
        if "master_state" in node_doc and (node_doc["master_state"] == "down" or node_doc["master_state"] == "error"):
            index_page.append("<td><a href=\"/beomon/node/" + str(node_doc["_id"]) + "\">n" + str(node_doc["_id"]) + "</a></td>\n")

        else:
            index_page.append("<td><a href=\"/beomon/node/" + str(node_doc["_id"]) + "\">n" + str(node_doc["_id"]) + "</a></td>\n")





        #
        # Master state
        #
        if node_doc["_id"] == 242:
            index_page.append("<td>up</td>\n")

        elif "master_state" not in node_doc:
            index_page.append("<td style=\"font-weight:bold;color:red;\">unknown</td>\n")

            for _ in range(3):
                index_page.append("<td></td>")

            continue

        elif node_doc["master_state"] == "up":
            index_page.append("<td>up</td>\n")

        else:
            index_page.append("<td colspan='4'><span style='font-weight:bold;'>" + "In master state '" + node_doc["master_state"] + "' since " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(node_doc["master_state_time"])) + "</span></td>\n")

            continue





        #
        # Stale data?
        #

        try:
            if int(time.time()) - node_doc["last_checkin"] > 60 * 30:
                index_page.append("<td colspan='3' style=\"font-weight:bold;color:red;\">Stale data</td>\n")

                continue

        except KeyError:
            # We'll get here if the node never checked in but a master node added its rack location and state
            index_page.append("<td colspan='3' style=\"font-weight:bold;color:red;\">Missing data</td>\n")

            continue





        #
        # Torque
        #

        if "torque_state" not in node_doc:
            index_page.append("<td style=\"font-weight:bold;color:red;\">unknown</td>\n")

        elif node_doc["torque_state"] is True:
            index_page.append("<td>ok</td>\n")

        else:
            index_page.append("<td style=\"font-weight:bold;color:red;\">down</td>\n")





        #
        # Infiniband
        #

        if "infiniband" not in node_doc:
            index_page.append("<td style=\"font-weight:bold;color:red;\">unknown</td>\n")

        elif node_doc["infiniband"] is True:
            index_page.append("<td>ok</td>\n")

        else:
            index_page.append("<td style=\"font-weight:bold;color:red;\">down</td>\n")





        #
        # Tempurature
        #

        #tempurature = compute_query("tempurature", node_doc)
        #if tempurature == None:
            #index_page.append("<td style=\"font-weight:bold;color:red;\">unknown</td>\n")

        #else:
            #index_page.append("<td>" + tempurature + "</td>\n")





        #
        # Filesystems
        #

        filesystems = [
            "datapkg",
            "datasam",
            "gscratch1",
            "home0",
            "home1",
            "home2",
            "panasas",
            "scratch",
        ]

        try:
            filesystems_all_good = True
            for filesystem, state in node_doc["filesystems"].items():
                if state is not True:
                    filesystems_all_good = False

            if filesystems_all_good is True:
                index_page.append("<td>ok</td>\n")

            else:
                index_page.append("<td style=\"font-weight:bold;color:red;\">fail</td>\n")

        except KeyError:
            index_page.append("<td style=\"font-weight:bold;color:red;\">unknown</td>\n")



        index_page.append("</tr>\n")


    # End of compute detail table
    index_page.append("""
        </tbody>
    </table>
    </div> <!-- compute_detail -->
    """)



    # End of detail tables
    index_page.append("""
    </div> <!-- detail_outer -->
    """)



    # Footer
    index_page.append("""
    <script src="/static/jquery.stickytableheaders.js" type="text/javascript"></script>

    <script type="text/javascript">

                    $(document).ready(function () {
                            $("table").stickyTableHeaders();
                    });

    </script>
    </body>
    </html>
    """)



    return index_page





# Run the server
#run(host="0.0.0.0", port=8080, debug=True)
application = bottle.app()
