"""The HTTP API package (spec 007).

Deliberately doesn't re-export `app` here -- importing `api.auth` or
`api.jobs` on their own shouldn't trigger `api.app`'s module-level
fail-fast token check. Run the server with `uvicorn api.app:app`.
"""
