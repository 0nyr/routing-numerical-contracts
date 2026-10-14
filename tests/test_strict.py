from fractions import Fraction as Q
import math
import random
from ncci.contracts import exact_unit_slope, NEW, STRICT


def test_rounded_slope_guard_counterexample():
    a,b,c,d,x=0.,2.**-51,5.,5.,0.011393229166666666
    exact=Q(b)+Q(x)*(Q(d)-Q(b))/Q(c)
    assert d-b==c-a
    assert not exact_unit_slope(a,b,c,d)
    assert NEW._interpolate(a,b,c,d,x,True)!=float(exact)
    assert STRICT._interpolate(a,b,c,d,x,True)==float(exact)


def test_error_free_predicate_against_exact_binary_differences():
    rng=random.Random(108)
    for _ in range(2000):
        values=[math.ldexp(rng.random(),rng.randrange(-200,200)) for _ in range(4)]
        a,b,c,d=values
        if rng.random()<.5:c,d=b,a
        assert exact_unit_slope(a,b,c,d)==(Q(d)-Q(b)==Q(c)-Q(a))
