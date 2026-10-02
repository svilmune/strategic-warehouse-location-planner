import json
import os
import subprocess
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = {
    "warehouse-recommendation": "Hackathon-Oracle-Warehouse-Recommendation-Agent",
    "geo-postal-code": "Hackathon-Oracle-Geo-Postal-code-generator",
}
# Values swapped for ${NAME} on export and restored on deploy, longest first.
PLACEHOLDERS = [
    "FOUNDRY_PROJECT_ENDPOINT",
    "MCP_SHIM_HOST",
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_TENANT_ID",
    "AZURE_MAPS_CLIENT_ID",
]
API = "api-version=v1"


def load_env() -> dict:
    env = dict(os.environ)
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    return env


def to_placeholders(text: str, env: dict) -> str:
    pairs = sorted(((env[k], k) for k in PLACEHOLDERS if env.get(k)), key=lambda p: -len(p[0]))
    for value, name in pairs:
        text = text.replace(value, "${" + name + "}")
    return text


def from_placeholders(text: str, env: dict) -> str:
    for name in PLACEHOLDERS:
        token = "${" + name + "}"
        if token in text:
            if not env.get(name):
                raise SystemExit(f"{name} is used by the templates but not set in .env")
            text = text.replace(token, env[name])
    return text


class Foundry:
    def __init__(self, endpoint: str):
        self.base = endpoint.rstrip("/")
        self.token = subprocess.check_output(
            ["az", "account", "get-access-token", "--resource", "https://ai.azure.com",
             "--query", "accessToken", "-o", "tsv"], text=True).strip()

    def _req(self, method, path, body=None, headers=None, raw=False):
        req = urllib.request.Request(f"{self.base}{path}", data=body, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            raise SystemExit(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:500]}")
        return data if raw else json.loads(data)

    def latest_version(self, agent: str) -> dict:
        return self._req("GET", f"/agents/{agent}?{API}")["versions"]["latest"]

    def file_meta(self, fid: str) -> dict:
        return self._req("GET", f"/openai/v1/files/{fid}")

    def file_content(self, fid: str) -> bytes:
        return self._req("GET", f"/openai/v1/files/{fid}/content", raw=True)

    def upload_file(self, path: Path) -> str:
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nassistants\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        r = self._req("POST", "/openai/v1/files", body,
                      {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        return r["id"]

    def create_version(self, agent: str, payload: dict) -> dict:
        return self._req("POST", f"/agents/{agent}/versions?{API}", json.dumps(payload).encode(),
                         {"Content-Type": "application/json"})
