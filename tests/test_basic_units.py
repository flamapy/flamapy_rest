import sys
import warnings
import pytest
from flamapy.interfaces.python.flamapy_feature_model import FLAMAFeatureModel

VALID_MODEL = "./resources/models/simple/valid_model.uvl"

VALID_CONFIG = "./resources/configurations/valid_configuration.csvconf"
def test_atomic_sets():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    expected_result=[['Cart', 'eCommerce', 'Server', 'Web', 'Security', 'Catalog', 'v74', 'Payment', 'Shopping', 'PHP', 'Storage', 'Search'], ['LOW'], ['ENOUGH'], ['BASIC'], ['ADVANCED'], ['PayPal'], ['CreditCard'], ['Mobile'], ['HIGH'], ['STANDARD'], ['Backup'], ['Marketing'], ['SEO'], ['Socials'], ['Twitter'], ['Facebook'], ['YouTube']]

    # Act
    result = flamafm.atomic_sets()

    # Assert if the size are the same (this is to speed up the test)
    assert len(result) == len(expected_result)

def test_average_branching_factor():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    
    # Act
    result = flamafm.average_branching_factor()

    # Assert
    assert result == 2.45

def test_core_features():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    expected_result=['eCommerce', 'Server', 'Web', 'Catalog', 'Search', 'Shopping', 'Security', 'Cart', 'Payment', 'PHP', 'Storage', 'v74']
    # Act
    result = flamafm.core_features()

    # Assert
    assert sorted(result) == sorted(expected_result)

def test_count_leafs():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    
    # Act
    result = flamafm.count_leafs()

    # Assert
    assert result == 17

def test_estimated_number_of_configurations():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    
    # Act
    result = flamafm.estimated_number_of_configurations()

    # Assert
    assert result == 1904


def test_estimated_number_of_configurations():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    
    # Act
    result = flamafm.estimated_number_of_configurations()

    # Assert
    assert result == 1904

def test_feature_ancestors():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    
    # Act
    result = flamafm.feature_ancestors("v74")

    # Assert
    assert result == ['PHP', 'Server', 'eCommerce']    

def test_leaf_features():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    
    # Act
    result = flamafm.leaf_features()

    # Assert
    assert sorted(result) == sorted(['v74', 'LOW', 'ENOUGH', 'Catalog', 'BASIC', 'ADVANCED', 'Cart', 'PayPal', 'CreditCard', 'Mobile', 'HIGH', 'STANDARD', 'Backup', 'SEO', 'Twitter', 'Facebook', 'YouTube'])

def test_maxdep():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    
    # Act
    result = flamafm.max_depth()

    # Assert
    assert result == 4
def test_dead_features():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    
    # Act
    result = flamafm.dead_features()

    # Assert
    assert sorted(result) == sorted([])
 

def test_false_optional_features():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    
    # Act
    result = flamafm.false_optional_features()

    # Assert
    assert sorted(result) == sorted([])

def test_filter():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)

    # Act
    result = flamafm.filter(VALID_CONFIG)

    # Assert
    assert len(result) == 68

def test_products_number():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    
    # Act
    result = flamafm.configurations_number()

    # Assert
    assert result == 816

def test_products():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    
    # Act
    result = flamafm.configurations()

    # Assert
    assert len(result) == 816

def test_commonality():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    
    # Act
    result = flamafm.commonality(VALID_CONFIG)

    # Assert
    assert 1.0 == result

def test_valid_configuration():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    
    # Act
    result = flamafm.satisfiable_configuration(VALID_CONFIG)

    # Assert
    assert result == True

def test_satisfiable_configuration():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    
    # Act
    result = flamafm.satisfiable_configuration(VALID_CONFIG)

    # Assert
    assert result == True

def test_satisfiable():
    # Prepare
    flamafm=FLAMAFeatureModel(VALID_MODEL)
    
    # Act
    result = flamafm.satisfiable()

    # Assert
    assert result == True