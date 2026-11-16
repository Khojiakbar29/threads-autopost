# threads-autopost

Approved Threads posts for the personal page. GitHub Actions publishes them on time.

- `posts/<date>-<slug>/post.json` — text parts (a chain), optional image, `publish_at` (ISO time with timezone).
- `published.json` appears next to it after publishing (ids + link).
- Only posts with `"status": "approved"` (default) are published; set `"draft"` to hold one.
- Runs every 30 min; at most one post per run.
- Secrets: `THREADS_TOKEN`, `THREADS_USER_ID`, `GH_PAT` (for token refresh).
- Manual test: Actions → "Publish due Threads posts" → Run workflow with dry_run = 1.

Note: the repo is public so Threads can download images by URL. Do not put anything private here.
