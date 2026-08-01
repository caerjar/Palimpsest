"""Enable `python -m palimpsest …` as an alias for the `pal` command."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
