import os

import dropbox
from dotenv import load_dotenv

load_dotenv()

dbx = dropbox.Dropbox(
    oauth2_refresh_token=os.environ["DROPBOX_REFRESH_TOKEN"],
    app_key=os.environ["DROPBOX_APP_KEY"],
    app_secret=os.environ["DROPBOX_APP_SECRET"],
)

# Use "" to test the Dropbox root, or a path such as "/Reports".
folder = os.getenv("DROPBOX_TEST_FOLDER", "")

result = dbx.files_list_folder(folder, recursive=False, limit=1)

print("Success: Dropbox authenticated and the folder is accessible.")
print(f"Returned {len(result.entries)} item(s) on this page.")