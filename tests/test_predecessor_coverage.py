from src.line_balancer.io_utils import read_operations
import pandas as pd
import tempfile
import os

# Test: Missing operation ID from predecessor column
print('Test: Missing operation ID from predecessor column')
print('IDs: 1, 2, 3, 4, 5')
print('Predecessors: Op1=[], Op2=[1], Op3=[2], Op4=[4], Op5=[4]')
print('Expected: ID 3 is missing from predecessor column')
try:
    df = pd.DataFrame({
        'Serial No.': [1, 2, 3, 4, 5],
        'Operation': ['Op1', 'Op2', 'Op3', 'Op4', 'Op5'],
        'Predecessor': ['-', '1', '2', '4', '4'],  # ID 3 is missing
        'Machine Type': ['M1', 'M2', 'M3', 'M4', 'M5'],
        'Basic Time': [10, 20, 30, 40, 50]
    })
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False).name
    df.to_csv(temp_file, index=False)
    try:
        read_operations(temp_file)
        print('FAILED: Should have raised ValueError for missing ID in predecessor column')
    except ValueError as e:
        print(f'PASSED: {e}')
    finally:
        os.unlink(temp_file)
except Exception as e:
    print(f'ERROR: {e}')

# Test: Duplicate operation ID in predecessor column
print('\nTest: Duplicate operation ID in predecessor column')
print('IDs: 1, 2, 3, 4, 5')
print('Predecessors: Op1=[], Op2=[1], Op3=[1], Op4=[3], Op5=[4]')
print('Expected: ID 1 appears twice in predecessor column')
try:
    df = pd.DataFrame({
        'Serial No.': [1, 2, 3, 4, 5],
        'Operation': ['Op1', 'Op2', 'Op3', 'Op4', 'Op5'],
        'Predecessor': ['-', '1', '1', '3', '4'],  # ID 1 appears twice
        'Machine Type': ['M1', 'M2', 'M3', 'M4', 'M5'],
        'Basic Time': [10, 20, 30, 40, 50]
    })
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False).name
    df.to_csv(temp_file, index=False)
    try:
        read_operations(temp_file)
        print('FAILED: Should have raised ValueError for duplicate ID in predecessor column')
    except ValueError as e:
        print(f'PASSED: {e}')
    finally:
        os.unlink(temp_file)
except Exception as e:
    print(f'ERROR: {e}')

# Test: Valid case - each ID appears exactly once
print('\nTest: Valid case - each ID appears exactly once')
print('IDs: 1, 2, 3, 4, 5')
print('Predecessors: Op1=[], Op2=[1], Op3=[2], Op4=[3], Op5=[4]')
print('Expected: Should pass validation')
try:
    df = pd.DataFrame({
        'Serial No.': [1, 2, 3, 4, 5],
        'Operation': ['Op1', 'Op2', 'Op3', 'Op4', 'Op5'],
        'Predecessor': ['-', '1', '2', '3', '4'],  # Perfect chain
        'Machine Type': ['M1', 'M2', 'M3', 'M4', 'M5'],
        'Basic Time': [10, 20, 30, 40, 50]
    })
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False).name
    df.to_csv(temp_file, index=False)
    try:
        ops = read_operations(temp_file)
        print(f'PASSED: Validation succeeded, {len(ops)} operations loaded')
    except ValueError as e:
        print(f'FAILED: {e}')
    finally:
        os.unlink(temp_file)
except Exception as e:
    print(f'ERROR: {e}')

print('\nAll predecessor coverage tests completed')
