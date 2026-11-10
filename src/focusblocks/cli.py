"""Command line.

  focusblocksw                   floating pill + tracker (no console)
  focusblocks                    same, with console log (for testing)
  focusblocks --nogui            tracker only
  focusblocks --test             test mode: 1-min blocks, 30-s breaks, separate data,
                                 plus a Test menu to jump to any moment
  focusblocks report [name]      build a report (default: heatmap) and open it

Settings: %USERPROFILE%\\.focusblocks\\config.json (created on first run).
          Edit it, then right-click the pill -> Reload settings.
"""

from __future__ import annotations

import sys

from focusblocks.logging_setup import configure_logging

COMMANDS = ("", "--nogui", "report")


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return
    test_mode = "--test" in args
    if test_mode:
        args.remove("--test")
    command = args[0] if args else ""
    if command not in COMMANDS:
        print(f"focusblocks: unknown command: {command}", __doc__, sep="\n", file=sys.stderr)
        sys.exit(2)

    from focusblocks.paths import AppPaths
    configure_logging(log_file=(AppPaths.test() if test_mode else AppPaths.default()).log)
    from focusblocks.app import DEFAULT_REPORT, Application
    app = Application.create(test_mode=test_mode)
    if command == "report":
        name = args[1] if len(args) > 1 else DEFAULT_REPORT
        try:
            app.open_report(name)
        except KeyError as e:
            sys.exit(str(e.args[0]))
        return
    app.run(gui=command != "--nogui")
