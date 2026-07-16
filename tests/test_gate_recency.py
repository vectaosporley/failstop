#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The gate blocks loops, not failures. There is no attempt limit.

Three designs were tried here and the first two were both wrong, in instructive ways.

  v1  lifetime totals: block if fail >= N and ok == 0.
      Wrong in both directions at once. `ok == 0` is false for anything that ever worked, and
      almost everything works once, so almost nothing could ever be blocked — the gate was
      inert. Meanwhile anything that had never worked was condemned permanently, and since
      the block stopped the command from running, it could never produce the success that
      would clear it. The evidence that would exonerate it was forbidden by the sentence.

  v2  failures since the last success: block if run >= N.
      Fixes both of those and breaks something worse. `npm test` fails five times in a row
      while you fix the code — that is not a malfunction, that is the job. A counter cannot
      tell that from a machine retrying a dead command, so it stops the fix cycle exactly
      when it is needed. The old suite caught this; those tests were right to exist.

  v3  novelty: block when the newest failure repeats an error already seen in this run.
      No threshold at all. The number was always a proxy for the question it could not ask —
      is this attempt learning anything? Ask that. Ten failures with ten different errors is
      a search and must be left alone. Two identical failures is a circle, and the second one
      proved it. The limit stops being configured and becomes emergent.

This is FS-007 read literally: do not REPEAT a failed attempt. Repeating means same input and
same output. If the output changed, you did not repeat — you advanced.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture()
def mem(tmp_path, monkeypatch):
    monkeypatch.setenv("FAILSTOP_HOME", str(tmp_path))
    import memory
    importlib.reload(memory)
    return memory


SHAPE = "cmd <path>"
BOOM = "ModuleNotFoundError: No module named 'requests'"


def _fail(mem, n, error=BOOM, shape=SHAPE, fix=""):
    for _ in range(n):
        mem.record("Bash", shape, ok=False, fix=fix, error=error)


def _ok(mem, n=1, shape=SHAPE):
    for _ in range(n):
        mem.record("Bash", shape, ok=True)


# ── a proven loop is stopped ─────────────────────────────────────────────────

def test_the_same_error_twice_is_a_loop(mem):
    """The second identical failure IS the proof. Nothing is gained by waiting for a third."""
    _fail(mem, 2)
    v = mem.check("Bash", SHAPE)
    assert v["verdict"] == "blocked"
    assert "requests" in v["repeated"]


def test_one_failure_is_never_a_loop(mem):
    """One event cannot be a repetition of itself."""
    _fail(mem, 1)
    assert mem.check("Bash", SHAPE)["verdict"] == "suspect"


def test_returning_to_an_earlier_error_is_also_a_loop(mem):
    """A, B, A — a bigger circle is still a circle. Coming back to an error you already hit
    is not progress."""
    _fail(mem, 1, error="cannot find module x")
    _fail(mem, 1, error="cannot find module y")
    _fail(mem, 1, error="cannot find module x")
    assert mem.check("Bash", SHAPE)["verdict"] == "blocked"


def test_unknown_shape_is_not_blocked(mem):
    assert mem.check("Bash", "never seen")["verdict"] == "unknown"


# ── the regression the old suite was protecting: a fix cycle must never be stopped ───

def test_a_fix_cycle_is_never_blocked_however_long(mem):
    """`npm test` failing repeatedly while the code gets fixed is the job, not a malfunction.

    Every run says something different — three failing, then two, then one. Under a counting
    gate this dies on the third run and the agent can no longer test anything. The novelty
    rule lets it run as long as it keeps learning.
    """
    for msg in ("3 tests failed: auth, db, api",
                "2 tests failed: db, api",
                "1 test failed: api",
                "1 test failed: api timeout after 30s",
                "1 test failed: api returns 500"):
        mem.record("Bash", "npm test", ok=False, error=msg)
        assert mem.check("Bash", "npm test")["verdict"] != "blocked", (
            f"blocked a fix cycle at: {msg!r} — the gate would make the work impossible")
    assert mem.check("Bash", "npm test")["run"] == 5, "five honest failures, none of them a loop"


def test_counts_inside_an_error_are_information_not_noise(mem):
    """'3 tests failed' and '2 tests failed' must not normalize to the same signature.

    normalize_shape() collapses digits so retries match — the right call for a command. Doing
    it to an error would erase the only evidence that the fix cycle is working, and turn the
    npm case above into a block on the second run. Errors normalize timidly; shapes boldly.
    """
    assert mem.normalize_error("3 tests failed") != mem.normalize_error("2 tests failed")


