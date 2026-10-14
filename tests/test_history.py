from fractions import Fraction

from ncci.history import pair_comparison, score
from ncci.contracts import fold, OLD, NEW


def candidate(values, count=1):
    result=score(values)
    result.update(canonical_flat=result['flat'],num_routes=count)
    return result


def test_decimal_tie_changes_legacy_ranking():
    a=candidate([1e16,1.,1.]);b=candidate([1.,1.,1e16])
    result=pair_comparison(a,b,'MonoCost')
    assert result['legacy_rank']==-1
    assert result['decimal_rank']==0


def test_fleet_priority_is_preserved():
    a=candidate([100.],1);b=candidate([1.],2)
    result=pair_comparison(a,b,'HierarchicalVehicleCost')
    assert result['legacy_rank']==result['decimal_rank']==-1
    assert pair_comparison(a,b,'MonoCost')['legacy_rank']==1


def test_conversion_models_are_distinct():
    result=score([.1,.2])
    assert Fraction(result['decimal'])==Fraction(3,10)
    assert Fraction(result['binary'])!=Fraction(result['decimal'])


def test_preloaded_fold_retains_the_rifki_witness():
    from test_contracts import rifki
    record,route=rifki()
    for version,module in [('v011',OLD),('v012',NEW)]:
        arcs={(i,j):module.NDCPWLF(xs,ys) for i,j,xs,ys in record['arcs']}
        ordinary=fold(record,route,version)
        preloaded=fold(record,route,version,prepared_arcs=arcs)
        assert {k:v for k,v in ordinary.items() if k!='seconds'}=={k:v for k,v in preloaded.items() if k!='seconds'}
