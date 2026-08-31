from pathlib import Path
import json

def build(blueprint, output_path):
    params = blueprint["parameters"]
    title = params["title"]
    description = params["description"]
    Path(output_path).write_text(
        "title: " + json.dumps(title, ensure_ascii=False) + "\n"
        "description: " + json.dumps(description, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