def test_the_difference_can_be_anywhere_in_the_error(mem):
    """The question that ended the magic number: *does it matter if it's 800 instead of 400?*

    No — and that is the diagnosis. Any fixed cut has a blind spot; changing the value only
    moves the cliff and leaves it just as invisible.

    This case defeats BOTH cuts that were tried. Head-400 dies on pytest's identical header.
    Tail-400 dies here: fix test A, break test B, and the summary reads "1 failed" both times,
    so the tail matches while the difference sits in the middle — exactly where a fixed window
    cannot see. Only hashing the whole thing has no window to miss.
    """
    relleno_cabeza = "=" * 200 + " test session starts platform win32 collected 193 items "
    cola_identica = " 1 failed, 192 passed in <dur> ===== short test summary ====="
    a = relleno_cabeza + " tests/test_auth.py F " + "x" * 500 + cola_identica
    b = relleno_cabeza + " tests/test_db.py F   " + "x" * 500 + cola_identica
    assert mem.error_signature(a) != mem.error_signature(b), (
        "misma cantidad de fallos, test distinto: la diferencia esta en el medio y hay que verla")


def test_the_signature_has_no_length_to_get_wrong(mem):
    """Un solo caracter distinto en cualquier parte de 10.000 cambia la firma. No hay ventana."""
    base = "x" * 10000
    assert mem.error_signature(base + "A" + base) != mem.error_signature(base + "B" + base)


def test_what_decides_and_what_is_read_are_different_fields(mem):
    """`sig` decide, `err` se lee. Mezclarlos es como el numero magico volvio dos veces."""
    mem.record("Bash", SHAPE, ok=False, error="Traceback...\nModuleNotFoundError: no hay 'requests'")
    e = [x for x in mem.load()["log"] if not x["ok"]][-1]
    assert len(e["sig"]) == 16 and all(c in "0123456789abcdef" for c in e["sig"])
    assert "requests" in e["err"], "lo que se lee tiene que decirle algo a un humano"


def test_the_display_keeps_the_last_lines_not_the_last_bytes(mem):
    """El unico numero que sobrevive esta en LINEAS, no en bytes — y las lineas son donde vive
    el significado: Python pone la excepcion en la ultima, pytest su veredicto en la ultima."""
    d = mem.error_display("linea uno\nlinea dos\n\nTypeError: che", lineas=2)
    assert d == "linea dos | TypeError: che"


def test_a_long_identical_header_does_not_erase_the_difference(mem):
    """Found by an eval subagent, then measured. The signature keeps the TAIL for this reason.

    pytest prints a header — platform, rootdir, plugins, collected count — that is byte-identical
    between runs, and only then prints what actually happened. Truncating from the front returns
    pure header, so two runs with different failures get the same signature and the gate blocks
    the fix cycle: the exact disaster this whole rule exists to prevent.

    It was not hypothetical. With a ~470-char header (a deep project path plus a few plugins) the
    old `[:400]` went blind. The real project measured 336 — seventy characters from firing. The
    culprit was 400, a number picked out of the air, exactly like the attempt threshold that was
    removed from the gate one layer above and then left sitting here where nobody looked.
    """
    # The header is padded with plugins rather than a deep rootdir, and both reasons are worth
    # keeping. First: the boundary guard rejected the original version of this test for carrying
    # a machine path — in the file that argues the guard works. Third time it has caught its own
    # author. Second: removing that path dropped the header to 313 chars and the assert below
    # caught that the scenario no longer reproduced anything. Same line, two failures.
    encabezado = ("=" * 79 + "\ntest session starts\n"
                  "platform win32 -- Python 3.11.9, pytest-9.0.2, pluggy-1.5.0\n"
                  "cachedir: .pytest_cache\nrootdir: <project>\nconfigfile: pytest.ini\n"
                  "plugins: anyio-4.11.0, cov-6.0.0, mock-3.14.0, randomly-3.16.0, xdist-3.6.1, "
                  "asyncio-0.24.0, timeout-2.3.1, benchmark-4.0.0, html-4.1.1, metadata-3.1.1, "
                  "forked-1.6.0, repeat-0.9.3\ncollected 193 items\n\n")
    assert len(encabezado) > 400, "el escenario solo existe si el encabezado supera el recorte"
    a = mem.normalize_error(encabezado + "tests/test_auth.py .F..F\n3 failed, 190 passed in 29.05s")
    b = mem.normalize_error(encabezado + "tests/test_auth.py .....\n1 failed, 192 passed in 31.44s")
    assert a != b, "el encabezado se comio la diferencia: el ciclo de arreglo se bloquearia"


def test_the_signature_keeps_what_changed_not_what_repeats(mem):
    """El corolario, dicho como propiedad: la firma tiene que contener la cola."""
    f = mem.normalize_error("x" * 2000 + " ModuleNotFoundError: No module named 'requests'")
    assert "requests" in f, "se perdio el error y se guardo el relleno"


def test_volatile_noise_does_not_disguise_a_repeat(mem):
    """The mirror risk: if a clock or a temp path makes every error unique, nothing ever
    repeats and the gate never fires."""
    a = mem.normalize_error("2026-07-15T10:00:01 connect failed pid=8123 in 0.30s")
    b = mem.normalize_error("2026-07-15T10:04:57 connect failed pid=9944 in 0.28s")
    assert a == b


# ── no error captured means no proof, so no block (FS-012) ───────────────────

