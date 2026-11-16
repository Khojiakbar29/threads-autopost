"""Publish due Threads posts from posts/*/post.json.

Each post folder holds post.json:
{
  "publish_at": "2026-11-18T18:30:00+01:00",
  "parts": [
    {"text": "First post of the chain", "image": "image.png"},
    {"text": "Reply 2"},
    {"text": "Reply 3"}
  ]
}
Images are served from the public repo via raw.githubusercontent.com.
After publishing, published.json is written next to post.json and committed by the workflow.
"""
import json, os, sys, time, glob, datetime, urllib.parse, urllib.request

API = "https://graph.threads.net/v1.0"
TOKEN = os.environ["THREADS_TOKEN"]
USER_ID = os.environ.get("THREADS_USER_ID", "me")
REPO = os.environ["GITHUB_REPOSITORY"]
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
DRY = os.environ.get("DRY_RUN") == "1"


def call(method, path, params):
    params = dict(params, access_token=TOKEN)
    data = urllib.parse.urlencode(params).encode()
    url = f"{API}/{path}"
    if method == "GET":
        req = urllib.request.Request(url + "?" + data.decode())
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path}: {e.code} {e.read().decode()[:500]}")


def wait_ready(container_id):
    for _ in range(30):
        st = call("GET", container_id, {"fields": "status,error_message"})
        if st.get("status") == "FINISHED":
            return
        if st.get("status") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"container {container_id}: {st}")
        time.sleep(5)
    raise RuntimeError(f"container {container_id} not ready in time")


def publish_part(folder, part, reply_to=None):
    params = {"text": part["text"]}
    if part.get("image"):
        rel = os.path.relpath(os.path.join(folder, part["image"]))
        params["media_type"] = "IMAGE"
        params["image_url"] = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{urllib.parse.quote(rel)}"
    else:
        params["media_type"] = "TEXT"
    if reply_to:
        params["reply_to_id"] = reply_to
    if DRY:
        print("DRY", folder, params)
        return "dry"
    c = call("POST", f"{USER_ID}/threads", params)["id"]
    wait_ready(c)
    return call("POST", f"{USER_ID}/threads_publish", {"creation_id": c})["id"]


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    if DRY:
        me = call("GET", USER_ID, {"fields": "id,username"})
        print(f"connection ok: @{me.get('username')} (id {me.get('id')})")
    done_any = False
    for pj in sorted(glob.glob("posts/*/post.json")):
        folder = os.path.dirname(pj)
        if os.path.exists(os.path.join(folder, "published.json")):
            continue
        post = json.load(open(pj, encoding="utf-8"))
        if post.get("status", "approved") != "approved":
            continue
        when = datetime.datetime.fromisoformat(post["publish_at"])
        if when > now:
            continue
        for p in post["parts"]:
            if len(p["text"]) > 500:
                raise SystemExit(f"{folder}: part longer than 500 chars")
        ids, prev = [], None
        for p in post["parts"]:
            prev = publish_part(folder, p, reply_to=prev)
            ids.append(prev)
            time.sleep(3)
        link = None
        if not DRY:
            link = call("GET", ids[0], {"fields": "permalink"}).get("permalink")
        json.dump({"published_at": now.isoformat(), "ids": ids, "permalink": link},
                  open(os.path.join(folder, "published.json"), "w"), indent=2)
        print("published", folder, link)
        done_any = True
        break  # one post per run, keeps spacing between posts
    if not done_any:
        print("nothing due")


if __name__ == "__main__":
    main()
