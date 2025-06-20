set dotenv-required
set dotenv-load

default:
    @just -l

init-run-ui-server:
    #!/bin/bash
    [ -f .env ] && echo "✅ 已初始化" || ([ -f example.env ] && mv example.env .env && echo "🚀 初始化完毕" || echo "❌ 初始化失败: example.env 不存在")

run-ui-server: init-run-ui-server
    uv run feedback_ui.py

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