def test_failures_without_an_error_never_block(mem):
    """A count with no words attached cannot distinguish a loop from a search, so it must not
    pretend to. Abstaining costs one repeated failure; a false block costs the session."""
    for _ in range(10):
        mem.record("Bash", SHAPE, ok=False, error="")
    v = mem.check("Bash", SHAPE)
    assert v["verdict"] == "suspect", "with nothing to compare, the gate has no grounds"
    assert v["run"] == 10


# ── recency: an old success cannot immunise, a new one must clear ────────────

def test_an_old_success_does_not_immunise_a_now_broken_shape(mem):
    """Worked once, has failed identically ever since. v1 called this 'suspect' forever."""
    _ok(mem)
    _fail(mem, 10, error="the API changed", fix="use v2 of the endpoint")
    v = mem.check("Bash", SHAPE)
    assert v["verdict"] == "blocked"
    assert v["last_fix"] == "use v2 of the endpoint"


def test_a_success_ends_the_run(mem):
    """Recency cuts both ways or it is not recency."""
    _fail(mem, 5)
    assert mem.check("Bash", SHAPE)["verdict"] == "blocked"
    _ok(mem)
    assert mem.check("Bash", SHAPE)["verdict"] == "trusted"


def test_errors_before_the_last_success_are_history_not_evidence(mem):
    """It broke, got fixed, and broke again differently. The old error is not part of this run."""
    _fail(mem, 3, error="old problem")
    _ok(mem)
    _fail(mem, 1, error="old problem")     # same string, but the run restarted
    assert mem.check("Bash", SHAPE)["verdict"] == "suspect"


# ── the escape hatch ─────────────────────────────────────────────────────────

def test_a_cleared_shape_stops_being_blocked(mem):
    """The block is self-sealing: it stops the command, so the command cannot produce the
    success that would lift it. Without a way out the only exits are hand-editing the store
    or deleting it — destroying every lesson learned to unstick one command."""
    _fail(mem, 3, fix="install the missing dependency")
    assert mem.check("Bash", SHAPE)["verdict"] == "blocked"
    mem.clear_shape("Bash", SHAPE)
    assert mem.check("Bash", SHAPE)["verdict"] != "blocked"


def test_clearing_does_not_erase_the_history(mem):
    """A clear says 'judge me from here', not 'this never happened'. A tool that can be
    argued out of its own memory has no memory."""
    _fail(mem, 3)
    mem.clear_shape("Bash", SHAPE)
    v = mem.check("Bash", SHAPE)
    assert v["fail"] == 3, "lifetime history stays visible"
    assert v["verdict"] != "blocked"


def test_the_same_error_after_a_clear_blocks_again(mem):
    """Clearing is not immunity, or it becomes the universal bypass."""
    _fail(mem, 3)
    mem.clear_shape("Bash", SHAPE)
    _fail(mem, 2)
    assert mem.check("Bash", SHAPE)["verdict"] == "blocked"


def test_clear_is_scoped_to_one_shape(mem):
    _fail(mem, 2, shape="shape A")
    _fail(mem, 2, shape="shape B")
    mem.clear_shape("Bash", "shape A")
    assert mem.check("Bash", "shape A")["verdict"] != "blocked"
    assert mem.check("Bash", "shape B")["verdict"] == "blocked", "a clear is not an amnesty"


def test_clear_survives_a_reload(mem):
    """An escape hatch that evaporates with the process is not an escape hatch."""
    _fail(mem, 2)
    mem.clear_shape("Bash", SHAPE)
    importlib.reload(mem)
    assert mem.check("Bash", SHAPE)["verdict"] != "blocked"


# ── the gate fails open (FS-012) ─────────────────────────────────────────────

def test_check_never_raises_on_a_damaged_store(mem, tmp_path):
    (tmp_path / "memory.json").write_text("{ this is not json", encoding="utf-8")
    assert mem.check("Bash", SHAPE)["verdict"] in {"unknown", "trusted", "suspect", "blocked"}


def test_a_damaged_clear_record_is_treated_as_no_clear(mem):
    """Corruption must never be a way to launder a block away."""
    _fail(mem, 2)
    db = mem.load()
    db["cleared"] = "this is not a mapping"
    mem.save(db)
    assert mem.check("Bash", SHAPE)["verdict"] == "blocked"


def test_ordering_does_not_depend_on_the_clock(mem):
    """Events are ordered by a monotonic sequence, never by a timestamp: several records land
    inside one coarse Windows clock tick, and a clear compared by time would then fail to
    separate the failures it was meant to forgive."""
    _fail(mem, 2)
    mem.clear_shape("Bash", SHAPE)
    _fail(mem, 1)
    log = [e for e in mem.load()["log"] if e["shape"] == SHAPE]
    assert [e["n"] for e in log] == sorted(e["n"] for e in log)
    assert len({e["n"] for e in log}) == len(log), "sequence numbers must be unique"
    assert mem.check("Bash", SHAPE)["verdict"] == "suspect", "only the post-clear failure counts"
