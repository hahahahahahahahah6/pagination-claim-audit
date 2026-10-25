def fetch(page=1):
    return {"next_page_token": None}

resp = fetch(page=1)
while resp["next_page_token"]:
    resp = fetch(page_token=resp["next_page_token"])
