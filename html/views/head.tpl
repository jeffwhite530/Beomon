<!DOCTYPE html>
<html>
    <head>
        <link href="/static/style.css" media="all" rel="stylesheet" type="text/css">
        <title>{{ node_doc["_id"] }}</title>
    </head>



    <body>
        <span style="font-size: 150%;font-weight: bold;">Node {{ node_doc["_id"] }}</span><br><br>


        <!-- Health information -->
        <span style="font-size: 125%;font-weight: bold;">Health:</span><br>
        %processes_all_good = True
        %for process, state in node_doc["processes"].items():
            %if state is False:
                %processes_all_good = False

                <span style="color:red">{{ process }} : fail</span><br>

            %end

        %end

        %if processes_all_good is True:
            State: ok<br>

        %else:
            <span style="color:red">State: fail</span><br>

        %end


        Load average 1 minute: {{ node_doc["loadavg"]["1"] }}<br>
        Load average 5 minutes: {{ node_doc["loadavg"]["5"] }}<br>
        Load average 15 minutes: {{ node_doc["loadavg"]["15"] }}<br>

        %if len(bad_files) == 0:
            File mismatch check: ok<br>

        %else:
            File mismatch check:<br>
            %for each_file in bad_files:
                <span style="color:red">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Does not match head0a: {{ each_file }}</span><br>
            %end

        %end

        Last Check-in: {{ node_doc["last_checkin"] }}<br>

        <br>


        <!-- Basic information of the node -->
        <span style="font-size: 125%;font-weight: bold;">Info:</span><br>
        Class: {{ node_doc["compute_node_class"] }}<br>
        Primary of: {{ node_doc["primary_of"] }}<br>
        Secondary of: {{ node_doc["secondary_of"] }}<br>

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
        <form action="/beomon/head/{{node_doc['_id']}}/journal" method="post">
            <textarea cols="75" rows="10" name="entry"></textarea><br>
            <input value="Add to journal" type="submit">
        </form>

    </body>
</html>
