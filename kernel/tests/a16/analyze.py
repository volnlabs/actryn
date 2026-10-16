#!/usr/bin/env python3
"""Summarize the frozen eight-run A16 matrix; preserve failed/missing trials."""
import argparse
import json
import math
import pathlib
import statistics

ARMS = ("kernel", "kernel", "userspace", "userspace", "userspace", "userspace", "kernel", "kernel")


def distribution(values):
    values = sorted(values)
    if not values:
        return {"count": 0, "median_ns": None, "p95_ns": None, "observed_max_ns": None}
    return {"count": len(values), "median_ns": statistics.median(values),
            "p95_ns": values[math.ceil(len(values) * .95) - 1], "observed_max_ns": values[-1]}


def summarize(records):
    manifests = [r for r in records if r["type"] == "manifest"]
    if len(manifests) != 1 or manifests[0].get("planned_trials") != 10 or manifests[0].get("revision") != 1:
        raise ValueError("one frozen revision-1 manifest with ten planned trials required")
    manifest = manifests[0]
    if manifest.get("arm") not in {"kernel", "userspace"}:
        raise ValueError("unknown arm")
    begins, ends = {}, {}
    for r in records:
        if r["type"] in {"trial_begin", "trial_end"}:
            target = begins if r["type"] == "trial_begin" else ends
            trial = r["trial"]
            if trial not in range(10) or trial in target:
                raise ValueError("duplicate or invalid trial identity")
            target[trial] = r
    if ends.keys() - begins.keys():
        raise ValueError("trial end without begin")
    requests = [r for r in records if r["type"] == "request"]
    events = [r for r in records if r["type"] == "event"]
    metrics = {name: [] for name in ("admission", "sample_to_applied", "cancel_to_closure",
               "cancel_to_quiesced", "finish_to_quiesced", "recover_to_baseline", "owner_to_closure",
               "observation_age_at_sample")}
    samples, applied, misses, reversed_clock = 0, 0, 0, 0
    def elapsed(before, after):
        nonlocal reversed_clock
        if after < before:
            reversed_clock += 1
            return None
        return after - before
    def matching(r, kind):
        return [e for e in events if e["trial"] == r["trial"] and e["kind"] == kind
                and (not r.get("operation") or e["operation"] == r["operation"])
                and e["captured_ns"] >= r["before_ns"]]
    for r in requests:
        dt = elapsed(r["before_ns"], r["after_ns"])
        if dt is not None:
            metrics["admission"].append(dt)
        if r["rc"]:
            continue
        opcode = r["opcode"]
        if opcode == 8:
            samples += 1
            observations = [o for o in requests if o["trial"] == r["trial"] and o["opcode"] == 6
                            and not o["rc"] and o.get("observation") == r.get("observation")
                            and o["after_ns"] <= r["before_ns"] and "acquired_earliest_ns" in o]
            if observations:
                age = elapsed(observations[-1]["acquired_earliest_ns"], r["before_ns"])
                if age is not None:
                    metrics["observation_age_at_sample"].append(age)
            receipts = [e for e in matching(r, 0x20008) if e["sample"] == r["sequence"]]
            timely = [e for e in receipts if e["captured_ns"] < r["deadline_ns"]]
            if timely:
                applied += 1
                metrics["sample_to_applied"].append(min(e["captured_ns"] for e in timely) - r["before_ns"])
            else:
                misses += 1
        for request_op, kind, metric in ((10, 0x30002, "cancel_to_closure"),
                (10, 0x2000A, "cancel_to_quiesced"), (9, 0x2000A, "finish_to_quiesced"),
                (12, 0x20004, "recover_to_baseline")):
            if opcode == request_op:
                rows = matching(r, kind)
                if rows:
                    metrics[metric].append(min(e["captured_ns"] for e in rows) - r["before_ns"])
    for r in records:
        if r["type"] == "owner_exit":
            times = [e["captured_ns"] for e in events if e["trial"] == r["trial"]
                     and e["kind"] == 0x30005 and e["captured_ns"] >= r["before_exit_ns"]]
            if times:
                metrics["owner_to_closure"].append(min(times) - r["before_exit_ns"])
    if any(r["lost_final"] < begins[t]["lost_baseline"] for t, r in ends.items()):
        raise ValueError("cumulative event loss counter regressed")
    loss = sum(r["lost_final"] - begins[t]["lost_baseline"] for t, r in ends.items())
    event_gaps = sum(b["sequence"] != a["sequence"] + 1 for a, b in zip(events, events[1:]))
    resources = {r["phase"]: r for r in records if r["type"] == "resources"}
    cpu = None
    if resources.keys() >= {"begin", "end"}:
        first, last = resources["begin"], resources["end"]
        if first["clock_ticks"] != last["clock_ticks"]:
            raise ValueError("guest clock-tick configuration changed")
        delta = [b - a for a, b in zip(first["guest_cpu_ticks"], last["guest_cpu_ticks"])]
        if len(delta) != 8 or min(delta) < 0:
            raise ValueError("guest CPU counters regressed")
        cpu = {"clock_ticks": first["clock_ticks"], "guest_delta_ticks": delta,
               "guest_busy_ticks": sum(delta) - delta[3] - delta[4],
               "interval_ns": last["at_ns"] - first["at_ns"],
               "children_user_us": last["children_user_us"] - first["children_user_us"],
               "children_system_us": last["children_system_us"] - first["children_system_us"]}
    baseline_cpu = {r["phase"]: r for r in records if r["type"] == "baseline_cpu"}
    baseline = None
    if baseline_cpu.keys() >= {"begin", "end"}:
        first, last = baseline_cpu["begin"], baseline_cpu["end"]
        if first["pid"] != last["pid"]:
            raise ValueError("baseline process changed within one run")
        baseline = {key: last[key] - first[key] for key in ("user_ticks", "system_ticks")}
        if min(baseline.values()) < 0:
            raise ValueError("baseline CPU counters regressed")
    completed = [r for r in records if r["type"] == "complete"]
    return {"arm": manifest["arm"], "boot": manifest["boot"], "planned_trials": 10,
            "begun_trials": len(begins), "ended_trials": len(ends),
            "passed_trials": sum(r["pass"] for r in ends.values()),
            "failed_trials": sum(not r["pass"] for r in ends.values()),
            "unfinished_or_unstarted_trials": 10 - len(ends),
            "complete_marker": len(completed) == 1, "sample_requests": samples,
            "timely_applied": applied, "no_timely_applied": misses,
            "new_event_loss_in_ended_trials": loss, "event_loss_complete": len(ends) == 10,
            "loss_counter_saturated": any(r["lost_final"] == 0xffffffff for r in ends.values()),
            "event_sequence_discontinuities": event_gaps,
            "reversed_clock_pairs": reversed_clock, "cpu": cpu, "baseline_process_cpu_ticks": baseline,
            "metrics": {key: distribution(values) for key, values in metrics.items()},
            "admission_scope": "request call including ioctl or typed IPC; not UART dispatch",
            "dispatch_latency": "NOT_RUN: requires independently correlated UART trace",
            "physical_response": "NOT_MEASURED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", nargs=8, type=pathlib.Path,
                        help="ABBA blocks, each evidence-only then diagnostic-trace mode")
    args = parser.parse_args()
    reports = []
    for index, path in enumerate(args.events):
        records = [json.loads(line) for line in path.read_text().splitlines()]
        report = summarize(records)
        if report["arm"] != ARMS[index]:
            raise ValueError("arm order differs from frozen ABBA matrix")
        intents = sum(p.stat().st_size for p in path.parent.glob("intent-[0-9][0-9].bin"))
        report.update({"block": index // 2 + 1, "diagnostic_mode": bool(index % 2),
                       "journal_bytes": path.stat().st_size, "intent_bytes": intents,
                       "evidence_bytes": path.stat().st_size + intents, "path": str(path)})
        reports.append(report)
    for index in range(0, 8, 2):
        if reports[index]["boot"] != reports[index + 1]["boot"]:
            raise ValueError("both modes in one block require the same boot")
    if len({reports[index]["boot"] for index in range(0, 8, 2)}) != 4:
        raise ValueError("four separately recorded boots required")
    print(json.dumps({"revision": 1, "qualification": "requires independent baseline review",
          "claim": "descriptive software measurements only; no superiority or WCET inference",
          "runs": reports}, indent=2))


if __name__ == "__main__":
    main()
