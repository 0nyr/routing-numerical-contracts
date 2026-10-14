import ast
from fractions import Fraction as Q
from ncci.contracts import ROOT
from ncci.static import left, evaluate, temporal


def test_checker_static_loop_is_unchanged_between_tags():
    functions = []
    for version in ('v011', 'v012'):
        tree = ast.parse((ROOT / 'vendor' / version / 'src/mamut_routing_lib/checker.py').read_text())
        functions.append(next(ast.dump(node) for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_check_common_route_constraints'))
    assert functions[0] == functions[1]


def test_exact_decimal_and_binary_ranking_can_differ():
    assert Q('0.1') + Q('0.2') == Q('0.3')
    assert Q(0.1) + Q(0.2) != Q(0.3)
    assert left([0.1, 0.2]) > left([0.3])


def test_static_boundary_depends_on_input_interpretation():
    instance = {'depot': 0, 'arc_costs': [[0, .1, 0], [0, 0, .2], [0, 0, 0]],
                'service_times': [0, 0, 0], 'time_windows': [[0, 10], [0, 10], [0, .3]]}
    assert not temporal(instance, [[1, 2]], lambda x: x)
    assert not temporal(instance, [[1, 2]], Q)
    assert temporal(instance, [[1, 2]], lambda x: Q(str(x)))


def test_integral_total_does_not_establish_arc_scaling_eligibility():
    instance = {'depot': 0, 'num_customers': 1, 'demands': [0, 1],
                'vehicle_capacity': 1, 'arc_costs': [[0, .0004], [.0006, 0]]}
    result = evaluate(instance, [[1]])
    assert Q(result['decimal_exact']) * 1000 == 1
    assert not result['scale1000_exact']
    assert not result['scale1000_fits_int64']
