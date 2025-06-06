default:
    @just -l

run-ui-server:
    uv run fastapi dev feedback_ui.py

inspect:
    npx @modelcontextprotocol/inspector uv run server.py 

gen-mcp-config-json:
    #!/bin/bash
    cat << EOF
      "interactive_feedback": {
        "command": "uv",
        "args": [
          "--directory",
          "$PWD",
          "run",
          "server.py"
        ],
        "timeout": 3600,
        "autoApprove": [
          "interactive_feedback"
        ]
      },
    EOF

