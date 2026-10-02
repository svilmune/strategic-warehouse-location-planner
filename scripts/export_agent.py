"""Export the latest version of each hackathon agent from Foundry into agents/<dir>/.

Usage: python scripts/export_agent.py [agent-dir ...]   (default: all agents)
"""
import copy
import json
import sys

from common import AGENTS, ROOT, Foundry, load_env, to_placeholders

DROP_METADATA = {"modified_at"}


def write(path, text, env):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_placeholders(text, env))


def export(foundry, env, dirname, agent_name):
    latest = foundry.latest_version(agent_name)
    out = ROOT / "agents" / dirname
    definition = copy.deepcopy(latest["definition"])

    write(out / "instructions.md", definition["instructions"], env)
    definition["instructions"] = {"$file": "instructions.md"}

    for tool in definition.get("tools", []):
        if tool["type"] == "openapi":
            spec_path = ROOT / "tools" / "openapi" / f"{tool['openapi']['name']}.json"
            text = json.dumps(tool["openapi"]["spec"], indent=2) + "\n"
            if spec_path.exists() and spec_path.read_text() != to_placeholders(text, env):
                spec_path = spec_path.with_name(f"{tool['openapi']['name']}.{dirname}.json")
            write(spec_path, text, env)
            tool["openapi"]["spec"] = {"$file": f"../../tools/openapi/{spec_path.name}"}
        elif tool["type"] == "code_interpreter":
            files = []
            for fid in tool.get("container", {}).pop("file_ids", []):
                name = foundry.file_meta(fid)["filename"]
                data = foundry.file_content(fid)
                try:
                    write(out / "files" / name, data.decode("utf-8"), env)
                except UnicodeDecodeError:  # e.g. the UTF-16 Census Gazetteer; stored byte-for-byte
                    (out / "files").mkdir(parents=True, exist_ok=True)
                    (out / "files" / name).write_bytes(data)
                files.append(f"files/{name}")
            tool.setdefault("container", {})["files"] = files

    template = {
        "name": agent_name,
        "exported_from_version": latest["version"],
        "description": latest.get("description"),
        "metadata": {k: v for k, v in (latest.get("metadata") or {}).items() if k not in DROP_METADATA},
        "definition": definition,
    }
    write(out / "agent.json", json.dumps(template, indent=2) + "\n", env)
    print(f"{agent_name}: exported v{latest['version']} -> agents/{dirname}/")


def main():
    env = load_env()
    foundry = Foundry(env["FOUNDRY_PROJECT_ENDPOINT"])
    targets = sys.argv[1:] or list(AGENTS)
    (ROOT / "tools" / "openapi").mkdir(parents=True, exist_ok=True)
    if set(targets) == set(AGENTS):
        for spec in (ROOT / "tools" / "openapi").glob("*.json"):
            spec.unlink()
    for d in targets:
        export(foundry, env, d, AGENTS[d])


if __name__ == "__main__":
    main()
