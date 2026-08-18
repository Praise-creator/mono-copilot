import argparse

from copilot.cli import commands
from copilot.orchestrator import Orchestrator
from copilot.tui.app import CopilotApp
from copilot.tui.state import Message


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
    chat = sub.add_parser("chat")
    chat.add_argument("--project", required=False, help="Open this project in the TUI")
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
        

        app = CopilotApp()

        project = getattr(args, "project", None)
        if project:
            orch = Orchestrator()
            session = orch.context_manager.get_session(project)
            app.state_manager.state.active_project = project
            if session:
                app.state_manager.state.workflow_stage = session.get("stage")
                brd = (session.get("ba_output") or {}).get("markdown")
                prd = (session.get("pe_output") or {}).get("markdown")
                app.state_manager.state.current_document = brd or prd
                app.state_manager.add_message(
                    Message(role="Assistant", content=f"Resumed project '{project}' (stage: {session.get('stage')}).")
                )
            else:
                app.state_manager.add_message(
                    Message(role="Assistant", content=f"Opened project '{project}' — no persisted session found.")
                )

        app.run()
        return
    
    if args.cmd is None:
        app = CopilotApp()
        
        project = getattr(args, "project", None)
        if project:
            orch = Orchestrator()
            session = orch.context_manager.get_session(project)
            app.state_manager.state.active_project = project
            if session:
                app.state_manager.state.workflow_stage = session.get("stage")
                brd = (session.get("ba_output") or {}).get("markdown")
                prd = (session.get("pe_output") or {}).get("markdown")
                app.state_manager.state.current_document = brd or prd
                app.state_manager.add_message(
                    Message(role="Assistant", content=f"Resumed project '{project}' (stage: {session.get('stage')}).")
                )
            else:
                app.state_manager.add_message(
                    Message(role="Assistant", content=f"Opened project '{project}' — no persisted session found.")
                )
        
        app.run()
        return

    print("Unknown command")


if __name__ == "__main__":
    main()