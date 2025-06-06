# Interactive Feedback MCP
# Developed by Fábio Ferreira (https://x.com/fabiomlferreira)
# Inspired by/related to dotcursorrules.com (https://dotcursorrules.com/)
import os
import sys
import json
# import tempfile # No longer needed for output file
# import subprocess # No longer needed for subprocess
import httpx # For making HTTP requests

from typing import Annotated, Dict

from fastmcp import FastMCP
from pydantic import Field

# The log_level is necessary for Cline to work: https://github.com/jlowin/fastmcp/issues/81
mcp = FastMCP("Interactive Feedback MCP", log_level="ERROR")

# Define the API endpoint URL
# You might want to make this configurable (e.g., via environment variable)
FEEDBACK_API_URL = "http://localhost:8000/run_feedback_ui/"
# Define a long timeout for the API request (e.g., 1 hour = 3600 seconds)
# Adjust as needed based on how long you expect the UI interaction to take.
API_TIMEOUT_SECONDS = 3600.0

def launch_feedback_ui_via_api(project_directory: str, summary_prompt: str) -> dict[str, str]:
    """
    Launches the feedback UI by calling the FastAPI service.
    """
    payload = {
        "project_directory": project_directory,
        "prompt": summary_prompt
        # "server_save_path" is optional in the API; omitting it here.
        # If you need to save on the server, you can add it:
        # "server_save_path": "/path/on/server/to/save/result.json"
    }

    try:
        print(f"Calling Feedback API at {FEEDBACK_API_URL} with payload: {payload}")
        with httpx.Client(timeout=API_TIMEOUT_SECONDS) as client:
            response = client.post(FEEDBACK_API_URL, json=payload)
        
        # Check if the request was successful
        response.raise_for_status()  # Raises an HTTPStatusError for 4xx/5xx responses

        # Parse the JSON response
        result = response.json()
        print(f"Received response from Feedback API: {result}")
        return result

    except httpx.HTTPStatusError as e:
        # Handle HTTP errors (e.g., 404, 500, 422 for validation errors from FastAPI)
        error_message = f"API request failed with status {e.response.status_code}: {e.response.text}"
        print(f"Error: {error_message}")
        # You might want to return a specific error structure or re-raise a custom exception
        raise Exception(error_message) from e
    except httpx.RequestError as e:
        # Handle other request errors (e.g., network issues, timeout)
        error_message = f"API request failed: {str(e)}"
        print(f"Error: {error_message}")
        raise Exception(error_message) from e
    except json.JSONDecodeError as e:
        error_message = f"Failed to decode JSON response from API: {str(e)}"
        print(f"Error: {error_message} - Response text: {response.text if 'response' in locals() else 'N/A'}")
        raise Exception(error_message) from e
    except Exception as e:
        # Catch any other unexpected errors
        error_message = f"An unexpected error occurred while calling the feedback API: {str(e)}"
        print(f"Error: {error_message}")
        raise Exception(error_message) from e


def first_line(text: str) -> str:
    return text.split("\n")[0].strip()

@mcp.tool()
def interactive_feedback(
    project_directory: Annotated[str, Field(description="Full path to the project directory")],
    summary: Annotated[str, Field(description="Short, one-line summary of the changes (will be shown as a prompt in the UI)")],
) -> Dict[str, str]:
    """Request interactive feedback for a given project directory and summary by calling a remote UI service."""
    # The 'summary' from the tool maps to the 'prompt' in the API request.
    return launch_feedback_ui_via_api(first_line(project_directory), first_line(summary))

if __name__ == "__main__":
    # Example of how to test the tool directly (optional)
    # This requires the FastAPI service (from fastapi_pyside_feedback) to be running.
    # if len(sys.argv) > 1 and sys.argv[1] == "test":
    #     try:
    #         test_dir = os.getcwd()
    #         test_summary = "This is a test run of the interactive feedback tool via API."
    #         print(f"Testing interactive_feedback tool with dir='{test_dir}', summary='{test_summary}'")
    #         feedback_result = interactive_feedback(project_directory=test_dir, summary=test_summary)
    #         print("\n--- Feedback Result ---")
    #         print(f"Logs: {feedback_result.get('logs', 'N/A')}")
    #         print(f"Interactive Feedback: {feedback_result.get('interactive_feedback', 'N/A')}")
    #         print("--- End of Test ---")
    #     except Exception as e:
    #         print(f"Test failed: {e}")
    # else:
    #     mcp.run(transport="stdio")
    mcp.run(transport="stdio")

