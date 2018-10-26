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
        %if node_doc["write_test"] is True:
            Filesystem writable: ok<br>

        %else:
            <span style="color:red">Filesystem writable: fail</span><br>

        %end


        Load average 1 minute: {{ node_doc["loadavg"]["1"] }}<br>
        Load average 5 minutes: {{ node_doc["loadavg"]["5"] }}<br>
        Load average 15 minutes: {{ node_doc["loadavg"]["15"] }}<br>


        KB Read per Second (Last 10 Minutes): {{ node_doc["kilobytes_read_per_second"] }}<br>
        KB Written per Second (Last 10 Minutes): {{ node_doc["kilobytes_written_per_second"] }}<br>
        Transactions per Second (Last 10 Minutes): {{ node_doc["transactions_per_second"] }}<br>

        <br>


        <!-- Basic information of the node -->
        <span style="font-size: 125%;font-weight: bold;">Info:</span><br>
        <div style="text-align: left; max-width: 600px;">
            Description: {{ node_doc["description"] }}<br>
            Data device: {{ node_doc["data_device"] }}<br>
            Data mount: {{ node_doc["data_mount"] }}<br>
            Client mount: {{ node_doc["client_mount"] }}<br>
        </div>

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
        <form action="/beomon/storage/{{node_doc['_id']}}/journal" method="post">
            <textarea cols="75" rows="10" name="entry"></textarea><br>
            <input value="Add to journal" type="submit">
        </form>

    </body>
</html>
