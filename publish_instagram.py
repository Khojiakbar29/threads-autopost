"""Publish due Instagram posts from instagram/*/post.json (Instagram API with Instagram login).

post.json:
{
  "publish_at": "2026-11-19T18:30:00+01:00",
  "status": "approved",
  "type": "image" | "carousel" | "reel",
  "caption": "Text with #hashtags",
  "images": ["1.jpg", "2.jpg"],      # image: one file; carousel: 2-10 files (JPEG only)
  "video": "reel.mp4",                # reel only
  "cover": "cover.jpg"                # reel cover, optional
}
Files are served from the public repo via raw.githubusercontent.com.
After publishing, published.json is written next to post.json.
"""
import json, os, time, glob, datetime, urllib.parse, urllib.request

HOSTS = ["https://graph.instagram.com/v23.0", "https://graph.facebook.com/v23.0"]
API = HOSTS[0]
TOKEN = os.environ.get("IG_TOKEN", "")
USER_ID = os.environ.get("IG_USER_ID", "me")
REPO = os.environ["GITHUB_REPOSITORY"]
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
DRY = os.environ.get("DRY_RUN") == "1"


def call(method, path, params):
    params = dict(params, access_token=TOKEN)
    data = urllib.parse.urlencode(params).encode()
    url = f"{API}/{path}"
    req = urllib.request.Request(url + "?" + data.decode()) if method == "GET" else urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path}: {e.code} {e.read().decode()[:600]}")


def url_of(folder, name):
    rel = os.path.relpath(os.path.join(folder, name))
    return f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{urllib.parse.quote(rel)}"


def wait_ready(cid, tries=60, pause=5):
    for _ in range(tries):
        st = call("GET", cid, {"fields": "status_code,status"})
        if st.get("status_code") == "FINISHED":
            return
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"container {cid}: {st}")
        time.sleep(pause)
    raise RuntimeError(f"container {cid} not ready in time")


def create(params):
    if DRY:
        print("DRY create", params)
        return "dry"
    return call("POST", f"{USER_ID}/media", params)["id"]


def publish(folder, post):
    t, cap = post["type"], post.get("caption", "")
    if len(cap) > 2200:
        raise SystemExit(f"{folder}: caption longer than 2200 chars")
    for f in post.get("images", []):
        if not f.lower().endswith((".jpg", ".jpeg")):
            raise SystemExit(f"{folder}: Instagram accepts JPEG only ({f})")
    if t == "image":
        cid = create({"image_url": url_of(folder, post["images"][0]), "caption": cap})
    elif t == "carousel":
        kids = []
        for f in post["images"]:
            k = create({"image_url": url_of(folder, f), "is_carousel_item": "true"})
            if not DRY:
                wait_ready(k, tries=24)
            kids.append(k)
        cid = create({"media_type": "CAROUSEL", "children": ",".join(kids), "caption": cap})
    elif t == "reel":
        p = {"media_type": "REELS", "video_url": url_of(folder, post["video"]), "caption": cap}
        if post.get("share_to_feed") is not None:
            p["share_to_feed"] = "true" if post["share_to_feed"] else "false"
        if post.get("cover"):
            p["cover_url"] = url_of(folder, post["cover"])
        cid = create(p)
    else:
        raise SystemExit(f"{folder}: unknown type {t}")
    if DRY:
        return "dry", None
    wait_ready(cid, tries=120 if t == "reel" else 30)
    mid = call("POST", f"{USER_ID}/media_publish", {"creation_id": cid})["id"]
    link = call("GET", mid, {"fields": "permalink"}).get("permalink")
    return mid, link


def detect_host():
    """The token may belong to Instagram login or Facebook (business) login; pick the host that accepts it."""
    global API
    errors = []
    for h in HOSTS:
        API = h
        try:
            me = call("GET", USER_ID, {"fields": "username"})
            return me.get("username")
        except RuntimeError as e:
            errors.append(str(e)[:200])
    raise RuntimeError("token not accepted by any host: " + " | ".join(errors))


def main():
    if not TOKEN:
        print("IG_TOKEN not set, skipping Instagram")
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    user = detect_host()
    if DRY:
        print(f"instagram connection ok: @{user} via {API}")
    for pj in sorted(glob.glob("instagram/*/post.json")):
        folder = os.path.dirname(pj)
        if os.path.exists(os.path.join(folder, "published.json")):
            continue
        post = json.load(open(pj, encoding="utf-8"))
        if post.get("status", "approved") != "approved":
            continue
        if datetime.datetime.fromisoformat(post["publish_at"]) > now:
            continue
        # avoid duplicates: if a recent post already has this caption, just mark it
        head = post.get("caption", "")[:60]
        recent = call("GET", f"{USER_ID}/media", {"fields": "id,caption,permalink,timestamp", "limit": "5"}).get("data", [])
        dup = next((m for m in recent if head and (m.get("caption") or "").startswith(head)), None)
        if dup:
            json.dump({"published_at": dup.get("timestamp"), "id": dup["id"], "permalink": dup.get("permalink"), "note": "found already published"},
                      open(os.path.join(folder, "published.json"), "w"), indent=2)
            print("instagram already published", folder, dup.get("permalink"))
            return
        attempts = 3
        for n in range(attempts):
            try:
                mid, link = publish(folder, post)
                break
            except RuntimeError as e:
                if "media_publish" in str(e) and n < attempts - 1:
                    print("publish failed, retrying in 60s:", str(e)[:200])
                    time.sleep(60)
                    recent = call("GET", f"{USER_ID}/media", {"fields": "id,caption,permalink,timestamp", "limit": "5"}).get("data", [])
                    dup = next((m for m in recent if head and (m.get("caption") or "").startswith(head)), None)
                    if dup:
                        mid, link = dup["id"], dup.get("permalink")
                        break
                    continue
                raise
        if not DRY:
            json.dump({"published_at": now.isoformat(), "id": mid, "permalink": link},
                      open(os.path.join(folder, "published.json"), "w"), indent=2)
        print("instagram published", folder, link)
        return
    print("instagram: nothing due")


if __name__ == "__main__":
    main()
