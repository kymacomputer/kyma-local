"""Exact history counts and resumable storage under large/concurrent inputs."""
import _test_home  # isolate state before Kyma imports or subprocesses

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kyma import ensure_home, remask_log, state_append
from kyma import HOME, agents, enforce, index, light, rules, scan, signals, sources


TS = "2026-11-21T10:05:00Z"
POLICY = "- Never use sudo.\n"


def call(command="sudo echo hi", ts=TS):
    return {"type": "assistant", "timestamp": ts, "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": command}}
    ]}}


class Scale(unittest.TestCase):
    def setUp(self):
        ensure_home()
        os.makedirs(light.CACHE, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "history.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rows):
        with self.path.open("w") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")

    def hour_snapshot(self, cache, source, calls, people=None):
        import hashlib
        cache.mkdir(exist_ok=True)
        name = hashlib.sha1(str(source).encode()).hexdigest() + ".json"
        (cache / name).write_text(json.dumps({"s": f"{light.VERSION}:1:1", "p": str(source),
                                            "b": source.name, "a": calls, "y": people or {}}))

    @contextmanager
    def discovered_history(self):
        root = Path(self.tmp.name)
        with ExitStack() as stack:
            for name, value in (("CLAUDE_ROOT", str(root / ".claude/projects")),
                                ("CODEX_ROOT", str(root / ".codex/sessions")),
                                ("CODEX_ARCHIVE", str(root / ".codex/archived_sessions"))):
                stack.enter_context(patch.object(sources, name, value))
            stack.enter_context(patch.object(light, "CACHE", str(root / "hours")))
            stack.enter_context(patch.object(light, "_pool", lambda: ThreadPoolExecutor(max_workers=1)))
            yield root

    def test_alias_owner_survives_append_after_alias_disappears(self):
        with self.discovered_history() as root:
            canonical = root / ".claude/projects/p/z-canonical.jsonl"
            alias = canonical.with_name("a-alias.jsonl")
            canonical.parent.mkdir(parents=True)
            canonical.write_text(json.dumps(call("echo original")) + "\n")
            counts = [sum(light.gather()["a"].values())]
            os.link(canonical, alias)
            counts.append(sum(light.gather()["a"].values()))
            alias.unlink()
            with canonical.open("a") as fh:
                fh.write(json.dumps(call("echo appended")) + "\n")
            counts.append(sum(light.gather()["a"].values()))
            canonical.unlink()
            counts.append(sum(light.gather()["a"].values()))
            self.assertEqual(counts, [1, 1, 2, 2])

    def test_stale_retained_path_cannot_join_new_hard_link(self):
        with self.discovered_history() as root:
            prior = root / ".claude/projects/p/z-prior.jsonl"
            current = prior.with_name("a-current.jsonl")
            prior.parent.mkdir(parents=True)
            prior.write_text(json.dumps(call("echo prior session")) + "\n")
            counts = [sum(light.gather()["a"].values())]
            prior.unlink()
            current.write_text(json.dumps(call("echo distinct new session")) + "\n")
            os.link(current, prior)
            counts.append(sum(light.gather()["a"].values()))
            current.unlink()
            prior.unlink()
            counts.append(sum(light.gather()["a"].values()))
            self.assertEqual(counts, [1, 2, 2])

    def test_same_size_same_second_replacement_is_a_distinct_history(self):
        with self.discovered_history() as root:
            prior = root / ".claude/projects/p/z-prior.jsonl"
            current = prior.with_name("a-current.jsonl")
            prior.parent.mkdir(parents=True)
            prior.write_text(json.dumps(call("echo first")) + "\n")
            self.assertEqual(sum(light.gather()["a"].values()), 1)
            before = prior.stat()
            prior.unlink()
            current.write_text(json.dumps(call("echo other")) + "\n")
            stamp = (before.st_mtime_ns // 1_000_000_000) * 1_000_000_000 + 1
            if stamp == before.st_mtime_ns:
                stamp += 1
            os.utime(current, ns=(stamp, stamp))
            self.assertEqual(current.stat().st_size, before.st_size)
            self.assertEqual(int(current.stat().st_mtime), int(before.st_mtime))
            os.link(current, prior)
            self.assertEqual(sum(light.gather()["a"].values()), 2)
            current.unlink()
            prior.unlink()
            self.assertEqual(sum(light.gather()["a"].values()), 2)

    def test_legacy_equal_stamp_replacement_never_establishes_new_inode_union(self):
        with self.discovered_history() as root:
            prior = root / ".claude/projects/p/z-prior.jsonl"
            current = prior.with_name("a-current.jsonl")
            prior.parent.mkdir(parents=True)
            prior.write_text(json.dumps(call("echo old")) + "\n")
            before = prior.stat()
            self.assertEqual(sum(light.gather()["a"].values()), 1)
            for cp in (root / "hours").glob("*.json"):
                d = json.loads(cp.read_text())
                for field in ("i", "f", "h", "bytes", "r"):
                    d.pop(field, None)
                cp.write_text(json.dumps(d))
            prior.unlink()
            current.write_text(json.dumps(call("echo new")) + "\n")
            os.utime(current, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertEqual(current.stat().st_size, before.st_size)
            os.link(current, prior)
            self.assertEqual(sum(light.gather()["a"].values()), 2)
            current.unlink()
            prior.unlink()
            self.assertEqual(sum(light.gather()["a"].values()), 2)

    def test_native_archive_retains_identity_after_hard_link_owner_change(self):
        with self.discovered_history() as root:
            canonical = root / ".codex/sessions/rollout-z.jsonl"
            alias = canonical.with_name("rollout-a.jsonl")
            archive = root / ".codex/archived_sessions" / canonical.name
            canonical.parent.mkdir(parents=True)
            archive.parent.mkdir(parents=True)
            canonical.write_text(json.dumps({"type": "response_item", "timestamp": TS, "payload": {
                "type": "function_call", "name": "exec_command", "arguments": "{}"}}) + "\n")
            counts = [sum(light.gather()["a"].values())]
            os.link(canonical, alias)
            counts.append(sum(light.gather()["a"].values()))
            alias.unlink()
            canonical.rename(archive)
            counts.append(sum(light.gather()["a"].values()))
            archive.unlink()
            counts.append(sum(light.gather()["a"].values()))
            self.assertEqual(counts, [1, 1, 1, 1])

    def test_generic_path_replacement_does_not_inherit_alias_ownership(self):
        with self.discovered_history() as root:
            canonical = root / ".claude/projects/p/z-canonical.jsonl"
            alias = canonical.with_name("a-alias.jsonl")
            canonical.parent.mkdir(parents=True)
            canonical.write_text(json.dumps(call("echo original")) + "\n")
            self.assertEqual(sum(light.gather()["a"].values()), 1)
            os.link(canonical, alias)
            self.assertEqual(sum(light.gather()["a"].values()), 1)
            alias.unlink()
            canonical.write_text(json.dumps(call("echo replaced transcript")) + "\n")
            self.assertEqual(sum(light.gather()["a"].values()), 2)
            canonical.unlink()
            self.assertEqual(sum(light.gather()["a"].values()), 2)

    def test_alias_owned_hours_stay_once_after_canonical_source_deletion(self):
        root = Path(self.tmp.name)
        cache = root / "hours"
        real = root / ".codex/sessions/2026/11/21/rollout-alias.jsonl"
        real.parent.mkdir(parents=True)
        real.write_text(json.dumps({"type": "response_item", "timestamp": TS, "payload": {
            "type": "function_call", "name": "exec_command", "arguments": json.dumps({"cmd": "echo fixture"})}}) + "\n")
        mirror = root / ".codex/sessions/mirror"
        mirror.symlink_to(real.parents[2], target_is_directory=True)
        alias = mirror / "11/21" / real.name
        work = [(str(alias), "codex")]
        with patch.object(light, "CACHE", str(cache)), patch.object(light, "files", lambda: work), \
                patch.object(light, "_pool", lambda: ThreadPoolExecutor(max_workers=1)):
            self.assertEqual(sum(light.gather()["a"].values()), 1)
            # The released predecessor stored no durable identity.
            for cp in cache.glob("*.json"):
                d = json.loads(cp.read_text())
                for field in ("k", "i", "f", "h", "bytes", "r"):
                    d.pop(field, None)
                cp.write_text(json.dumps(d))
            work[:] = [(str(real), "codex")]
            self.assertEqual(sum(light.gather()["a"].values()), 1)
            mirror.unlink()
            self.assertEqual(sum(light.gather()["a"].values()), 1)
            real.unlink()
            work.clear()
            retained = light.gather()
            self.assertEqual(sum(retained["a"].values()), 1)
            self.assertEqual(retained["kept"], 1)

    def test_native_move_and_compression_keep_nonoverlapping_hours_and_appends(self):
        root = Path(self.tmp.name)
        cache = root / "hours"
        name = "rollout-2026-11-21T10-00-00-12345678-1234-1234-1234-123456789abc.jsonl"
        first, second, third = [light._ukey(t) for t in (TS, "2026-11-21T11:05:00Z", "2026-11-21T12:05:00Z")]
        self.hour_snapshot(cache, root / ".codex/sessions/2026/11/21" / name, {first: 1}, {first: 1})
        self.hour_snapshot(cache, root / ".codex/archived_sessions" / name, {first: 2, second: 1}, {first: 1})
        self.hour_snapshot(cache, root / ".codex/archived_sessions" / (name + ".zst"), {second: 1, third: 1})
        with patch.object(light, "CACHE", str(cache)), patch.object(light, "files", lambda: []), \
                patch.object(light, "_pool", lambda: ThreadPoolExecutor(max_workers=1)), \
                patch.object(light, "_scan", side_effect=AssertionError("deleted sources must not be read")):
            retained = light.gather()
            self.assertEqual(retained["a"], {light._local(first): 2, light._local(second): 1, light._local(third): 1})
            self.assertEqual(retained["y"], {light._local(first): 1})
            self.assertEqual(retained["kept"], 1)
            self.assertEqual(light.gather(), retained)
        identities = {json.loads(cp.read_text())["k"] for cp in cache.glob("*.json")}
        self.assertEqual(len(identities), 1)

    def test_hard_link_owner_change_persists_only_one_source_history(self):
        root = Path(self.tmp.name)
        cache = root / "hours"
        first = root / ".claude/projects/a/session.jsonl"
        second = root / ".claude/projects/a/canonical.jsonl"
        first.parent.mkdir(parents=True)
        first.write_text(json.dumps(call("echo fixture")) + "\n")
        os.link(first, second)
        work = [(str(first), "claude")]
        with patch.object(light, "CACHE", str(cache)), patch.object(light, "files", lambda: work), \
                patch.object(light, "_pool", lambda: ThreadPoolExecutor(max_workers=1)):
            self.assertEqual(sum(light.gather()["a"].values()), 1)
            work[:] = [(str(second), "claude")]
            self.assertEqual(sum(light.gather()["a"].values()), 1)
            first.unlink()
            second.unlink()
            work.clear()
            self.assertEqual(sum(light.gather()["a"].values()), 1)

    def test_retained_same_names_in_distinct_sessions_stores_and_projects_add(self):
        root = Path(self.tmp.name)
        cache = root / "hours"
        cell = light._ukey(TS)
        session1 = "12345678-1234-1234-1234-123456789abc"
        session2 = "12345678-1234-1234-1234-123456789def"
        paths = [root / ".claude/projects/a/session.jsonl", root / ".claude/projects/b/session.jsonl",
                 root / ".claude/projects/a" / session1 / "subagents/agent-shared.jsonl",
                 root / ".claude/projects/a" / session2 / "subagents/agent-shared.jsonl",
                 root / ".codex/sessions/rollout-shared.jsonl", root / "other-codex/sessions/rollout-shared.jsonl"]
        for path in paths:
            self.hour_snapshot(cache, path, {cell: 1})
        with patch.object(light, "CACHE", str(cache)), patch.object(light, "files", lambda: []), \
                patch.object(light, "_pool", lambda: ThreadPoolExecutor(max_workers=1)):
            retained = light.gather()
            self.assertEqual(sum(retained["a"].values()), len(paths))
            self.assertEqual(retained["kept"], len(paths))

    def test_more_than_five_thousand_holds_and_append(self):
        self.write(call() for _ in range(6007))
        marks, done = light._judge((str(self.path), "claude", POLICY))
        self.assertTrue(done)
        self.assertEqual(len(marks), 6007)
        with self.path.open("a") as fh:
            fh.write(json.dumps(call()) + "\n")
        again, done = light._judge((str(self.path), "claude", POLICY))
        self.assertTrue(done)
        self.assertEqual(len(again), 6008)
        self.assertEqual(sum(bool(m[3]) for m in again), 60)

    def test_byte_cursor_resumes_inside_multi_call_record(self):
        self.write([{"type": "user", "message": "x" * 200_000},
                    dict(call(), message={"content": call()["message"]["content"] * 10})])
        ticks = iter(range(1000))
        with patch.object(light.time, "monotonic", side_effect=lambda: next(ticks)), \
             patch.object(light, "_FILE_BUDGET", 3):
            part, done = light._judge((str(self.path), "claude", POLICY))
        self.assertFalse(done)
        self.assertEqual(len(part), 3)
        saved = json.loads(Path(light._held_cache(str(self.path))).read_text())
        self.assertGreater(saved["cursor"]["offset"], 200_000)
        self.assertEqual(saved["cursor"]["item"], 3)
        positions = []
        original = sources._open_log

        class Tracked:
            def __init__(self, wrapped):
                self.wrapped = wrapped
            def __getattr__(self, name):
                return getattr(self.wrapped, name)
            def seek(self, pos):
                positions.append(pos)
                return self.wrapped.seek(pos)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.wrapped.close()

        with patch.object(sources, "_open_log", side_effect=lambda p: Tracked(original(p))):
            full, done = light._judge((str(self.path), "claude", POLICY))
        self.assertTrue(done)
        self.assertEqual(len(full), 10)
        self.assertEqual(positions, [saved["cursor"]["offset"]])
        self.assertEqual(json.loads(Path(light._held_cache(str(self.path))).read_text())["n"], 10)

    def test_codex_cursor_preserves_context_and_call_position(self):
        self.write([
            {"timestamp": TS, "type": "session_meta", "payload": {"cwd": "/w", "timestamp": TS}},
            {"timestamp": TS, "type": "turn_context", "payload": {"cwd": "/w/project"}},
            {"timestamp": TS, "type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
                "input": 'await tools.exec_command({cmd: "sudo one"}); await tools.exec_command({cmd: "sudo two"});'}},
            {"timestamp": TS, "type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
                "arguments": json.dumps({"cmd": "sudo three"})}},
        ])
        cursor = {"offset": 0, "item": 0}
        reader = sources._read_codex(str(self.path), cursor=cursor)
        first = next(reader)
        self.assertEqual(first.project, "/w/project")
        saved = dict(cursor)
        reader.close()
        rest = list(sources._read_codex(str(self.path), cursor=saved))
        self.assertEqual([a.command for a in rest], ["sudo two", "sudo three"])
        self.assertTrue(all(a.project == "/w/project" for a in rest))

    def test_compressed_resume_budget_starts_after_old_prefix(self):
        self.path = self.path.with_suffix(".jsonl.zst")
        self.path.write_bytes(b"compressed fixture")
        clock = [0]

        def decoded_actions(_path):
            for i in range(7):
                clock[0] += 3
                yield sources.Action("codex", "exec_command", TS, "sudo echo hi",
                                     call_id=f"{i + 1:064x}")

        reached = []
        with patch.object(sources, "_read_codex", decoded_actions), \
                patch.object(light.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(light, "_FILE_BUDGET", 8):
            for _ in range(3):
                marks, done = light._judge((str(self.path), "codex", POLICY))
                saved = json.loads(Path(light._held_cache(str(self.path))).read_text())
                reached.append(saved["n"])

        # On later passes, just decoding the already checked prefix exceeds
        # the budget. Each pass still makes progress without duplicate holds.
        self.assertEqual(reached, [3, 6, 7])
        self.assertTrue(done)
        self.assertEqual(len(marks), 7)
        self.assertEqual(saved["checked"], 7)
        self.assertEqual(len({m[4]["call_id"] for m in marks}), 7)

    def test_compressed_first_action_after_slow_preamble_makes_progress(self):
        self.path = self.path.with_suffix(".jsonl.zst")
        self.path.write_bytes(b"compressed fixture with slow preamble")
        clock = [0]

        def decoded_actions(_path):
            clock[0] += 30
            yield sources.Action("codex", "exec_command", TS, "sudo echo hi")

        with patch.object(sources, "_read_codex", decoded_actions), \
                patch.object(light.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(light, "_FILE_BUDGET", 8):
            marks, done = light._judge((str(self.path), "codex", POLICY))
        self.assertTrue(done)
        self.assertEqual(len(marks), 1)

    def test_partial_last_record_is_retried_after_append(self):
        full = json.dumps(call()).encode()
        self.path.write_bytes(full[:80])
        cursor = {"offset": 0, "item": 0}
        self.assertEqual(list(sources._read_claude(str(self.path), cursor=cursor)), [])
        self.assertEqual(cursor["offset"], 0)
        with self.path.open("ab") as fh:
            fh.write(full[80:] + b"\n")
        self.assertEqual(len(list(sources._read_claude(str(self.path), cursor=cursor))), 1)

    def test_function_backslash_arguments_do_not_stall_history_replay(self):
        self.write([
            call(r'''f() { git "$@"; }; f push '\x' '''),
            call(r'''f() { printf '%s' "$@"; }; f '\1' '''),
            call(r'''f() { "$@"; }; f 'g\151t' push'''),
        ])
        marks, done = light._judge((str(self.path), "claude", "Ask me before any git push."))
        self.assertTrue(done)
        self.assertEqual(len(marks), 1)
        self.assertEqual(marks[0][1], "ask")
        saved = json.loads(Path(light._held_cache(str(self.path))).read_text())
        self.assertEqual(saved["checked"], 3)

    def test_coverage_bounds_order_timestamps_by_instant(self):
        earlier = "2026-11-21T12:05:00+03:00"
        self.write([call(ts=TS), call(ts=earlier)])
        _marks, done, coverage = light._judge_coverage((str(self.path), "claude", POLICY))
        self.assertTrue(done)
        self.assertEqual(coverage["first"], earlier)
        self.assertEqual(coverage["last"], TS)
        self.assertEqual(coverage["n"], 2)

    def test_rule_replay_has_no_distinct_command_or_path_cap(self):
        rows = [call(f"sudo echo unique-{i}") for i in range(501)]
        rows += [call("sudo echo unique-500")] * 4
        rows += [{"type": "assistant", "timestamp": TS, "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": f"/w/file-{i}"}}
        ]}} for i in range(503)]
        rows.append(call("echo " + "x" * 240 + "; sudo echo beyond-the-excerpt"))
        self.write(rows)
        data = index.digest_file((str(self.path), "claude"))
        self.assertEqual(len(data["commands"]), 502)
        self.assertEqual(len(data["touched"]), 503)
        self.assertEqual(data["unkept"], 0)
        rule = rules.parse(POLICY)[0]
        result = scan.replay([rule], data, budget=30)
        self.assertEqual(result["checked"], result["total"])
        self.assertEqual(result["held"][id(rule)], 506)

    def test_migration_preserves_concurrent_append_without_blocking_transform(self):
        log = Path(HOME) / "log.jsonl"
        marker = Path(HOME) / ".log-masked-2"
        marker.unlink(missing_ok=True)
        log.write_text(json.dumps({"verdict": "block", "subject": "legacy", "rule": "old"}) + "\n")
        entered, appended = threading.Event(), threading.Event()
        redact = signals.redact
        failures = []

        def transform(text):
            if text == "legacy":
                entered.set()
                if not appended.wait(3):
                    failures.append("the long transform blocked the hook append")
            return redact(text)

        def writer():
            if entered.wait(3):
                state_append(str(log), json.dumps({"verdict": "ask", "subject": "concurrent", "rule": "new"}) + "\n")
            else:
                failures.append("migration did not enter the transform")
            appended.set()

        thread = threading.Thread(target=writer)
        thread.start()
        with patch.object(signals, "redact", side_effect=transform):
            remask_log()
        thread.join(4)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual([json.loads(s)["subject"] for s in log.read_text().splitlines()], ["legacy", "concurrent"])
        self.assertTrue(marker.exists())

    def test_hook_counts_and_rule_counts_cover_whole_log(self):
        log = Path(enforce.LOG)
        with log.open("w") as fh:
            for i in range(3007):
                fh.write(json.dumps({"ts": TS, "verdict": "block", "rule": "old" if i < 1007 else "new",
                                     "subject": 'echo "verdict": "ask"'}) + "\n")
        out = light._hook_totals()
        self.assertEqual(out, {"block": 3007, "ask": 0, "by_rule": {"old": 1007, "new": 2000}})
        with log.open("a") as fh:
            fh.write(json.dumps({"ts": TS, "verdict": "ask", "rule": "old"}) + "\n")
        out = light._hook_totals()
        self.assertEqual(out["ask"], 1)
        self.assertEqual(out["by_rule"]["old"], 1008)

    def test_picture_keeps_both_cohorts_and_separate_exact_counts(self):
        k = light._key(TS)
        shape = light.shape({"a": {k: 6000}, "held": {
            "past": [[k, "block", "past rule", "sudo x"]] * 6000,
            "live": [[k, "ask", "live rule", "git push"]] * 2000,
            "hook": {"block": 0, "ask": 5000, "by_rule": {"live rule": 5000}},
        }})
        self.assertEqual(len(shape["marks"]), light.MARKS_KEPT)
        self.assertEqual(sum(m["live"] for m in shape["marks"]), light.MARKS_KEPT // 2)
        self.assertEqual(shape["by_rule"], {"past rule": 6000})
        self.assertEqual(shape["live_by_rule"], {"live rule": 5000})
        self.assertEqual(shape["held_past"], 6000)
        self.assertEqual(shape["asked_live"], 5000)
        self.assertEqual(shape["marks_total"], 11000)

    def test_partial_coverage_counts_actions_and_exact_file_set(self):
        paths = [("newest", "claude"), ("middle", "claude"), ("oldest", "claude")]
        def judged(item):
            complete = item[0] != "middle"
            return [], complete, {"n": 3, "first": TS, "last": TS}
        with patch.object(light, "files", return_value=paths), \
             patch.object(light, "rules_text", return_value=(POLICY, True)), \
             patch.object(light, "_pool", side_effect=lambda: ThreadPoolExecutor(3)), \
             patch.object(light, "_judge_coverage", side_effect=judged), \
             patch.object(light, "_hook_totals", return_value={"block": 0, "ask": 0}), \
             patch.object(enforce, "held", return_value=[]):
            held = light.held_moments()
        self.assertEqual(held["judged"], 2)
        self.assertEqual(held["partial_logs"], 1)
        self.assertEqual(held["checked_calls"], 9)
        self.assertEqual(set(held["paths"]), {"newest", "middle", "oldest"})
        self.assertEqual(held["checked_first"], TS)
        self.assertEqual(held["checked_last"], TS)

    def test_agent_cards_follow_returned_files_not_a_newest_prefix(self):
        paths = [("newest", "claude"), ("middle", "claude"), ("oldest", "claude")]
        with patch.object(light, "files", return_value=paths), \
             patch.object(light, "rules_text", return_value=(POLICY, True)), \
             patch.object(agents, "_session", side_effect=lambda p, *_: {"id": p}), \
             patch.object(agents, "_held", return_value=[[TS, "block", "rule", "sudo"]]):
            cards = agents.sessions(limit=1, judged=["oldest"])
        self.assertEqual([a["id"] for a in cards], ["newest", "oldest"])


if __name__ == "__main__":
    unittest.main()
