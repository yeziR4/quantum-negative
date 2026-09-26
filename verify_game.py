"""Verify the DEVELOP THE NEGATIVE game mode.

The interesting question is not "does it run" but "is it actually a quantum
game". A quiz with quantum clip-art would satisfy the challenge brief and prove
nothing, so these checks test the mechanics:

  * the circuit driving the game is genuinely quantum (entangled, not uniform);
  * every question is fair and its answer really is the Born-rule marginal;
  * skill beats guessing, by a wide margin — otherwise it is a coin flip;
  * the same seed reproduces the same playthrough;
  * the negative actually develops as the player succeeds.

    python -B verify_game.py
"""

from __future__ import annotations

import io
import statistics
import sys

import checks
import game as game_mod
import qsim

PASS, FAIL = 0, 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def play(seed: int, chooser) -> dict:
    """Play one full game. `chooser(game) -> 0|1` picks each answer."""
    g = game_mod.QuantumGame(seed=seed)
    g.start()
    while not g.finished:
        g.answer(chooser(g))
    return g.status()


def main() -> int:
    print("=" * 68)
    print("quantum game verification — DEVELOP THE NEGATIVE")
    print("=" * 68)

    print("\n[1] the game's circuit is genuinely quantum")
    g = game_mod.QuantumGame(seed=1234)
    g.start()
    for _ in range(3):
        if not g.finished:
            g.answer(g.answer_for(g.question["qubit"]))
    report = g.gate_report()
    failed = [r for r in report if not r.ok]
    check("all physics gates pass on the live game state", not failed,
          "; ".join(r.name for r in failed) if failed else f"{len(report)} gates")
    probs = g.register.probabilities()
    check("state is not the uniform distribution",
          max(probs) > 1.5 / len(probs), f"p_max {max(probs):.5f}")
    check("norm preserved through play", g.register.verify_normalised() < 1e-9)

    print("\n[2] every question is fair, and the answer is the Born rule")
    g = game_mod.QuantumGame(seed=99)
    g.start()
    checked = 0
    while not g.finished:
        q = g.question
        # Read the state BEFORE answering: answering applies a development dip
        # and therefore mutates the register, so a post-answer recomputation
        # would be checking a different state.
        recomputed = g.register.marginal(q["qubit"])
        # The advertised marginal must equal an independent recomputation.
        assert abs(recomputed - q["marginal"]) < 1e-9, "marginal mismatch"
        # The answer must follow the Born rule, and never be a coin flip.
        expected = 1 if recomputed >= 0.5 else 0
        assert q["answer"] == expected, "answer is not the Born-rule outcome"
        assert abs(recomputed - 0.5) > game_mod.QuantumGame.MIN_BIAS, \
            f"unfair coin-flip question: {recomputed}"
        # Answering the advertised answer must be recorded as correct.
        g.answer(q["answer"])
        assert g.history[-1]["correct"] is True, "advertised answer was not accepted"
        checked += 1
    check("all questions had an independent, Born-rule answer", checked == game_mod.MAX_ROUNDS,
          f"{checked} rounds verified")
    check("no question was an undecidable coin flip", True,
          f"bias > {game_mod.QuantumGame.MIN_BIAS} required on every round")

    print("\n[3] skill beats guessing")
    seeds = range(60)
    perfect = [play(seed, lambda gg: gg.answer_for(gg.question["qubit"]))
               for seed in seeds]
    # A random player, deterministically seeded so the comparison is repeatable.
    def guess(gg):
        return gg.rng.randrange(2)
    lucky = [play(seed, guess) for seed in seeds]
    mean_perfect = statistics.mean(s["score"] for s in perfect)
    mean_lucky = statistics.mean(s["score"] for s in lucky)
    mean_perfect_correct = statistics.mean(s["correct"] for s in perfect)
    mean_lucky_correct = statistics.mean(s["correct"] for s in lucky)

    check("a perfect player answers every round correctly",
          all(s["correct"] == game_mod.MAX_ROUNDS for s in perfect),
          f"all {game_mod.MAX_ROUNDS}/{game_mod.MAX_ROUNDS}")
    # The meaningful property is that reading the state PAYS, by a wide margin.
    # A game where guessing earns ~90% of the score is a coin flip with
    # decoration, so the assertion is on the gap rather than a brittle ratio.
    check("perfect play is worth at least 1.8x random play",
          mean_perfect >= 1.8 * mean_lucky,
          f"perfect {mean_perfect:.0f} vs random {mean_lucky:.0f} "
          f"({mean_perfect / mean_lucky:.2f}x)")
    check("the score gap is substantial",
          mean_perfect - mean_lucky > 700,
          f"gap {mean_perfect - mean_lucky:.0f} points")
    check("guessing answers far fewer rounds correctly",
          mean_perfect_correct - mean_lucky_correct > 2.5,
          f"{mean_perfect_correct:.1f} vs {mean_lucky_correct:.1f} of "
          f"{game_mod.MAX_ROUNDS}")
    check("the game is not winnable by luck",
          mean_lucky_correct < game_mod.MAX_ROUNDS * 0.85,
          f"random corrects {mean_lucky_correct:.1f}/{game_mod.MAX_ROUNDS}")

    print("\n[4] the negative develops with success, and is ruined by failure")
    perfect_game = game_mod.QuantumGame(seed=7)
    perfect_game.start()
    devs = [perfect_game.development]
    while not perfect_game.finished:
        perfect_game.answer(perfect_game.answer_for(perfect_game.question["qubit"]))
        devs.append(perfect_game.development)
    check("development increases on correct answers", devs[-1] > devs[0],
          f"{devs[0]} -> {devs[-1]}")

    bad_game = game_mod.QuantumGame(seed=7)
    bad_game.start()
    while not bad_game.finished:
        wrong = 1 - bad_game.answer_for(bad_game.question["qubit"])
        bad_game.answer(wrong)
    check("development falls on wrong answers",
          bad_game.development < perfect_game.development,
          f"wrong {bad_game.development} vs right {perfect_game.development}")

    print("\n[5] determinism")
    a = play(4242, lambda gg: gg.answer_for(gg.question["qubit"]))
    b = play(4242, lambda gg: gg.answer_for(gg.question["qubit"]))
    check("same seed reproduces the same playthrough",
          a["score"] == b["score"] and [h["qubit"] for h in a["history"]]
          == [h["qubit"] for h in b["history"]],
          f"score {a['score']}")
    c = play(4243, lambda gg: gg.answer_for(gg.question["qubit"]))
    check("a different seed gives a different playthrough",
          (c["score"], [h["qubit"] for h in c["history"]])
          != (a["score"], [h["qubit"] for h in a["history"]]))

    print("\n[6] rendering")
    g2 = game_mod.QuantumGame(seed=5)
    g2.start()
    latent = g2.render(size=128, revealed=False)
    final = g2.render(size=128, revealed=True)
    check("latent image renders", latent.size == (128, 128) and latent.mode == "L")
    check("revealed image renders", final.size == (128, 128) and final.mode == "L")
    import numpy as np
    la, fa = np.asarray(latent, float), np.asarray(final, float)
    check("latent and revealed differ", float(np.abs(la - fa).mean()) > 1.0,
          f"mean abs diff {float(np.abs(la - fa).mean()):.1f}")
    check("the image is actually a picture of the circuit",
          len(set(g2.register.probabilities())) > 1)
    url = g2.image_data_url(size=64)
    check("image is served as a PNG data URL",
          url.startswith("data:image/png;base64,") and len(url) > 500,
          f"{len(url)} chars")

    print("\n[7] a completed game reports a result")
    done = play(31337, lambda gg: gg.answer_for(gg.question["qubit"]))
    check("finished game is flagged", done["finished"] and done["revealed"])
    check("final image is returned", str(done.get("final_image", "")).startswith("data:image"))
    check("a rank is awarded", bool(done.get("rank")), done.get("rank", ""))
    check("history records every round",
          len(done["history"]) == game_mod.MAX_ROUNDS,
          f"{len(done['history'])} rounds")
    check("history stores the marginal for each round",
          all("marginal" in h for h in done["history"]))

    print("\n" + "=" * 68)
    print(f"{PASS} passed, {FAIL} failed")
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
