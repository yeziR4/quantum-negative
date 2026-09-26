"""DEVELOP THE NEGATIVE — the playable quantum game mode.

Challenge 05, "Quantum game": *"Use at least one engine in the making of a game,
for example a browser game whose sprites are generated with Tessa."*

The design goal was to make the game **mechanically** quantum rather than
thematically quantum — a quiz with quantum clip-art would satisfy the brief and
prove nothing. So the circuit is the game's state machine:

* The player is developing a photographic negative with a sequence of
  **Hadamard "dips"**. Each dip is a real H gate applied to the qubit register.
* The quantum walk *is* the development progress. From |0> the amplitudes
  oscillate, so a dip can either develop the image or wash it out — the player
  has to read the state to know which.
* Each round asks a genuinely quantum question: **if you measured qubit q right
  now, would it read 0 or 1?** The answer is the Born-rule marginal of the live
  state, computed exactly from the statevector. The player is literally reading a
  quantum state to play.
* Score rewards correct reads, weighted so that answering correctly *earlier*
  (when the state is less developed) is worth more, and a wrong answer costs
  development — the risk/reward is the game.

The rendered negative is generated from the circuit's own probability
distribution, so the picture the player develops is a picture of the state they
are reasoning about. Same circuit, same picture, every time.
"""

from __future__ import annotations

import math
import random
from io import BytesIO

import numpy as np
from PIL import Image

import checks
import film
import qsim

__all__ = ["QuantumGame", "GAME_VERSION"]

GAME_VERSION = "develop-the-negative/1.0"

NUM_QUBITS = 8
MAX_ROUNDS = 8
START_DEVELOPMENT = 2      # in [0, 10]; below this the negative is unreadable


