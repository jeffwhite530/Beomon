<!DOCTYPE html>
<html>
    <head>
        <link href="/static/style.css" media="all" rel="stylesheet" type="text/css">
        <title>Node {{ node_doc["_id"] }}</title>
    </head>



    <body>
        <h2>Node {{ node_doc["_id"] }}</h2>

        %for entry in node_doc["journal"]:
            <div style="text-align: left; max-width: 300px;">
                <div style="background:gainsboro;">
                    {{ entry["time"] }}
                </div>

                <div>
                    {{ entry["entry"] }}
                </div>
                 <hr style="height: 5px; background: black;">
            </div>
        %end

    </body>
</html>
