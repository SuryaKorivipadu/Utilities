servicenow_incidents_csv = """incident_number,priority,state,category,assigned_group,short_description
INC0010001,1,Critical,Network,Network Operations,"VPN connectivity failures across regional offices"
INC0010002,2,In Progress,Application,ERP Support,"ERP monthly reconciliation report timeouts"
INC0010003,3,Open,Hardware,End User Computing,"Laptop performance issues after OS update"
INC0010004,2,Resolved,Database,Database Services,"Database replication latency detected"
INC0010005,4,Pending,Security,Security Operations,"Suspicious authentication attempts on service accounts"
INC0010006,1,In Progress,Cloud,Cloud Platform Team,"Production cloud API response failures"
INC0010007,3,Open,Email,Messaging Services,"Delayed email delivery across organization"
INC0010008,2,Monitoring,Storage,Infrastructure Services,"Storage array predictive failure alerts"
INC0010009,4,Closed,Service Request,IT Operations,"Self-service password reset enhancement request"
INC0010010,2,Investigating,Monitoring,Observability Team,"Duplicate infrastructure monitoring alerts"
"""
headings = servicenow_incidents_csv.split("\n")[0]
max_chars_chunk = 400
chunk = headings + "\n"
chunk_num = 1
for line in servicenow_incidents_csv.split("\n")[1:]:
    if len(chunk) + len(line) <= max_chars_chunk:
        chunk += line + "\n"
    else:
        print(f"\n\nChunk num: {chunk_num}, chunk length: {len(chunk)}\nChunk:\n{chunk}")
        chunk = headings + "\n" + line + "\n"
        chunk_num += 1
print(f"\n\nChunk num: {chunk_num}, chunk length: {len(chunk)}\nChunk:\n{chunk}")
print("done")