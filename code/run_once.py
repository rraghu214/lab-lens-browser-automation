"""Direct CLI runner — invokes AgentRunner without the NiceGUI UI."""
import asyncio, pathlib, sys, json

async def main():
    from agent_runner import AgentRunner
    from run_trace import RunTrace
    from llm_client import load_env
    load_env(".env")

    goal     = "Thyroid Profile (T3, T4, TSH) price"
    locality = "Koramangala, Bangalore"

    trace = RunTrace(goal=goal, locality=locality)
    root  = pathlib.Path(f"./run_artifacts/{trace.run_id}")
    root.mkdir(parents=True, exist_ok=True)

    def log(line: str) -> None:
        safe = line.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8", errors="replace")
        print(safe, flush=True)

    runner = AgentRunner(
        log_push=log,
        options={"online": True, "nearby": True},
    )
    await runner.run(trace, root)

    replay = root / "replay.json"
    data   = json.loads(replay.read_text())
    print("\n=== RESULT SUMMARY ===")
    print(f"run_id: {data['run_id']}")
    for s in data["sources"]:
        print(f"  {s['name']:12s} layer={s['layer']} success={s['success']} "
              f"tok_in={s['tokens_in']} tok_out={s['tokens_out']} elapsed={s['elapsed_s']}s")
    print("\n--- comparison_rows ---")
    for r in data.get("comparison_rows", []):
        print(f"  {r.get('provider'):12s} price={r.get('price')} "
              f"home_collection={r.get('home_collection')} notes={r.get('notes','')[:60]}")
    print(f"\nrun_id: {data['run_id']}")

asyncio.run(main())
