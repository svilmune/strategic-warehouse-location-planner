"""Create a new Foundry agent version from agents/<dir>/agent.json.

Usage:
  python scripts/deploy_agent.py <agent-dir> [--dry-run] [--name <agent-name>]

--dry-run  render the definition and diff it against the live latest version; no changes made.
--name     deploy under a different agent name (e.g. a test copy).
"""
import argparse
import copy
import difflib
import json

from common import AGENTS, ROOT, Foundry, from_placeholders, load_env


def render(dirname: str, env: dict):
    base = ROOT / "agents" / dirname
    template = json.loads(from_placeholders((base / "agent.json").read_text(), env))
    definition = template["definition"]
    definition["instructions"] = from_placeholders(
        (base / definition["instructions"]["$file"]).read_text(), env)
    for tool in definition["tools"]:
        if tool["type"] == "openapi":
            spec_file = (base / tool["openapi"]["spec"]["$file"]).resolve()
            tool["openapi"]["spec"] = json.loads(from_placeholders(spec_file.read_text(), env))
    return template, base


def normalise(definition: dict, file_names=None) -> dict:
    """Replace uploaded file ids with file names so repo and live definitions compare."""
    d = copy.deepcopy(definition)
    for tool in d.get("tools", []):
        c = tool.get("container")
        if tool["type"] == "code_interpreter" and c is not None:
            if "file_ids" in c:
                c["files"] = sorted(file_names[f] for f in c.pop("file_ids"))
            else:
                c["files"] = sorted(p.split("/")[-1] for p in c.get("files", []))
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agent", choices=sorted(AGENTS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--name")
    args = ap.parse_args()

    env = load_env()
    foundry = Foundry(env["FOUNDRY_PROJECT_ENDPOINT"])
    template, base = render(args.agent, env)
    name = args.name or template["name"]
    definition = template["definition"]

    if args.dry_run:
        live = foundry.latest_version(template["name"])
        ids = [f for t in live["definition"]["tools"] if t["type"] == "code_interpreter"
               for f in t.get("container", {}).get("file_ids", [])]
        names = {f: foundry.file_meta(f)["filename"] for f in ids}
        a = json.dumps(normalise(live["definition"], names), indent=2, sort_keys=True).splitlines()
        b = json.dumps(normalise(definition), indent=2, sort_keys=True).splitlines()
        diff = list(difflib.unified_diff(a, b, f"live v{live['version']}", "repo", lineterm=""))
        print("\n".join(diff) if diff else f"IDENTICAL to live v{live['version']}")
        return

    for tool in definition["tools"]:
        if tool["type"] == "code_interpreter":
            tool["container"]["file_ids"] = [foundry.upload_file(base / p)
                                             for p in tool["container"].pop("files", [])]
    r = foundry.create_version(name, {"definition": definition,
                                      "description": template.get("description"),
                                      "metadata": template.get("metadata")})
    print(f"{name}: created version {r['version']}")


if __name__ == "__main__":
    main()
