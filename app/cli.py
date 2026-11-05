"""Interactive REPL:  python -m app.cli"""
import uuid

from .engine import Text2SQLEngine


def main() -> None:
    engine = Text2SQLEngine()
    sid, options = uuid.uuid4().hex, []
    print("Text-to-SQL with clarification. Type a question, '/new' to reset, '/quit' to exit.\n")
    while True:
        msg = input("you> ").strip()
        if msg in ("/quit", "/exit"):
            break
        if msg == "/new":
            sid, options = uuid.uuid4().hex, []
            continue
        if not msg:
            continue
        if options and msg.isdigit() and 1 <= int(msg) <= len(options):
            msg = options[int(msg) - 1]
        r = engine.ask(sid, msg)
        options = r.options
        if r.status == "needs_clarification":
            print(f"\nbot> {r.clarification_question}")
            for i, o in enumerate(r.options, 1):
                print(f"     {i}. {o}")
            print()
        elif r.status == "answered":
            print(f"\nSQL: {r.sql}\n{r.explanation}\n")
            print(" | ".join(r.columns))
            for row in r.rows[:20]:
                print(" | ".join(str(v) for v in row))
            print(f"({len(r.rows)} rows)\n")
            sid = uuid.uuid4().hex
        else:
            print(f"\n[error] {r.error}\n")
            sid = uuid.uuid4().hex


if __name__ == "__main__":
    main()
