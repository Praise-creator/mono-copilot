import argparse
from copilot.cli import commands


def parse_args():
    p = argparse.ArgumentParser(prog="mono")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("projects")
    show = sub.add_parser("show")
    show.add_argument("what", choices=["brd", "prd", "sources"])
    show.add_argument("--project", required=True)
    start = sub.add_parser("start")
    start.add_argument("--project", required=True)
    start.add_argument("--problem", required=True)
    start.add_argument("--segment", default="")
    start.add_argument("--dry-run", action="store_true", help="Create session without calling agents")
    approve = sub.add_parser("approve")
    approve.add_argument("--project", required=True)
    approve.add_argument("--stage", required=True, choices=["ba", "pe", "rfc"])
    approve.add_argument("--decision", default="approve", choices=["approve", "needs_changes", "clarification", "jump_back_to_ba"])
    feedback = sub.add_parser("feedback")
    feedback.add_argument("--project", required=True)
    feedback.add_argument("--stage", required=True, choices=["ba", "pe", "rfc"])
    feedback.add_argument("--message", required=True)
    sub.add_parser("chat")
    return p.parse_args()


def main():
    args = parse_args()

    if args.cmd == "projects":
        res = commands.list_projects()
        print("\n".join(res or ["(no persisted projects)"]))
        return

    if args.cmd == "show":
        if args.what == "brd":
            print(commands.show_brd(args.project) or "(no BRD found)")
        elif args.what == "prd":
            print(commands.show_prd(args.project) or "(no PRD found)")
        else:
            print(commands.show_sources(args.project) or "(no sources found)")
        return

    if args.cmd == "start":
        res = commands.start_headless(project=args.project, problem=args.problem, segment=args.segment, dry_run=getattr(args, "dry_run", False))
        print(res)
        return

    if args.cmd == "approve":
        res = commands.approve(project=args.project, stage=args.stage, decision=args.decision)
        print(res)
        return

    if args.cmd == "feedback":
        res = commands.feedback(project=args.project, stage=args.stage, message=args.message)
        print(res)
        return

    if args.cmd == "chat":
        print("TUI not implemented yet.")
        return

    print("Unknown command")


if __name__ == "__main__":
    main()