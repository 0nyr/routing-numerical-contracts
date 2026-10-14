from fractions import Fraction as Q
import random
import pytest
from ncci.exact import Stage, optimize, forward, number


def test_known_jump_and_singleton():
    stages = [Stage((Q(0), Q(5), Q(20)), (Q(7), Q(7), Q(25))),
              Stage((Q(0), Q(7), Q(7), Q(20)), (Q(1), Q(8), Q(30), Q(43)))]
    result = optimize(stages, Q(0), Q(20))
    assert (result["duration"], result["departure"], result["attained"]) == (Q(3), Q(5), True)
    assert optimize(stages, Q(5), Q(5))["duration"] == 3
    assert not optimize([*stages, Stage(latest=Q(7))], Q(0), Q(20))["feasible"]


def test_plateau_deadline_and_nonunit_preimage():
    stages = [Stage((Q(0), Q(20)), (Q(2), Q(32))), Stage(earliest=Q(8), latest=Q(17), service=Q(3))]
    result = optimize(stages, Q(0), Q(20))
    assert (result["duration"], result["departure"]) == (Q(7), Q(4))
    assert forward(stages, Q(10)) == 20
    assert forward(stages, Q(10) + Q(1, 100)) is None


def test_unattained_infimum_is_not_reported_as_an_optimum():
    # The first map jumps into the second map's domain immediately after 0.
    stages = [Stage((Q(0), Q(0), Q(1)), (Q(0), Q(1), Q(2))),
              Stage((Q(1), Q(2)), (Q(2), Q(4)))]
    result = optimize(stages, Q(0), Q(1))
    assert result["duration"] == 2 and not result["attained"]


def test_binary_and_decimal_are_distinct_inputs():
    assert number(0.1, "binary") != number("0.1", "decimal")
    assert number("0.1", "decimal") == Q(1, 10)


@pytest.mark.parametrize("seed", range(80))
def test_against_exhaustive_integer_grid(seed):
    rng = random.Random(seed)
    stages = []
    for _ in range(3):
        xs, ys = [Q(0)], [Q(rng.randrange(1, 5))]
        for x in range(1, 31):
            if rng.random() < .2:
                xs.append(Q(x - 1)); ys.append(ys[-1] + rng.randrange(1, 4))
            xs.append(Q(x)); ys.append(ys[-1] + (0 if ys[-1] > x + 2 and rng.random() < .2 else 1))
        stages.append(Stage(tuple(xs), tuple(ys)))
        stages.append(Stage(earliest=Q(rng.randrange(0, 6)), latest=Q(25), service=Q(rng.randrange(0, 3))))
    result = optimize(stages, Q(0), Q(20))
    grid = [(forward(stages, Q(t)) - t, Q(t)) for t in range(21) if forward(stages, Q(t)) is not None]
    assert result["feasible"] == bool(grid)
    if grid:
        assert (result["duration"], result["departure"]) == min(grid)
