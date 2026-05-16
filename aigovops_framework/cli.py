"""CLI entry point for the AIGovOps Agent Framework.

Usage:
    aigovops init          # Create a new project from template
    aigovops run           # Start the framework
    aigovops run --dry-run # Start in dry-run mode
    aigovops test          # Send a test event
    aigovops status        # Show framework status
    aigovops agents        # List loaded agents
    aigovops audit         # Show recent audit log
"""

from __future__ import annotations

import sys


def main() -> None:
    """CLI entry point."""
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print_help()
        return

    command = args[0]

    if command == "init":
        cmd_init()
    elif command == "run":
        cmd_run("--dry-run" in args)
    elif command == "test":
        cmd_test()
    elif command == "status":
        cmd_status()
    elif command == "agents":
        cmd_agents()
    elif command == "audit":
        cmd_audit()
    elif command == "demo":
        cmd_demo()
    else:
        print(f"Unknown command: {command}")
        print_help()
        sys.exit(1)


def print_help() -> None:
    print("""
AIGovOps Agent Framework CLI

Commands:
  init       Create a new project (agents/, policies/, config)
  run        Start the framework (--dry-run for safe mode)
  test       Send a test event and verify the pipeline
  status     Show framework status
  agents     List loaded agents
  audit      Show recent audit log entries
  demo       Run the self-contained demo

Options:
  --dry-run  No external API calls (safe testing)
  -h, --help Show this help
""")


def cmd_init() -> None:
    """Create a new project structure."""
    from pathlib import Path

    dirs = ["agents", "policies/agents", "data", "logs", "backups"]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)
        print(f"  ✓ Created {d}/")

    # Create example agent
    example_agent = Path("agents/hello_world.yaml")
    if not example_agent.exists():
        example_agent.write_text("""# Example agent — responds to hello.world events
agent:
  name: personal/hello_world
  description: "A simple example agent"
  trigger: "hello.world"
  model: "gpt-4o-mini"
  temperature: 0.5
  max_tokens: 256
  system_prompt: |
    You are a friendly assistant. Respond to the greeting.

actions:
  - when: "true"
    do: log_audit
    params:
      summary: "Hello world agent executed"
""")
        print("  ✓ Created agents/hello_world.yaml")

    # Create example policy
    example_policy = Path("policies/default.yaml")
    if not example_policy.exists():
        example_policy.write_text("""# Default policies
rules:
  - name: "all_agents_can_log"
    effect: "permit"
    principal: "*"
    actions: ["log_audit", "execute"]
    resource_type: "*"
    reason: "All agents can log and execute by default"
""")
        print("  ✓ Created policies/default.yaml")

    print("\n  ✅ Project initialized! Next steps:")
    print("    1. Edit agents/hello_world.yaml")
    print("    2. Run: aigovops test")
    print("    3. Run: aigovops run --dry-run")


def cmd_run(dry_run: bool = False) -> None:
    """Start the framework."""
    from aigovops_framework import Framework

    fw = Framework(dry_run=dry_run)
    fw.load_agents()
    fw.load_policies()
    fw.start()


def cmd_test() -> None:
    """Send a test event."""
    from aigovops_framework import Framework

    fw = Framework(dry_run=True)
    fw.load_agents()
    fw.load_policies()

    event_id = fw.emit("hello.world", {"message": "Test event from CLI"})
    print(f"  ✓ Emitted event #{event_id}: hello.world")
    print(f"  ✓ Framework status: {fw.status}")


def cmd_status() -> None:
    """Show framework status."""
    from aigovops_framework import Framework

    fw = Framework(dry_run=True)
    fw.load_agents()
    fw.load_policies()
    status = fw.status

    print(f"\n  AIGovOps Agent Framework Status")
    print(f"  {'─' * 40}")
    print(f"  Agents loaded:      {status['agents_loaded']}")
    print(f"  Policy rules:       {status['policies_loaded']}")
    print(f"  Pending approvals:  {status['pending_approvals']}")
    print(f"  Dry-run:            {status['dry_run']}")
    print(f"  Cache hit rate:     {status['cache_stats']['hit_rate']:.0%}")
    print()


def cmd_agents() -> None:
    """List loaded agents."""
    from pathlib import Path
    import yaml

    agents_dir = Path("agents")
    if not agents_dir.exists():
        print("  No agents/ directory found. Run: aigovops init")
        return

    print(f"\n  Loaded Agents")
    print(f"  {'─' * 50}")
    for f in sorted(agents_dir.glob("*.yaml")):
        with f.open() as fh:
            data = yaml.safe_load(fh)
        agent = data.get("agent", {})
        name = agent.get("name", f.stem)
        trigger = agent.get("trigger", "—")
        model = agent.get("model", "—")
        print(f"  {name:<30} trigger={trigger:<20} model={model}")
    print()


def cmd_audit() -> None:
    """Show recent audit log."""
    from aigovops_framework import StateStore

    store = StateStore()
    entries = store.get_audit_log(limit=20)

    if not entries:
        print("  No audit log entries yet.")
        return

    print(f"\n  {'#':>4} {'Agent':<28} {'Action':<15} {'Status':<8} {'Summary'}")
    print(f"  {'─'*4} {'─'*28} {'─'*15} {'─'*8} {'─'*30}")
    for e in entries:
        print(f"  {e['seq']:>4} {e['agent']:<28} {e['action']:<15} {e['status']:<8} {(e.get('result_summary') or '')[:30]}")
    print()


def cmd_demo() -> None:
    """Run the demo script."""
    import subprocess
    from pathlib import Path
    demo = Path("scripts/demo.py")
    if demo.exists():
        subprocess.run([sys.executable, str(demo)])
    else:
        print("  Demo script not found at scripts/demo.py")


if __name__ == "__main__":
    main()
