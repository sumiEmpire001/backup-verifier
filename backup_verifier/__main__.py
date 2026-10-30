import argparse
import json
from .backup import create, verify, restore


def main():
    parser = argparse.ArgumentParser(description="Create, verify and rehearse directory backups")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "restore"):
        sub = commands.add_parser(name)
        sub.add_argument("source")
        sub.add_argument("destination")
    sub = commands.add_parser("verify")
    sub.add_argument("source")
    args = parser.parse_args()
    try:
        result = verify(args.source) if args.command == "verify" else {"create": create, "restore": restore}[args.command](args.source, args.destination)
        print(json.dumps(result, indent=2))
        if result.get("valid") is False:
            raise SystemExit(1)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
