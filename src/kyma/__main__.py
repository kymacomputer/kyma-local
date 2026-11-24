import os
import sys

if sys.argv[1:] == ["hook"]:
    # the hook runs on every tool call: straight to it, without the CLI and argparse
    os.umask(0o077)
    from .enforce import hook
    sys.exit(hook())
from .cli import main  # noqa: E402
sys.exit(main())
