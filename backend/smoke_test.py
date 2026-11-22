from app import create_app

app = create_app()
c = app.test_client()

r = c.post("/api/projects", json={"name": "Projet demo", "description": "validation"})
print("create project", r.status_code, r.get_json())
pid = r.get_json()["id"]

r = c.post(
    f"/api/projects/{pid}/targets",
    json={
        "name": "Demo local",
        "base_url": "http://127.0.0.1:5001/",
        "configuration": {
            "limits": {"max_pages": 6, "max_depth": 2, "max_duration_seconds": 60}
        },
    },
)
print("create target", r.status_code, r.get_json())
tid = r.get_json()["id"]

r = c.post(
    f"/api/targets/{tid}/campaigns",
    json={"objective": "Verifier inscription et navigation"},
)
print("create campaign", r.status_code, r.get_json())
cid = r.get_json()["id"]

r = c.post(f"/api/projects/{pid}/targets", json={"name": "bad", "base_url": "ftp://x"})
print("invalid url", r.status_code, r.get_json())
print("IDS", pid, tid, cid)
