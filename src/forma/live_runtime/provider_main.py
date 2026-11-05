"""One provider process. It loads only the assignment file it is given."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import uvicorn

from forma.live_runtime.server import ProviderExecutor, make_card, service_app


def main() -> None:
    config = json.loads(Path(sys.argv[1]).read_text())
    url = f"http://127.0.0.1:{config['port']}"
    description = (
        f"Provider {config['agent_id']} for role {config['role']}. "
        f"Owns {', '.join(config['owned_attribute_ids'])}."
    )
    card = make_card(config["agent_id"], url, "perform_delegated_task", description)
    app = service_app(config.get("id_prefix") or config["agent_id"], card, ProviderExecutor(config))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=config["port"], log_level="error", access_log=False))
    server.run()


if __name__ == "__main__":
    main()
