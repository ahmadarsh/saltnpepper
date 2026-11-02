"""Entry point shared by the bundled server and isolated solver workers."""
import sys

if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--worker':
        sys.argv.pop(1)
        from pcb_simulator.worker import main
    else:
        from pcb_simulator.server import main
    raise SystemExit(main())
