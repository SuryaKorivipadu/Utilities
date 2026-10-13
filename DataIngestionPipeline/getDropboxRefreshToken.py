import os

import dropbox
from dotenv import load_dotenv

load_dotenv()

app_key = os.environ["DROPBOX_APP_KEY"]
app_secret = os.environ["DROPBOX_APP_SECRET"]

flow = dropbox.DropboxOAuth2FlowNoRedirect(
    app_key,
    app_secret,
    token_access_type="offline",
    scope=["files.metadata.read"],
)

print("Open this URL in your browser and sign in to the Dropbox account:")
print(flow.start())

authorization_code = input("Paste the authorization code Dropbox gives you: ").strip()
result = flow.finish(authorization_code)

print("\nAccess token (short-lived; SDK can refresh it):")
print(result.access_token)

print("\nRefresh token (store securely for Airflow):")
print(result.refresh_token)