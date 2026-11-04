"""Local stdio MCP tools. The connected host supplies its own model judgment."""
from functools import wraps

from .agent_workflow import (
    prepare_contract_job,
    prepare_revision_job,
    read_contract_result,
    read_contract_source,
    submit_contract_assessment,
)


def create_server():
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

    def anticipated_errors(function):
        @wraps(function)
        def invoke(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except (AssertionError, ValueError, FileNotFoundError) as error:
                raise ToolError(str(error)) from error
        return invoke

    server = MCPServer('Kyma Local')
    for tool in [prepare_contract_job, prepare_revision_job, read_contract_source, submit_contract_assessment, read_contract_result]:
        server.tool(structured_output=True)(anticipated_errors(tool))
    return server


def main():
    try:
        server = create_server()
    except ImportError as error:
        raise SystemExit('Install the MCP extra: python3 scripts/bootstrap.py --mcp') from error
    server.run(transport='stdio')


if __name__ == '__main__':
    main()
