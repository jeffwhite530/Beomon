<!DOCTYPE html>
<html>
    <head>
        <link href="/static/style.css" media="all" rel="stylesheet" type="text/css">
        <title>Node {{ node_doc["_id"] }}</title>
        %import locale
    </head>



    <body>
        <span style="font-size: 150%;font-weight: bold;">Node {{ node_doc["_id"] }}</span><br><br>


        <!-- Health information -->
        <span style="font-size: 125%;font-weight: bold;">Health:</span><br>
        %if node_doc["alerting_state"] == True:
            Alerting: enabled<br>

        %else:
            <span style="color:red">Alerting: disabled</span><br>

        %end


        %if node_doc["master_state"] == "up":
            Master state: up (since {{ node_doc["master_state_time"] }})<br>

        %else:
            <span style="color:red">Master state: {{ node_doc["master_state"] }} (since {{ node_doc["master_state_time"] }})</span><br>

        %end


        %if node_doc["torque_state"] is True:
            Torque State: ok<br>

        %else:
            <span style="color:red">Torque state: fail</span><br>

        %end



        %if node_doc["infiniband"] is True:
            Infiniband: ok<br>

        %else:
            <span style="color:red">Infiniband: fail</span><br>

        %end


        %filesystems_all_good = True
        %for filesystem, state in node_doc["filesystems"].items():
            %if state is not True:
                %filesystems_all_good = False

                <span style="color:red">{{ filesystem }}: fail</span><br>

            %end
        %end

        %if filesystems_all_good is True:
            Filesystems: ok<br>
        %end

        Last Health Check: {{ node_doc["last_health_check"] }}<br>
        Last Check-in: {{ node_doc["last_checkin"] }}<br>

        <br>


        <!-- Basic information of the node -->
        <span style="font-size: 125%;font-weight: bold;">Info:</span><br>
        CPU:<br>
            &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Type: {{ node_doc["cpu"]["cpu_type"] }}<br>
            &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Cores: {{ node_doc["cpu"]["cpu_num"] }}<br>
        GPU:<br>
            %if node_doc["gpu"]["num_cards"] != 0:
                &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;GPU Type: {{ node_doc["gpu"]["gpu_type"] }}<br>
                &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Cards: {{ node_doc["gpu"]["num_cards"] }}<br>
                &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Total RAM Size: {{ node_doc["gpu"]["ram_size"] }} GB<br>
                &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Total GPU Cores: {{ node_doc["gpu"]["num_cores"] }}<br>
            %else:
                &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;None<br>
            %end
        IPs:<br>
            &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;GigE IP: {{ node_doc["ip"]["gige"] }}<br>
            &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;BMC IP: {{ node_doc["ip"]["bmc"] }}<br>
            &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;IB IP: {{ node_doc["ip"]["ib"] }}<br>
        RAM: {{ node_doc["ram"] }} GB<br>
        Scratch Size: {{ node_doc["scratch_size"] }} GB<br>
        Rack: {{ node_doc["rack"]}}<br>
        Serial: {{ node_doc["serial"] }}<br>

        <br>


        <!-- Journal section -->
        <span style="font-size: 125%;font-weight: bold;">Journal:</span><br>
        %if len(node_doc["journal"]) > 0:
            %for entry in node_doc["journal"]:
                <div style="background: #DEDEDE; width: 500px; padding: 5px; border: 3px solid black; border-radius: 5px;">
                    {{! entry["entry"] }}<br>
                    <span style="font-size: 75%;">{{ entry["time"] }}</span>
                </div>
                <br>
            %end
        %else:
            <div style="background: #DEDEDE; width: 500px; padding: 5px; border: 3px solid black; border-radius: 5px;">
                No journal entries
            </div>
        %end

        <br>
        New journal entry:
        <form action="/beomon/node/{{node_doc['_id']}}/journal" method="post">
            <textarea cols="75" rows="10" name="entry"></textarea><br>
            <input value="Add to journal" type="submit">
        </form>

    </body>
</html>