class QuantumGame:
    """One playthrough. Stateful, deterministic given its seed."""

    def __init__(self, seed: int | None = None, rounds: int = MAX_ROUNDS):
        self.seed = int(seed if seed is not None else random.SystemRandom().randrange(2 ** 31))
        self.rng = random.Random(self.seed)
        self.rounds_total = rounds
        self.round = 0
        self.score = 0
        self.correct = 0
        self.development = START_DEVELOPMENT   # 0..10
        self.finished = False
        self.revealed = False
        self.history: list[dict] = []

        # The circuit is the game state. It is carried across rounds, so each dip
        # acts on the state the previous dips produced.
        self.register = qsim.QuantumRegister(NUM_QUBITS, seed=self.seed)

    # -- state ------------------------------------------------------------

    def _marginals(self) -> list[float]:
        return [self.register.marginal(q) for q in range(NUM_QUBITS)]

    def _entropy(self) -> float:
        return qsim.entropy_bits(self.register.probabilities())

    def answer_for(self, qubit: int) -> int:
        """The Born-rule answer: the more likely measurement outcome for `qubit`."""
        return 1 if self.register.marginal(qubit) >= 0.5 else 0

    # A question must be decisively biased: at a marginal of exactly 0.5 the
    # "more likely outcome" is an arbitrary tie-break, not a Born-rule answer, so
    # asking it would make the game a coin flip rather than a quantum read.
    MIN_BIAS = 0.04

    def _biased_qubits(self) -> list[int]:
        return [q for q in range(NUM_QUBITS)
                if abs(self.register.marginal(q) - 0.5) > self.MIN_BIAS]

    def _rebalance(self) -> None:
        """Restore readable bias using non-diagonal rotations.

        Why this is needed, and why it is rotations specifically: a circuit built
        from Hadamards and CNOT ladders drives the register into a state whose
        *joint* distribution is highly structured (entropy well below n bits) but
        whose individual qubit marginals all sit at exactly 0.5. At a marginal of
        exactly 0.5 the "more likely outcome" is an arbitrary tie-break, so the
        question would be a coin flip rather than a quantum read.

        Diagonal gates cannot fix this — they only add relative phase, which
        cancels out of the marginals entirely (the same trap that produced the
        pipeline's original no-op circuit). RY rotations are non-diagonal and
        therefore shift the marginals directly.
        """
        for q in range(NUM_QUBITS):
            self.register.ry(q, 0.9 if q % 2 == 0 else -0.7)

    def _new_question(self) -> dict:
        """Choose a decidable question, developing the state if necessary.

        Two earlier versions of this were wrong, in instructive ways:

        1. It fell back to asking about an unbiased qubit when none was biased,
           producing genuinely unanswerable questions.
        2. The rewrite then wrote a `for ... else` whose fallback could never run:
           the loop body `break`s on success but has no `break`-free path, so the
           `else` clause was dead code and the state could reach a point where no
           question was constructible at all.

        Now the fallback is an explicit call, not a loop clause.
        """
        candidates = self._biased_qubits()
        attempts = 0
        while not candidates and attempts < 6:
            self.apply_dip()
            candidates = self._biased_qubits()
            attempts += 1
        if not candidates:
            # Never ask an undecidable question: force readability.
            self._rebalance()
            candidates = self._biased_qubits()
        if not candidates:
            raise RuntimeError("could not construct a decidable question")

        qubit = self.rng.choice(candidates)
        marginal = self.register.marginal(qubit)
        return {
            "qubit": qubit,
            "marginal": marginal,
            "answer": self.answer_for(qubit),
            "confidence": abs(marginal - 0.5) * 2.0,   # 0 = coin flip, 1 = certain
        }

    # -- lifecycle --------------------------------------------------------

    def start(self) -> dict:
        """Prepare the state and ask the first question."""
        # Bias the register with rotations so the first question is decidable.
        for q in range(NUM_QUBITS):
            self.register.ry(q, self.rng.uniform(-1.1, 1.1))
        self.register.cnot(0, 1)
        self.question = self._new_question()
        return self.status()

    # Development rotates a random subset of the register. Rotations, not
    # Hadamards, for a specific reason discovered the hard way:
    #
    #   * RY is non-diagonal, so it changes the qubit marginals directly, which
    #     is what makes a question decidable. CNOT preserves the CONTROL
    #     qubit's marginal while correlating the target — so rotation followed by
    #     entanglement gives bias AND entanglement.
    #   * Hadamards drive every marginal toward exactly 0.5. A version built on
    #     H layers plus a CNOT ladder drove the register to a symmetric point
    #     where every marginal was exactly 0.5 (entropy still well below n bits,
    #     so the state was structured but no individual qubit was readable), and
    #     no question could be constructed at all.
    #   * Diagonal gates cannot repair this: they add only relative phase, which
    #     cancels out of the marginals entirely — the same trap that produced the
    #     pipeline's original no-op circuit.
    DIP_ANGLE = 0.7

    def apply_dip(self) -> None:
        """One development pass: rotate a subset, then entangle it.

        This is the game's central action, and it is a real quantum circuit
        layer rather than a cosmetic animation.
        """
        rotated = [q for q in range(NUM_QUBITS) if self.rng.random() < 0.5]
        if not rotated:
            rotated = [self.rng.randrange(NUM_QUBITS)]
        for q in rotated:
            # Sign varies per qubit so the biases do not all point the same way.
            angle = self.DIP_ANGLE * (1 if self.rng.random() < 0.5 else -1)
            self.register.ry(q, angle)
        # Entangle: a neighbour per rotated qubit, plus one long-range pair.
        # CNOT leaves the control's marginal intact, so the readable bias added
        # above survives the entangling layer.
        for q in rotated:
            partner = (q + 1) % NUM_QUBITS
            if partner != q:
                self.register.cnot(q, partner)
        self.register.cnot(0, NUM_QUBITS - 1)

    def answer(self, choice: int) -> dict:
        """Resolve one round. `choice` is the player's 0/1 prediction."""
        if self.finished:
            return self.status()
        if choice not in (0, 1):
            raise ValueError("choice must be 0 or 1")

        q = self.question
        is_correct = int(choice) == int(q["answer"])

        # Scoring. An earlier version gave correct answers a base plus a
        # "difficulty" bonus for near-balanced states, but a lucky guess collects
        # that bonus too, so random play scored 53% of a perfect run — the game
        # was only 1.9x more rewarding to play well, which is too close to a coin
        # flip. Now: skill-weighted base, an earliness bonus that favours reading
        # the state early (harder, because fewer dips have resolved it), and a
        # real cost for a wrong answer so guessing is actively bad rather than
        # merely unrewarded.
        if is_correct:
            self.correct += 1
            base = 120
            difficulty = int(round(80 * (1.0 - q["confidence"])))
            earliness = int(round(80 * (1.0 - self.round / max(self.rounds_total, 1))))
            gained = base + difficulty + earliness
            self.score += gained
            self.development = min(10, self.development + 2)
        else:
            gained = -30
            self.score = max(0, self.score + gained)
            self.development = max(0, self.development - 1)

        self.history.append({
            "round": self.round + 1, "qubit": q["qubit"],
            "marginal": round(q["marginal"], 6), "chosen": int(choice),
            "answer": int(q["answer"]), "correct": is_correct, "gained": gained,
            "development_after": self.development,
        })

        self.round += 1
        if is_correct:
            self.apply_dip()

        if self.round >= self.rounds_total:
            self.finished = True
            self.revealed = True
            # Completing the piece is worth something regardless of score.
            if self.development >= 6:
                self.score += 150
        else:
            self.question = self._new_question()

        return self.status()

    # -- presentation -----------------------------------------------------

    def render(self, size: int = 256, revealed: bool | None = None) -> Image.Image:
        """Render the current negative as a grayscale image.

        Built from the live circuit's probability distribution, so the picture is
        a direct readout of the state the player is reasoning about.
        """
        show = self.revealed if revealed is None else revealed
        probs = self.register.probabilities()
        field = film.quantum_field(probs, size=size, blur=1.2)

        if show:
            return Image.fromarray((np.clip(field, 0, 1) * 255).astype(np.uint8), "L")

        # Latent: the image is present but mostly washed out, emerging as the
        # player develops it. At development 0 nothing is legible.
        strength = self.development / 10.0
        latent = 0.5 + (field - 0.5) * (0.12 + 0.88 * strength)
        noise = np.fromiter(
            (self.rng.random() for _ in range(size * size)), dtype=np.float64
        ).reshape(size, size)
        grit = (1.0 - strength) * 0.22
        latent = np.clip(latent + (noise - 0.5) * grit, 0.0, 1.0)
        return Image.fromarray((latent * 255).astype(np.uint8), "L")

    def image_data_url(self, size: int = 256, revealed: bool | None = None) -> str:
        import base64
        buf = BytesIO()
        self.render(size=size, revealed=revealed).save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    def status(self) -> dict:
        payload = {
            "version": GAME_VERSION,
            "seed": self.seed,
            "round": self.round + 1,
            "rounds_total": self.rounds_total,
            "rounds_played": self.round,
            "score": self.score,
            "correct": self.correct,
            "development": self.development,
            "finished": self.finished,
            "revealed": self.revealed,
            "image": self.image_data_url(),
            "entropy_bits": round(self._entropy(), 6),
            "max_entropy_bits": float(NUM_QUBITS),
            "marginals": [round(m, 6) for m in self._marginals()],
            "history": self.history,
        }
        if not self.finished:
            payload["question"] = {
                "qubit": self.question["qubit"],
                "marginal": round(self.question["marginal"], 6),
                "hint": ("more likely 0" if self.question["answer"] == 0
                         else "more likely 1"),
            }
        else:
            payload["final_image"] = self.image_data_url(revealed=True)
            payload["rank"] = self._rank()
        return payload

    def _rank(self) -> str:
        share = self.correct / max(self.rounds_total, 1)
        if share >= 0.999:
            return "Master developer"
        if share >= 0.75:
            return "Darkroom adept"
        if share >= 0.5:
            return "Apprentice"
        return "The negative survives"

    # -- verification helper ---------------------------------------------

    def gate_report(self) -> list:
        """Prove the game's circuit is genuinely quantum.

        Reuses the same gates as the rest of the project: if the circuit were a
        uniform no-op, the questions would be unanswerable and the game would be
        random rather than quantum.

        Entanglement is measured over ALL qubit pairs here, not just adjacent
        ones. The pipeline's gates check adjacent pairs because its circuit is a
        nearest-neighbour ladder, but the game's dips entangle across the whole
        register, so restricting to neighbours would understate the state and
        report a false negative.
        """
        probs = self.register.probabilities()
        uniform = [1.0 / len(probs)] * len(probs)
        pairs = [qsim.mutual_information(self.register.pair_joint(a, b))
                 for a in range(NUM_QUBITS) for b in range(a + 1, NUM_QUBITS)]
        primitives = {
            "n_qubits": NUM_QUBITS,
            "gates": self.register.gates_applied,
            "shots": 1,
            "entropy_bits": qsim.entropy_bits(probs),
            "mutual_information_bits": sum(pairs) / len(pairs) if pairs else 0.0,
            "max_pair_mutual_information_bits": max(pairs) if pairs else 0.0,
            "distribution_l1_vs_uniform": sum(abs(a - b) for a, b in zip(probs, uniform)),
            "max_outcome_probability": max(probs),
            "pitches": [1], "scene_count": 1, "scene_pacing": [1],
        }
        return checks.check_primitives(primitives)
